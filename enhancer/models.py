import math
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

SETTINGS_CACHE_KEY = "site-settings"


class SiteSettings(models.Model):
    """Single-row table with everything the admin can tune: prices, bonuses and limits."""

    # General
    registration_open = models.BooleanField(_("registration open"), default=True)
    maintenance_mode = models.BooleanField(
        _("pause new jobs"), default=False, help_text=_("Users cannot submit new jobs while this is on.")
    )
    announcement_fa = models.TextField(_("announcement (Persian)"), blank=True)
    announcement_en = models.TextField(_("announcement (English)"), blank=True)

    # Bonuses
    signup_bonus = models.PositiveIntegerField(_("sign-up bonus coins"), default=20)
    referral_bonus_referrer = models.PositiveIntegerField(_("referral bonus for the inviter"), default=10)
    referral_bonus_new_user = models.PositiveIntegerField(_("referral bonus for the new user"), default=5)

    # Image prices (coins per image)
    image_fast_cost = models.PositiveIntegerField(_("image - fast mode"), default=2)
    image_high_cost = models.PositiveIntegerField(_("image - high quality mode"), default=5)
    image_4x_extra = models.PositiveIntegerField(_("image - extra for 4x"), default=1)
    image_face_cost = models.PositiveIntegerField(_("image - face restoration extra"), default=2)

    # Video prices (coins per started 10 seconds)
    video_fast_cost = models.PositiveIntegerField(_("video - fast mode (per 10 s)"), default=5)
    video_high_cost = models.PositiveIntegerField(_("video - high quality mode (per 10 s)"), default=15)
    video_4x_extra = models.PositiveIntegerField(_("video - extra for 4x (per 10 s)"), default=3)
    video_face_cost = models.PositiveIntegerField(_("video - face restoration extra (per 10 s)"), default=5)
    video_fps_cost = models.PositiveIntegerField(_("video - smooth motion extra (per 10 s)"), default=5)

    # Limits
    max_image_mb = models.PositiveIntegerField(_("max image size (MB)"), default=25)
    max_image_megapixels = models.PositiveIntegerField(_("max image resolution (megapixels)"), default=24)
    max_video_mb = models.PositiveIntegerField(_("max video size (MB)"), default=300)
    max_video_seconds = models.PositiveIntegerField(_("max video length (seconds)"), default=180)
    max_image_output_side = models.PositiveIntegerField(
        _("max output side for images (px)"), default=8192, validators=[MinValueValidator(512)]
    )
    max_video_output_side = models.PositiveIntegerField(
        _("max output side for videos (px)"),
        default=3840,
        validators=[MinValueValidator(480), MaxValueValidator(7680)],
    )
    max_active_jobs = models.PositiveIntegerField(
        _("max queued jobs per user"), default=3, validators=[MinValueValidator(1)]
    )
    retention_days = models.PositiveIntegerField(
        _("delete files after (days)"), default=7, help_text=_("0 keeps files forever.")
    )

    # Quality
    video_denoise = models.PositiveSmallIntegerField(
        _("video noise reduction"),
        default=1,
        choices=[(0, _("Off")), (1, _("Light")), (2, _("Medium")), (3, _("Strong"))],
        help_text=_("Cleans compression noise and stops flicker between frames. Light is right for most videos."),
    )

    # Desktop app
    app_enabled = models.BooleanField(_("desktop app can log in"), default=True)
    app_price_percent = models.PositiveIntegerField(
        _("desktop app price (% of site price)"),
        default=50,
        validators=[MaxValueValidator(1000)],
        help_text=_("The desktop app uses the customer's own GPU, so it can be cheaper. 0 makes it free."),
    )
    app_download_url = models.URLField(
        _("desktop app download link"),
        blank=True,
        help_text=_("Where users can download the Windows installer. Leave empty to hide the download button."),
    )

    class Meta:
        verbose_name = _("site settings")
        verbose_name_plural = _("site settings")

    def __str__(self):
        return str(_("Site settings"))

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SETTINGS_CACHE_KEY)

    @classmethod
    def get(cls):
        obj = cache.get(SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _created = cls.objects.get_or_create(pk=1)
            cache.set(SETTINGS_CACHE_KEY, obj, 30)
        return obj

    @property
    def announcement(self):
        return self.announcement_en if (get_language() or "").startswith("en") else self.announcement_fa

    def price(self, media_type, quality, scale, face, fps_boost, duration=0.0):
        """Coin cost of one job. Video is priced per started 10 seconds."""
        high = quality == Job.Quality.HIGH
        if media_type == Job.MediaType.IMAGE:
            cost = self.image_high_cost if high else self.image_fast_cost
            if scale == 4:
                cost += self.image_4x_extra
            if face:
                cost += self.image_face_cost
            return cost
        units = max(1, math.ceil(max(duration, 0.0) / 10.0))
        per_unit = self.video_high_cost if high else self.video_fast_cost
        if scale == 4:
            per_unit += self.video_4x_extra
        if face:
            per_unit += self.video_face_cost
        if fps_boost:
            per_unit += self.video_fps_cost
        return per_unit * units

    def app_price(self, media_type, quality, scale, face, fps_boost, duration=0.0):
        """Price of the same job in the desktop app, rounded up to whole coins."""
        base = self.price(media_type, quality, scale, face, fps_boost, duration)
        return math.ceil(base * self.app_price_percent / 100)

    def price_table(self):
        """Prices exposed to the browser for the live cost preview."""
        return {
            "image": {
                "fast": self.image_fast_cost, "high": self.image_high_cost,
                "x4": self.image_4x_extra, "face": self.image_face_cost,
            },
            "video": {
                "fast": self.video_fast_cost, "high": self.video_high_cost,
                "x4": self.video_4x_extra, "face": self.video_face_cost, "fps": self.video_fps_cost,
            },
        }


class WorkerStatus(models.Model):
    """Heartbeat written by the processing worker so the site knows whether it is running."""

    last_seen = models.DateTimeField(_("last seen"), null=True)
    device = models.CharField(_("device"), max_length=120, blank=True)
    current_job = models.UUIDField(_("current job"), null=True, blank=True)

    class Meta:
        verbose_name = _("worker status")
        verbose_name_plural = _("worker status")

    @classmethod
    def beat(cls, device="", current_job=None):
        from django.utils import timezone

        cls.objects.update_or_create(
            pk=1, defaults={"last_seen": timezone.now(), "device": device, "current_job": current_job}
        )

    @classmethod
    def is_online(cls):
        from datetime import timedelta

        from django.utils import timezone

        row = cls.objects.filter(pk=1).first()
        return bool(row and row.last_seen and timezone.now() - row.last_seen < timedelta(seconds=90))


def upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"uploads/{instance.user_id}/{instance.id}.{ext}"


class Job(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", _("Image")
        VIDEO = "video", _("Video")

    class Quality(models.TextChoices):
        FAST = "fast", _("Fast")
        HIGH = "high", _("High quality")

    class Status(models.TextChoices):
        QUEUED = "queued", _("In queue")
        PROCESSING = "processing", _("Processing")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    ACTIVE_STATUSES = (Status.QUEUED, Status.PROCESSING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("user"), on_delete=models.CASCADE, related_name="jobs"
    )
    media_type = models.CharField(_("type"), max_length=10, choices=MediaType.choices)
    quality = models.CharField(_("mode"), max_length=10, choices=Quality.choices, default=Quality.HIGH)
    scale = models.PositiveSmallIntegerField(_("scale"), default=4, choices=[(2, "2x"), (4, "4x")])
    face_enhance = models.BooleanField(_("face restoration"), default=False)
    fps_boost = models.BooleanField(_("smooth motion (2x FPS)"), default=False)

    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.QUEUED)
    progress = models.FloatField(_("progress"), default=0)
    stage = models.CharField(_("stage"), max_length=64, blank=True)
    cost = models.PositiveIntegerField(_("cost (coins)"), default=0)
    refunded = models.BooleanField(_("refunded"), default=False)
    error_message = models.TextField(_("error"), blank=True)

    original_name = models.CharField(_("file name"), max_length=255)
    input_file = models.FileField(_("input"), upload_to=upload_path, max_length=255)
    output_file = models.FileField(_("output"), max_length=255, blank=True)
    input_preview = models.FileField(max_length=255, blank=True)
    output_preview = models.FileField(max_length=255, blank=True)
    files_deleted = models.BooleanField(_("files deleted"), default=False)

    input_width = models.PositiveIntegerField(_("input width"), default=0)
    input_height = models.PositiveIntegerField(_("input height"), default=0)
    output_width = models.PositiveIntegerField(_("output width"), default=0)
    output_height = models.PositiveIntegerField(_("output height"), default=0)
    duration = models.FloatField(_("duration (s)"), default=0)
    fps = models.FloatField(_("frame rate (FPS)"), default=0)

    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    started_at = models.DateTimeField(_("started"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("job")
        verbose_name_plural = _("jobs")
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.original_name} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_image(self):
        return self.media_type == self.MediaType.IMAGE

    @property
    def processing_seconds(self):
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None

    def output_filename(self):
        stem = self.original_name.rsplit(".", 1)[0][:80] or "media"
        ext = self.output_file.name.rsplit(".", 1)[-1] if self.output_file else "png"
        return f"{stem}_enhanced_{self.scale}x.{ext}"
