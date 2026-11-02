from dataclasses import dataclass
from pathlib import Path


@dataclass
class EngineConfig:
    weights_dir: Path
    # "cuda" or "cpu"
    device: str = "cuda"
    # Tile size (input pixels) for the large models; lower it on GPUs with little memory.
    tile_size: int = 512
    # "auto"/"fp16": half precision with a corruption check (recommended).
    # "fp32": everything in full precision (slowest, needs a lot of GPU memory for 4K smooth motion).
    precision: str = "auto"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # "auto" uses the NVIDIA hardware encoder when it is available, otherwise libx264.
    video_encoder: str = "auto"

    def __post_init__(self):
        self.weights_dir = Path(self.weights_dir)
