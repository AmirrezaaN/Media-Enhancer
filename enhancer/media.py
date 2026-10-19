"""Inspect uploaded files. Uploads are validated by decoding them, never by trusting the extension."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction

from django.conf import settings
from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"}
VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "avi", "m4v"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "MPO"}

# Hard upper bound for Pillow; the admin limit is checked separately with a clear message.
Image.MAX_IMAGE_PIXELS = 120_000_000


class MediaError(Exception):
    pass


@dataclass
class MediaInfo:
    width: int
    height: int
    duration: float = 0.0
    fps: float = 0.0
    frames: int = 0
    has_audio: bool = False


def media_type_for(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def probe_image(path):
    try:
        with Image.open(path) as im:
            fmt = im.format
            im.verify()
        with Image.open(path) as im:
            im.load()
            width, height = im.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise MediaError("invalid image") from exc
    if fmt not in IMAGE_FORMATS:
        raise MediaError("unsupported image format")
    return MediaInfo(width=width, height=height)


def _run_json(cmd, timeout=60):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_no_window())
    if proc.returncode != 0:
        raise MediaError("ffprobe failed")
    return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def probe_video(path):
    try:
        data = _run_json([
            settings.FFPROBE_BIN, "-v", "error",
            "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,nb_frames:"
            "stream_tags=rotate:stream_side_data=rotation:format=duration",
            "-of", "json", str(path),
        ])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        raise MediaError("invalid video") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
    if video is None:
        raise MediaError("no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    width, height = int(video["width"]), int(video["height"])
    rotation = 0
    try:
        rotation = int(float(video.get("tags", {}).get("rotate", 0)))
    except ValueError:
        pass
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    if abs(rotation) % 180 == 90:
        width, height = height, width

    fps = 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            value = float(Fraction(video.get(key, "0/1")))
        except (ValueError, ZeroDivisionError):
            value = 0.0
        if 1 <= value <= 240:
            fps = value
            break
    if not fps:
        raise MediaError("unknown frame rate")

    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise MediaError("unknown duration")

    try:
        frames = int(video.get("nb_frames") or 0)
    except ValueError:
        frames = 0
    if frames <= 0:
        frames = int(round(duration * fps))

    return MediaInfo(width=width, height=height, duration=duration, fps=fps, frames=frames, has_audio=has_audio)
