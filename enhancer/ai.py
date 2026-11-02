"""Builds the shared AI engine (mecore) from the Django settings."""

from django.conf import settings

from mecore import EngineConfig


def engine_config() -> EngineConfig:
    return EngineConfig(
        weights_dir=settings.AI_WEIGHTS_DIR,
        device=settings.AI_DEVICE,
        tile_size=settings.AI_TILE_SIZE,
        precision=settings.AI_PRECISION,
        ffmpeg=settings.FFMPEG_BIN,
        ffprobe=settings.FFPROBE_BIN,
        video_encoder=settings.VIDEO_ENCODER,
    )


def create_engine():
    from mecore.core import Engine

    return Engine(engine_config())
