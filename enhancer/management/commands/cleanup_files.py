from django.core.management.base import BaseCommand

from enhancer.worker import cleanup_old_files


class Command(BaseCommand):
    help = "Delete uploaded and generated files older than the retention period set in Site settings."

    def handle(self, *args, **options):
        n = cleanup_old_files()
        self.stdout.write(self.style.SUCCESS(f"Deleted files of {n} jobs."))
