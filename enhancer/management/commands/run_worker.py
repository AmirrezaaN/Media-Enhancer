import logging
import time

from django.core.management.base import BaseCommand

from enhancer.models import WorkerStatus
from enhancer.worker import claim_next_job, cleanup_old_files, requeue_interrupted_jobs, run_job

logger = logging.getLogger("enhancer")


class Command(BaseCommand):
    help = "Run the GPU worker that processes enhancement jobs. Keep it running next to the web server."

    def add_arguments(self, parser):
        parser.add_argument("--poll", type=float, default=2.0, help="Seconds between queue checks when idle.")
        parser.add_argument("--once", action="store_true", help="Process the current queue and exit.")

    def handle(self, *args, poll, once, **options):
        from enhancer.ai import create_engine

        engine = create_engine()
        self.stdout.write(self.style.SUCCESS(f"Worker started on {engine.device_name}. Press Ctrl+C to stop."))
        requeue_interrupted_jobs()
        cleanup_old_files()
        last_cleanup = last_beat = time.monotonic()
        WorkerStatus.beat(engine.device_name)
        try:
            while True:
                job = claim_next_job()
                if job is not None:
                    run_job(job, engine)
                    WorkerStatus.beat(engine.device_name)
                    continue
                if once:
                    break
                now = time.monotonic()
                if now - last_beat > 20:
                    WorkerStatus.beat(engine.device_name)
                    last_beat = now
                if now - last_cleanup > 3600:
                    cleanup_old_files()
                    last_cleanup = now
                time.sleep(poll)
        except KeyboardInterrupt:
            self.stdout.write("Stopping worker...")
            requeue_interrupted_jobs()
