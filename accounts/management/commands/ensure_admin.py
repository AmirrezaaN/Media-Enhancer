import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create or update the admin account from ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD in .env"

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME", "").strip()
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not username or not email or not password:
            raise CommandError("Set ADMIN_USERNAME, ADMIN_EMAIL and ADMIN_PASSWORD in the .env file first.")
        if len(password) < 10:
            raise CommandError("ADMIN_PASSWORD must be at least 10 characters.")

        user = User.objects.filter(username=username).first()
        created = user is None
        if created:
            user = User(username=username)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin '{username}' {'created' if created else 'updated'}."))
        self.stdout.write("You can now remove ADMIN_PASSWORD from .env.")
