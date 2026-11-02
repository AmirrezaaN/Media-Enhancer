"""Where things live, both when running from source and inside the packaged app."""

import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# Folder with bundled read-only files (PyInstaller unpacks them into _internal).
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
# Per-user writable folder for settings and logs.
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MediaEnhancer"


def weights_dir() -> Path:
    return RESOURCE_DIR / "weights"


def asset(name: str) -> Path:
    base = RESOURCE_DIR / "desktop" / "assets" if not FROZEN else RESOURCE_DIR / "assets"
    return base / name


def ffmpeg_tool(name: str) -> str:
    """Bundled ffmpeg/ffprobe if present, otherwise whatever is on PATH."""
    bundled = RESOURCE_DIR / "ffmpeg" / f"{name}.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which(name) or name


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
