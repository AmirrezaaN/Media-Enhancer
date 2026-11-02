"""Background threads: loading the AI engine and running one job (charge -> process -> report)."""

import logging
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from mecore import Cancelled, EngineConfig, Options

from . import paths
from .api import ApiError

logger = logging.getLogger("desktop")


class EngineHolder:
    """Creates the engine once (importing torch takes a few seconds) and shares it."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._engine is None:
                import torch

                from mecore.core import Engine

                config = EngineConfig(
                    weights_dir=paths.weights_dir(),
                    device="cuda" if torch.cuda.is_available() else "cpu",
                    ffmpeg=paths.ffmpeg_tool("ffmpeg"),
                    ffprobe=paths.ffmpeg_tool("ffprobe"),
                )
                self._engine = Engine(config)
            return self._engine


class EngineLoader(QThread):
    ready = Signal(str, bool)  # device name, has CUDA
    error = Signal(str)

    def __init__(self, holder: EngineHolder):
        super().__init__()
        self.holder = holder

    def run(self):
        try:
            engine = self.holder.get()
            self.ready.emit(engine.device_name, engine.cuda)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Engine failed to start")
            self.error.emit(str(exc))


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path


class JobRunner(QThread):
    progress = Signal(float, str)  # percent, stage key
    charged = Signal(int, int)  # cost, coins left
    succeeded = Signal(object, float, int)  # mecore Result, seconds, coins
    failed = Signal(str, int, bool)  # message, coins (-1 if unknown), whether coins had been charged
    cancelled = Signal(int)  # coins

    def __init__(self, holder, api, settings, source: Path, media_type, info, opts: Options, out_dir: Path):
        super().__init__()
        self.holder = holder
        self.api = api
        self.settings = settings
        self.source = source
        self.media_type = media_type
        self.info = info
        self.opts = opts
        self.out_dir = out_dir
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _report(self, percent, stage=None, force=False):
        if self._cancel.is_set():
            raise Cancelled()
        self.progress.emit(float(percent), stage or "")

    def _finish(self, job_id, status, seconds=0, error=""):
        """Tell the server how the job ended. Kept for later if the server is unreachable."""
        try:
            return self.api.finish_job(job_id, status, int(seconds), error[:1500])["coins"]
        except ApiError as exc:
            logger.warning("Could not report job %s (%s), will retry later", job_id, exc)
            pending = list(self.settings.get("pending_reports") or [])
            pending.append({"job_id": job_id, "status": status, "seconds": int(seconds), "error": error[:1500]})
            self.settings.set("pending_reports", pending)
            return -1

    def run(self):
        self.progress.emit(0, "charging")
        try:
            engine = self.holder.get()
            start = self.api.start_job(
                media_type=self.media_type, quality=self.opts.quality, scale=self.opts.scale,
                face=self.opts.face, fps_boost=self.opts.fps_boost, duration=self.info.duration,
                width=self.info.width, height=self.info.height, name=self.source.name, gpu=engine.device_name,
            )
        except ApiError as exc:
            self.failed.emit(str(exc), -1, False)
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not start")
            self.failed.emit(str(exc), -1, False)
            return

        job_id = start["job_id"]
        self.charged.emit(start["cost"], start["coins"])
        stem = f"{self.source.stem}_enhanced_{self.opts.scale}x"
        started = time.monotonic()
        try:
            from mecore import process_image, process_video

            if self.media_type == "image":
                # The extension is chosen by the pipeline (.png or .jpg); reserve a unique stem.
                taken = {p.stem for p in self.out_dir.glob(f"{stem}*")}
                n = 1
                base = stem
                while stem in taken:
                    stem = f"{base} ({n})"
                    n += 1
                result = process_image(engine, self.source, self.out_dir / stem, self.opts, self._report)
            else:
                target = unique_path(self.out_dir / f"{stem}.mp4")
                result = process_video(engine, self.source, target, self.opts, self._report)
        except Cancelled:
            coins = self._finish(job_id, "cancelled", time.monotonic() - started)
            self.cancelled.emit(coins)
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job failed")
            detail = f"{type(exc).__name__}: {exc}"
            coins = self._finish(job_id, "failed", time.monotonic() - started,
                                 detail + "\n" + traceback.format_exc()[-800:])
            self.failed.emit(detail, coins, True)
            return

        seconds = time.monotonic() - started
        coins = self._finish(job_id, "done", seconds)
        self.succeeded.emit(result, seconds, coins)
