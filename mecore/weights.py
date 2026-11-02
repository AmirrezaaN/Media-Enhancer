"""AI model weights and a downloader. Weights come from the official project releases."""

import logging
import shutil
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger("mecore")

MODELS = {
    # Fast general-purpose 4x model (Real-ESRGAN compact). Good for video.
    "realesr-general-x4v3": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
    # High quality 4x / 2x models (Real-ESRGAN RRDB).
    "RealESRGAN_x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "RealESRGAN_x2plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    # Face restoration.
    "GFPGANv1.4": "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
}


def model_path(weights_dir: Path, name: str) -> Path:
    return Path(weights_dir) / f"{name}.pth"


def ensure(weights_dir: Path, name: str) -> Path:
    """Return the local path of a model, downloading it the first time."""
    weights_dir = Path(weights_dir)
    weights_dir.mkdir(parents=True, exist_ok=True)
    path = model_path(weights_dir, name)
    if path.exists() and path.stat().st_size > 0:
        return path
    logger.info("Downloading %s ...", name)
    with tempfile.NamedTemporaryFile(dir=weights_dir, suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with urllib.request.urlopen(MODELS[name], timeout=60) as response:
            shutil.copyfileobj(response, tmp, length=1024 * 1024)
    tmp_path.replace(path)
    logger.info("Saved %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path
