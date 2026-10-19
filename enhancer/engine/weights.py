"""Registry of AI model weights and a downloader. Weights come from the official project releases."""

import logging
import shutil
import tempfile
import urllib.request
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("enhancer")

MODELS = {
    # Fast general-purpose 4x model (Real-ESRGAN compact). Good for video.
    "realesr-general-x4v3": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
    # High quality 4x / 2x models (Real-ESRGAN RRDB).
    "RealESRGAN_x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "RealESRGAN_x2plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    # Face restoration.
    "GFPGANv1.4": "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
}


def weights_dir() -> Path:
    path = Path(settings.AI_WEIGHTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_path(name: str) -> Path:
    return weights_dir() / f"{name}.pth"


def ensure(name: str) -> Path:
    """Return the local path of a model, downloading it the first time."""
    path = model_path(name)
    if path.exists() and path.stat().st_size > 0:
        return path
    url = MODELS[name]
    logger.info("Downloading %s ...", name)
    with tempfile.NamedTemporaryFile(dir=weights_dir(), suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with urllib.request.urlopen(url, timeout=60) as response:
            shutil.copyfileobj(response, tmp, length=1024 * 1024)
    tmp_path.replace(path)
    logger.info("Saved %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path
