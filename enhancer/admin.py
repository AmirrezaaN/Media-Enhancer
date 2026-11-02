from django.contrib import admin, messages
from django.db import models, transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts import wallet
from accounts.models import CoinTransaction

from .models import Job, SiteSettings, WorkerStatus
from .views import delete_job_files, refund_job

admin.site.index_template = "admin/dashboard_index.html"


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (_("General"), {"fields": ("registration_open", "maintenance_mode", "announcement_fa", "announcement_en")}),
        (_("Bonuses"), {"fields": ("signup_bonus", "referral_bonus_referrer", "referral_bonus_new_user")}),
        (
            _("Image prices (coins per image)"),
            {"fields": ("image_fast_cost", "image_high_cost", "image_4x_extra", "image_face_cost")},
        ),
        (
            _("Video prices (coins per started 10 seconds)"),
            {"fields": ("video_fast_cost", "video_high_cost", "video_4x_extra", "video_face_cost", "video_fps_cost")},
        ),
        (_("Quality"), {"fields": ("video_denoise",)}),
        (_("Desktop app"), {"fields": ("app_enabled", "app_price_percent", "app_download_url")}),
        (
            _("Limits"),
            {
                "fields": (
                    "max_image_mb", "max_image_megapixels", "max_image_output_side",
                    "max_video_mb", "max_video_seconds", "max_video_output_side",
                    "max_active_jobs", "retention_days",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get()
        return redirect(reverse("admin:enhancer_sitesettings_change", args=[obj.pk]))


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "original_name", "user", "media_type", "quality", "scale", "face_enhance", "fps_boost",
        "status_badge", "progress_display", "cost", "created_at",
    )
    list_filter = ("status", "media_type", "quality", "face_enhance", "fps_boost", "created_at")
    search_fields = ("original_name", "user__username", "user__email", "id")
    list_select_related = ("user",)
    date_hierarchy = "created_at"
    actions = ["cancel_and_refund", "requeue", "delete_files"]
    # File fields are private (no public URL), so they are shown through download links instead.
    readonly_fields = [
        f.name for f in Job._meta.fields if not isinstance(f, models.FileField)
    ] + ["input_link", "result_link"]
    exclude = ("input_file", "output_file", "input_preview", "output_preview")

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("status"), ordering="status")
    def status_badge(self, obj):
        colors = {"queued": "#888", "processing": "#2b7de9", "done": "#1a9b53", "failed": "#d93f3f", "cancelled": "#aaa"}
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.status, "#000"), obj.get_status_display()
        )

    @admin.display(description=_("progress"))
    def progress_display(self, obj):
        return f"{obj.progress:.0f}%"

    @admin.display(description=_("input"))
    def input_link(self, obj):
        if obj.input_file and not obj.files_deleted:
            url = reverse("enhancer:job_file", args=[obj.pk, "input"]) + "?download=1"
            return format_html('<a href="{}">{}</a>', url, obj.original_name)
        return "-"

    @admin.display(description=_("result"))
    def result_link(self, obj):
        if obj.output_file and not obj.files_deleted:
            url = reverse("enhancer:job_file", args=[obj.pk, "output"]) + "?download=1"
            return format_html('<a href="{}">{}</a>', url, _("Download"))
        return "-"

    @admin.action(description=_("Cancel and refund selected jobs"))
    def cancel_and_refund(self, request, queryset):
        n = 0
        for job in queryset.select_related("user"):
            if job.status in (Job.Status.DONE,) or job.refunded:
                continue
            Job.objects.filter(pk=job.pk).exclude(status=Job.Status.DONE).update(
                status=Job.Status.CANCELLED, finished_at=timezone.now()
            )
            refund_job(job, _("Cancelled by admin"))
            n += 1
        self.message_user(request, _("%(n)d jobs cancelled and refunded.") % {"n": n}, messages.SUCCESS)

    @admin.action(description=_("Retry selected failed jobs (the user is charged again)"))
    def requeue(self, request, queryset):
        n = skipped = 0
        for job in queryset.filter(status=Job.Status.FAILED, files_deleted=False).select_related("user"):
            try:
                with transaction.atomic():
                    if job.refunded and job.cost > 0:
                        wallet.debit(job.user, job.cost, CoinTransaction.Kind.JOB_CHARGE, note=job.original_name, job=job)
                    Job.objects.filter(pk=job.pk).update(
                        status=Job.Status.QUEUED, progress=0, stage="", error_message="",
                        started_at=None, finished_at=None, refunded=False,
                    )
                n += 1
            except wallet.InsufficientCoins:
                skipped += 1
        self.message_user(
            request, _("%(n)d jobs requeued, %(s)d skipped (not enough coins).") % {"n": n, "s": skipped},
            messages.SUCCESS,
        )

    @admin.action(description=_("Delete files of selected jobs"))
    def delete_files(self, request, queryset):
        n = 0
        for job in queryset.exclude(status__in=Job.ACTIVE_STATUSES):
            delete_job_files(job)
            n += 1
        self.message_user(request, _("Files of %(n)d jobs deleted.") % {"n": n}, messages.SUCCESS)


@admin.register(WorkerStatus)
class WorkerStatusAdmin(admin.ModelAdmin):
    list_display = ("device", "last_seen", "current_job", "online")

    @admin.display(description=_("online"), boolean=True)
    def online(self, obj):
        return WorkerStatus.is_online()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
