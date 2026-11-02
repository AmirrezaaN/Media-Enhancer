"""Upload inspection for the website; the actual probing lives in mecore."""

from django.conf import settings

from mecore.media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaError, MediaInfo, media_type_for, probe_image
from mecore.media import probe_video as _probe_video

__all__ = [
    "IMAGE_EXTENSIONS", "VIDEO_EXTENSIONS", "MediaError", "MediaInfo", "media_type_for", "probe_image", "probe_video",
]


def probe_video(path):
    return _probe_video(path, settings.FFPROBE_BIN)
