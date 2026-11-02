"""Media Enhancer core: the AI engine shared by the website worker and the desktop app.

Nothing in this package depends on Django, so it can be bundled into the Windows app as is.
"""

from .config import EngineConfig
from .media import MediaError, MediaInfo, media_type_for, probe_image, probe_video
from .pipeline import Cancelled, Options, Result, make_plan, process_image, process_video, save_previews

__all__ = [
    "EngineConfig", "MediaError", "MediaInfo", "media_type_for", "probe_image", "probe_video",
    "Cancelled", "Options", "Result", "make_plan", "process_image", "process_video", "save_previews",
]
