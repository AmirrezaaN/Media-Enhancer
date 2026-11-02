"""Job queue processing. One worker owns the GPU and runs jobs one at a time, oldest first."""

import logging
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Job, SiteSettings, WorkerStatus
from .views import delete_job_files, refund_job

logger = logging.getLogger("enhancer")


class ProgressReporter:
    """Writes progress to the database at most once per second and notices cancellation."""

    def __init__(self, job, device_name):
        self.job = job
        self.device_name = device_name
        self.last_write = 0.0
        self.last_beat = 0.0

    def __call__(self, percent, stage=None, force=False):
        from mecore import Cancelled

        now = time.monotonic()
        if not force and now - self.last_write < 1.0:
            return
        self.last_write = now
        fields = {"progress": round(min(float(percent), 99.5), 1)}
        if stage:
            fields["stage"] = stage
        Job.objects.filter(pk=self.job.pk).update(**fields)
        if Job.objects.filter(pk=self.job.pk).values_list("status", flat=True).first() != Job.Status.PROCESSING:
            raise Cancelled()
        if now - self.last_beat > 20:
            self.last_beat = now
            WorkerStatus.beat(self.device_name, self.job.pk)


def claim_next_job():
    for job in Job.objects.filter(status=Job.Status.QUEUED).order_by("created_at")[:5]:
        claimed = Job.objects.filter(pk=job.pk, status=Job.Status.QUEUED).update(
            status=Job.Status.PROCESSING, started_at=timezone.now(), progress=0, stage="loading"
        )
        if claimed:
            job.refresh_from_db()
            return job
    return None


def requeue_interrupted_jobs():
    """Jobs left 'processing' by a crashed or stopped worker go back to the queue."""
    n = Job.objects.filter(status=Job.Status.PROCESSING).update(
        status=Job.Status.QUEUED, progress=0, stage="", started_at=None
    )
    if n:
        logger.info("Requeued %d interrupted jobs", n)


def run_job(job, engine):
    from mecore import Cancelled, Options, process_image, process_video, save_previews

    site = SiteSettings.get()
    report = ProgressReporter(job, engine.device_name)
    WorkerStatus.beat(engine.device_name, job.pk)
    logger.info("Processing job %s (%s, %s, %dx, face=%s, fps=%s)",
                job.pk, job.media_type, job.quality, job.scale, job.face_enhance, job.fps_boost)
    opts = Options(
        quality=job.quality,
        scale=job.scale,
        face=job.face_enhance,
        fps_boost=job.fps_boost and not job.is_image,
        max_side=site.max_image_output_side if job.is_image else site.max_video_output_side,
        denoise=site.video_denoise,
    )
    media_root = Path(settings.MEDIA_ROOT)
    result_stem = f"results/{job.user_id}/{job.id}"
    started = time.monotonic()
    try:
        if job.is_image:
            result = process_image(engine, job.input_file.path, media_root / result_stem, opts, report)
        else:
            result = process_video(engine, job.input_file.path, media_root / f"{result_stem}.mp4", opts, report)
        job.output_file = result.output_path.relative_to(media_root).as_posix()
        job.input_preview = f"previews/{job.user_id}/{job.id}_before.jpg"
        job.output_preview = f"previews/{job.user_id}/{job.id}_after.jpg"
        save_previews(result, media_root / job.input_preview.name, media_root / job.output_preview.name)
        job.output_width, job.output_height = result.width, result.height
        if result.repaired_tiles:
            logger.warning("Job %s: %d corrupt GPU tiles were detected and repaired", job.pk, result.repaired_tiles)
    except Cancelled:
        logger.info("Job %s was cancelled", job.pk)
        _remove_outputs(job)
        return
    except Exception as exc:  # noqa: BLE001 - any failure must refund the user
        logger.exception("Job %s failed", job.pk)
        _remove_outputs(job)
        updated = Job.objects.filter(pk=job.pk, status=Job.Status.PROCESSING).update(
            status=Job.Status.FAILED, finished_at=timezone.now(), error_message=f"{type(exc).__name__}: {exc}"[:2000]
        )
        if updated:
            refund_job(job, "Processing failed")
        return
    finally:
        engine.free_memory()

    updated = Job.objects.filter(pk=job.pk, status=Job.Status.PROCESSING).update(
        status=Job.Status.DONE,
        progress=100,
        stage="done",
        finished_at=timezone.now(),
        output_file=job.output_file.name,
        input_preview=job.input_preview.name,
        output_preview=job.output_preview.name,
        output_width=job.output_width,
        output_height=job.output_height,
    )
    if not updated:  # cancelled at the very last moment
        _remove_outputs(job)
    logger.info("Job %s finished in %.1fs", job.pk, time.monotonic() - started)


def _remove_outputs(job):
    for field in (job.output_file, job.input_preview, job.output_preview):
        if field:
            try:
                field.delete(save=False)
            except OSError:
                pass


def cleanup_old_files():
    days = SiteSettings.get().retention_days
    if not days:
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    old = Job.objects.filter(files_deleted=False, created_at__lt=cutoff).filter(
        ~Q(status__in=Job.ACTIVE_STATUSES)
    )
    n = 0
    for job in old:
        delete_job_files(job)
        n += 1
    if n:
        logger.info("Deleted files of %d old jobs", n)
    return n
