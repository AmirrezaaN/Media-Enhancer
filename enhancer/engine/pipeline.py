"""Turns a Job into an enhanced output file, reporting progress along the way."""

import logging
import math
import queue
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from django.conf import settings
from PIL import Image, ImageOps

from ..media import probe_video
from .core import FAST_MODEL, HIGH_MODEL_X2, HIGH_MODEL_X4, Engine, resize_tensor, to_numpy, to_tensor

logger = logging.getLogger("enhancer")

PREVIEW_MAX_SIDE = 1600
# Above this many intermediate pixels the input is shrunk first to keep memory in check.
MAX_INTERMEDIATE_PIXELS = 200_000_000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Cancelled(Exception):
    pass


@dataclass
class Plan:
    model: str
    factor: float
    out_w: int
    out_h: int


def make_plan(width, height, scale, quality, max_side, even=False):
    factor = max(1.0, min(float(scale), max_side / max(width, height)))
    out_w, out_h = round(width * factor), round(height * factor)
    if even:
        out_w, out_h = out_w - out_w % 2, out_h - out_h % 2
    if quality == "fast":
        model = FAST_MODEL
    else:
        model = HIGH_MODEL_X2 if factor <= 2 else HIGH_MODEL_X4
    return Plan(model=model, factor=factor, out_w=out_w, out_h=out_h)


def storage_path(relative: str) -> Path:
    path = Path(settings.MEDIA_ROOT) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_previews(job, before_rgb: np.ndarray, after_rgb: np.ndarray):
    """Before/after JPEGs of identical size for the comparison slider."""
    h, w = after_rgb.shape[:2]
    ratio = min(1.0, PREVIEW_MAX_SIDE / max(w, h))
    size = (max(1, round(w * ratio)), max(1, round(h * ratio)))
    before = Image.fromarray(before_rgb).resize(size, Image.Resampling.BICUBIC)
    after = Image.fromarray(after_rgb).resize(size, Image.Resampling.LANCZOS)
    for field, img, suffix in (("input_preview", before, "before"), ("output_preview", after, "after")):
        rel = f"previews/{job.user_id}/{job.id}_{suffix}.jpg"
        img.save(storage_path(rel), "JPEG", quality=88)
        setattr(job, field, rel)


# --------------------------------------------------------------------------- images


def process_image(job, engine: Engine, report, max_side: int):
    report(2, "loading")
    with Image.open(job.input_file.path) as src:
        src = ImageOps.exif_transpose(src)
        icc = src.info.get("icc_profile")
        source_format = src.format or ""
        has_alpha = src.mode in ("RGBA", "LA", "PA") or (src.mode == "P" and "transparency" in src.info)
        alpha = src.convert("RGBA").getchannel("A") if has_alpha else None
        rgb = np.asarray(src.convert("RGB"))

    height, width = rgb.shape[:2]
    plan = make_plan(width, height, job.scale, job.quality, max_side)
    upscaler = engine.upscaler(plan.model)

    model_input = rgb
    if width * height * upscaler.scale ** 2 > MAX_INTERMEDIATE_PIXELS:
        shrink = math.sqrt(MAX_INTERMEDIATE_PIXELS / (width * height * upscaler.scale ** 2))
        model_input = np.asarray(
            Image.fromarray(rgb).resize((round(width * shrink), round(height * shrink)), Image.Resampling.LANCZOS)
        )

    face_share = 25 if job.face_enhance else 0
    up_end = 90 - face_share
    report(8, "upscaling", force=True)
    x = to_tensor(model_input, engine.device, upscaler.dtype)
    y = upscaler(x, on_progress=lambda f: report(8 + f * (up_end - 8), "upscaling"))
    y = resize_tensor(y, plan.out_h, plan.out_w)
    out = to_numpy(y)
    del x, y
    engine.free_memory()

    if job.face_enhance:
        report(up_end, "faces", force=True)
        out = engine.faces().enhance(rgb, out)

    report(92, "encoding", force=True)
    result = Image.fromarray(out)
    if alpha is not None:
        result.putalpha(alpha.resize(result.size, Image.Resampling.LANCZOS))

    lossless = alpha is not None or (source_format in ("PNG", "BMP", "TIFF") and plan.out_w * plan.out_h <= 20e6)
    ext = "png" if lossless else "jpg"
    rel = f"results/{job.user_id}/{job.id}.{ext}"
    target = storage_path(rel)
    save_kwargs = {"icc_profile": icc} if icc else {}
    if lossless:
        result.save(target, "PNG", compress_level=6, **save_kwargs)
    else:
        result.save(target, "JPEG", quality=95, subsampling=0, **save_kwargs)

    job.output_file = rel
    job.output_width, job.output_height = plan.out_w, plan.out_h
    save_previews(job, rgb, out)


# --------------------------------------------------------------------------- videos


class FrameReader:
    """Decodes a video into raw RGB frames in a background thread."""

    def __init__(self, path, width, height, fps):
        self.frame_bytes = width * height * 3
        self.shape = (height, width, 3)
        cmd = [
            settings.FFMPEG_BIN, "-v", "error", "-nostdin", "-i", str(path),
            "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", f"scale={width}:{height}:flags=lanczos",
            "-fps_mode", "cfr", "-r", fps,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]
        self.stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=self.stderr, bufsize=self.frame_bytes * 2, creationflags=NO_WINDOW
        )
        self.queue = queue.Queue(maxsize=8)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while True:
                data = self.proc.stdout.read(self.frame_bytes)
                if not data or len(data) < self.frame_bytes:
                    break
                self.queue.put(np.frombuffer(data, np.uint8).reshape(self.shape))
        finally:
            self.queue.put(None)

    def __iter__(self):
        while True:
            frame = self.queue.get()
            if frame is None:
                return
            yield frame

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        # Unblock the reader thread if it is waiting on a full queue.
        while self.thread.is_alive():
            try:
                self.queue.get(timeout=0.1)
            except queue.Empty:
                pass
        self.stderr.close()


class FrameWriter:
    """Encodes raw RGB frames to H.264 MP4 in a background thread, copying audio from the source."""

    def __init__(self, path, width, height, fps, audio_source=None):
        cmd = [
            settings.FFMPEG_BIN, "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", fps, "-i", "-",
        ]
        if audio_source:
            cmd += ["-i", str(audio_source), "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k"]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-shortest", str(path),
        ]
        self.stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self.stderr, creationflags=NO_WINDOW)
        self.queue = queue.Queue(maxsize=8)
        self.error = None
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self):
        try:
            while True:
                frame = self.queue.get()
                if frame is None:
                    break
                self.proc.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError) as exc:
            self.error = exc
            # Keep draining so the producer never blocks forever.
            while self.queue.get() is not None:
                pass

    def write(self, frame: np.ndarray):
        if self.error:
            raise RuntimeError(f"Video encoder stopped: {self.error_text()}")
        self.queue.put(frame)

    def error_text(self):
        self.stderr.seek(0)
        return self.stderr.read().decode("utf-8", "replace")[-800:]

    def finish(self):
        self.queue.put(None)
        self.thread.join()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait()
        if code != 0 or self.error:
            raise RuntimeError(f"Video encoding failed: {self.error_text()}")
        self.stderr.close()

    def abort(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        if self.thread.is_alive():
            # The killed encoder makes the writer thread fail and drain the queue until it sees None.
            self.queue.put(None)
            self.thread.join(timeout=10)
        self.stderr.close()


def fps_string(fps: float) -> str:
    frac = Fraction(fps).limit_denominator(1001)
    return f"{frac.numerator}/{frac.denominator}"


def process_video(job, engine: Engine, report, max_side: int):
    report(1, "loading")
    info = probe_video(job.input_file.path)
    plan = make_plan(info.width, info.height, job.scale, job.quality, max_side, even=True)

    upscaler = engine.upscaler(plan.model)
    faces = engine.faces() if job.face_enhance else None
    interpolator = engine.interpolator() if job.fps_boost else None

    in_fps = fps_string(info.fps)
    out_fps = fps_string(info.fps * 2) if interpolator else in_fps
    total = max(1, info.frames)
    preview_at = total // 2

    rel = f"results/{job.user_id}/{job.id}.mp4"
    final_path = storage_path(rel)
    temp_path = final_path.with_suffix(".part.mp4")

    reader = FrameReader(job.input_file.path, info.width, info.height, in_fps)
    writer = FrameWriter(temp_path, plan.out_w, plan.out_h, out_fps, job.input_file.path if info.has_audio else None)
    previews_saved = False
    count = 0
    previous = None
    last_in = last_out = None
    try:
        report(3, "upscaling", force=True)
        for frame in reader:
            x = to_tensor(frame, engine.device, upscaler.dtype)
            y = resize_tensor(upscaler(x), plan.out_h, plan.out_w)
            if faces is not None:
                y_np = faces.enhance(frame, to_numpy(y))
                y = to_tensor(y_np, engine.device, upscaler.dtype)
            if interpolator is not None:
                if previous is not None:
                    writer.write(to_numpy(interpolator.middle(previous, y)))
                previous = y
            out_np = to_numpy(y)
            writer.write(out_np)

            if count == preview_at:
                save_previews(job, frame, out_np)
                previews_saved = True
            last_in, last_out = frame, out_np
            count += 1
            report(3 + 94 * min(count / total, 1.0), "upscaling")

        if count == 0:
            raise RuntimeError("No frames could be decoded from the video.")
        if interpolator is not None and previous is not None:
            # Repeat the last frame so the doubled-FPS video keeps the original length.
            writer.write(to_numpy(previous))
        if not previews_saved:
            save_previews(job, last_in, last_out)

        report(97, "encoding", force=True)
        writer.finish()
    except BaseException:
        writer.abort()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        reader.close()
        engine.free_memory()

    temp_path.replace(final_path)
    job.output_file = rel
    job.output_width, job.output_height = plan.out_w, plan.out_h
