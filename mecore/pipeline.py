"""Turn an input image/video into an enhanced output file, reporting progress along the way."""

import functools
import logging
import math
import queue
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

from .core import FAST_MODEL, HIGH_MODEL_X2, HIGH_MODEL_X4, resize_tensor, to_numpy, to_tensor
from .media import NO_WINDOW, probe_video

logger = logging.getLogger("mecore")

PREVIEW_MAX_SIDE = 1600
# Above this many intermediate pixels the input is shrunk first to keep memory in check.
MAX_INTERMEDIATE_PIXELS = 200_000_000
# NVENC's H.264 encoder cannot go above 4096 pixels on either side.
NVENC_MAX_SIDE = 4096

# Video denoise levels. "pre" cleans compression noise in the source before the AI sees it (cheap,
# at the input size); "post" smooths frame-to-frame flicker of the enhanced result (temporal only,
# so sharpness inside each frame is kept).
DENOISE_FILTERS = {
    0: (None, None),
    1: ("hqdn3d=1.5:1.5:4:4", "hqdn3d=0:0:3:3"),
    2: ("hqdn3d=3:3:6:6", "hqdn3d=0:0:5:5"),
    3: ("hqdn3d=5:5:9:9", "hqdn3d=0:0:7:7"),
}

Report = Callable[..., None]


class Cancelled(Exception):
    pass


@dataclass
class Options:
    quality: str = "high"  # "fast" or "high"
    scale: int = 4  # 2 or 4
    face: bool = False
    fps_boost: bool = False  # video only
    max_side: int = 3840  # longest side of the output
    denoise: int = 1  # video only, 0-3


@dataclass
class Plan:
    model: str
    factor: float
    out_w: int
    out_h: int


@dataclass
class Result:
    output_path: Path
    width: int
    height: int
    before: np.ndarray = field(repr=False)  # preview frames, RGB, identical size
    after: np.ndarray = field(repr=False)
    repaired_tiles: int = 0


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


def preview_pair(before_rgb: np.ndarray, after_rgb: np.ndarray, max_side=PREVIEW_MAX_SIDE):
    """Before/after images of identical size for a comparison slider."""
    h, w = after_rgb.shape[:2]
    ratio = min(1.0, max_side / max(w, h))
    size = (max(1, round(w * ratio)), max(1, round(h * ratio)))
    before = Image.fromarray(before_rgb).resize(size, Image.Resampling.BICUBIC)
    after = Image.fromarray(after_rgb).resize(size, Image.Resampling.LANCZOS)
    return before, after


def save_previews(result: Result, before_path, after_path, max_side=PREVIEW_MAX_SIDE):
    before, after = preview_pair(result.before, result.after, max_side)
    for img, path in ((before, before_path), (after, after_path)):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "JPEG", quality=88)


# --------------------------------------------------------------------------- images


def process_image(engine, src, dst_stem, opts: Options, report: Report) -> Result:
    """Enhance one image. The output is dst_stem + ".png" or ".jpg" depending on the source."""
    report(2, "loading")
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        icc = im.info.get("icc_profile")
        source_format = im.format or ""
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        alpha = im.convert("RGBA").getchannel("A") if has_alpha else None
        rgb = np.asarray(im.convert("RGB"))

    height, width = rgb.shape[:2]
    plan = make_plan(width, height, opts.scale, opts.quality, opts.max_side)
    upscaler = engine.upscaler(plan.model)
    repaired_before = engine.repaired_tiles()

    model_input = rgb
    if width * height * upscaler.scale ** 2 > MAX_INTERMEDIATE_PIXELS:
        shrink = math.sqrt(MAX_INTERMEDIATE_PIXELS / (width * height * upscaler.scale ** 2))
        model_input = np.asarray(
            Image.fromarray(rgb).resize((round(width * shrink), round(height * shrink)), Image.Resampling.LANCZOS)
        )

    face_share = 25 if opts.face else 0
    up_end = 90 - face_share
    report(8, "upscaling", force=True)
    x = to_tensor(model_input, engine.device, upscaler.dtype)
    y = upscaler(x, on_progress=lambda f: report(8 + f * (up_end - 8), "upscaling"))
    y = resize_tensor(y, plan.out_h, plan.out_w)
    out = to_numpy(y)
    del x, y
    engine.free_memory()

    if opts.face:
        report(up_end, "faces", force=True)
        out = engine.faces().enhance(rgb, out)

    report(92, "encoding", force=True)
    result_img = Image.fromarray(out)
    if alpha is not None:
        result_img.putalpha(alpha.resize(result_img.size, Image.Resampling.LANCZOS))

    lossless = alpha is not None or (source_format in ("PNG", "BMP", "TIFF") and plan.out_w * plan.out_h <= 20e6)
    target = Path(f"{dst_stem}.{'png' if lossless else 'jpg'}")
    target.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = {"icc_profile": icc} if icc else {}
    if lossless:
        result_img.save(target, "PNG", compress_level=6, **save_kwargs)
    else:
        result_img.save(target, "JPEG", quality=95, subsampling=0, **save_kwargs)

    return Result(target, plan.out_w, plan.out_h, rgb, out, engine.repaired_tiles() - repaired_before)


# --------------------------------------------------------------------------- videos


def fps_string(fps: float) -> str:
    frac = Fraction(fps).limit_denominator(1001)
    return f"{frac.numerator}/{frac.denominator}"


def source_color_matrix(info) -> str:
    """The YUV->RGB matrix to decode with. Untagged files follow what players assume."""
    tagged = {
        "bt709": "bt709", "bt470bg": "bt601", "smpte170m": "bt601", "bt601": "bt601",
        "bt2020nc": "bt2020", "bt2020c": "bt2020", "smpte240m": "smpte240m", "fcc": "fcc",
    }
    if info.color_space in tagged:
        return tagged[info.color_space]
    return "bt709" if min(info.width, info.height) >= 720 else "bt601"


@functools.lru_cache(maxsize=4)
def nvenc_available(ffmpeg: str) -> bool:
    """True when h264_nvenc exists and actually works on this machine (driver/GPU support)."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def encoder_args(config, width, height):
    use_nvenc = config.video_encoder == "nvenc" or (
        config.video_encoder == "auto" and max(width, height) <= NVENC_MAX_SIDE and nvenc_available(config.ffmpeg)
    )
    if use_nvenc:
        # Constant-quality VBR with the slowest/best preset; visually equivalent to x264 CRF 16.
        return ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "17", "-b:v", "0",
                "-spatial-aq", "1", "-temporal-aq", "1", "-bf", "3", "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]


class FrameReader:
    """Decodes a video into raw RGB frames in a background thread."""

    def __init__(self, ffmpeg, path, width, height, fps, matrix, prefilter=None):
        self.frame_bytes = width * height * 3
        self.shape = (height, width, 3)
        vf = f"scale={width}:{height}:flags=lanczos:in_color_matrix={matrix}"
        if prefilter:
            vf = f"{prefilter},{vf}"
        cmd = [
            ffmpeg, "-v", "error", "-nostdin", "-i", str(path),
            "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", vf, "-fps_mode", "cfr", "-r", fps,
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
    """Encodes raw RGB frames to an H.264 MP4 in a background thread, copying audio from the source."""

    def __init__(self, config, path, width, height, fps, audio_source=None, postfilter=None, max_duration=None):
        cmd = [
            config.ffmpeg, "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", fps, "-i", "-",
        ]
        if audio_source:
            # The audio is cut to the source length instead of using -shortest: -shortest makes ffmpeg
            # stop as soon as the audio ends, which dropped the last video frames (and crashed slow jobs
            # with "Invalid argument" when the frames arrived after ffmpeg had already quit).
            if max_duration:
                cmd += ["-t", f"{max_duration:.3f}"]
            cmd += ["-i", str(audio_source), "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k"]
        vf = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
        if postfilter:
            vf = f"{postfilter},{vf}"
        cmd += ["-vf", vf, *encoder_args(config, width, height),
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-movflags", "+faststart", str(path)]
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
            raise RuntimeError(f"Video encoding failed (exit {code}, {self.error!r}): {self.error_text()}")
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


def process_video(engine, src, dst, opts: Options, report: Report) -> Result:
    """Enhance a video into dst (an .mp4 path)."""
    config = engine.config
    report(1, "loading")
    info = probe_video(src, config.ffprobe)
    plan = make_plan(info.width, info.height, opts.scale, opts.quality, opts.max_side, even=True)

    upscaler = engine.upscaler(plan.model)
    faces = engine.faces() if opts.face else None
    interpolator = engine.interpolator() if opts.fps_boost else None
    repaired_before = engine.repaired_tiles()

    in_fps = fps_string(info.fps)
    out_fps = fps_string(info.fps * 2) if interpolator else in_fps
    total = max(1, info.frames)
    preview_at = total // 2
    # With big outputs the upscaler and RIFE each keep several GB cached; together they no longer fit
    # in 8 GB and Windows starts swapping GPU memory to system RAM (many times slower). Releasing the
    # cache between the two costs a few milliseconds per frame.
    free_between = interpolator is not None and engine.cuda and plan.out_w * plan.out_h > 3_000_000
    prefilter, postfilter = DENOISE_FILTERS.get(opts.denoise, DENOISE_FILTERS[1])

    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dst.with_name(dst.stem + ".part.mp4")

    reader = FrameReader(config.ffmpeg, src, info.width, info.height, in_fps, source_color_matrix(info), prefilter)
    writer = FrameWriter(config, temp_path, plan.out_w, plan.out_h, out_fps,
                         src if info.has_audio else None, postfilter, max_duration=info.duration)
    preview = None
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
                    if free_between:
                        engine.free_memory()
                    writer.write(to_numpy(interpolator.middle(previous, y)))
                    if free_between:
                        engine.free_memory()
                previous = y
            out_np = to_numpy(y)
            writer.write(out_np)

            if count == preview_at:
                preview = (frame.copy(), out_np)
            last_in, last_out = frame, out_np
            count += 1
            report(3 + 94 * min(count / total, 1.0), "upscaling")

        if count == 0:
            raise RuntimeError("No frames could be decoded from the video.")
        if interpolator is not None and previous is not None:
            # Repeat the last frame so the doubled-FPS video keeps the original length.
            writer.write(to_numpy(previous))
        if preview is None:
            preview = (last_in.copy(), last_out)

        report(97, "encoding", force=True)
        writer.finish()
    except BaseException:
        writer.abort()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        reader.close()
        engine.free_memory()

    temp_path.replace(dst)
    return Result(dst, plan.out_w, plan.out_h, preview[0], preview[1], engine.repaired_tiles() - repaired_before)
