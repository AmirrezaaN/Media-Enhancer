import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

TOKEN_LIFETIME = timedelta(days=90)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AppToken(models.Model):
    """Login session of the desktop app. Only a hash of the key is stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("user"), on_delete=models.CASCADE, related_name="app_tokens"
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    device = models.CharField(_("device"), max_length=150, blank=True)
    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("last used"), default=timezone.now)

    class Meta:
        verbose_name = _("app login")
        verbose_name_plural = _("app logins")
        ordering = ["-last_used_at"]

    def __str__(self):
        return f"{self.user} ({self.device or '-'})"

    @classmethod
    def issue(cls, user, device=""):
        key = secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, key_hash=hash_key(key), device=device[:150])
        return token, key

    @property
    def expired(self):
        return timezone.now() - self.last_used_at > TOKEN_LIFETIME


class AppJob(models.Model):
    """A job that ran on the customer's own computer. Only the record and the charge live here."""

    class Status(models.TextChoices):
        STARTED = "started", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("user"), on_delete=models.CASCADE, related_name="app_jobs"
    )
    token = models.ForeignKey(AppToken, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    media_type = models.CharField(_("type"), max_length=10)
    quality = models.CharField(_("mode"), max_length=10)
    scale = models.PositiveSmallIntegerField(_("scale"))
    face_enhance = models.BooleanField(_("face restoration"), default=False)
    fps_boost = models.BooleanField(_("smooth motion (2x FPS)"), default=False)
    original_name = models.CharField(_("file name"), max_length=255, blank=True)
    input_width = models.PositiveIntegerField(_("input width"), default=0)
    input_height = models.PositiveIntegerField(_("input height"), default=0)
    duration = models.FloatField(_("duration (s)"), default=0)
    cost = models.PositiveIntegerField(_("cost (coins)"), default=0)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.STARTED)
    refunded = models.BooleanField(_("refunded"), default=False)
    gpu = models.CharField(_("GPU"), max_length=150, blank=True)
    app_version = models.CharField(_("app version"), max_length=20, blank=True)
    processing_seconds = models.PositiveIntegerField(_("processing time (s)"), null=True, blank=True)
    error_message = models.TextField(_("error"), blank=True)
    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    finished_at = models.DateTimeField(_("finished"), null=True, blank=True)

    class Meta:
        verbose_name = _("desktop app job")
        verbose_name_plural = _("desktop app jobs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_name} ({self.get_status_display()})"
