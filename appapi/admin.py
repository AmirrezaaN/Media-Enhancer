from django.contrib import admin, messages
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from accounts import wallet
from accounts.models import CoinTransaction

from .models import AppJob, AppToken


@admin.register(AppJob)
class AppJobAdmin(admin.ModelAdmin):
    list_display = ("original_name", "user", "media_type", "quality", "scale", "face_enhance", "fps_boost",
                    "status", "cost", "refunded", "gpu", "created_at")
    list_filter = ("status", "media_type", "quality", "refunded", "created_at")
    search_fields = ("original_name", "user__username", "user__email", "gpu")
    list_select_related = ("user",)
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AppJob._meta.fields]
    actions = ["refund"]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Refund selected jobs"))
    def refund(self, request, queryset):
        n = 0
        for job in queryset.select_related("user"):
            with transaction.atomic():
                if job.cost and AppJob.objects.filter(pk=job.pk, refunded=False).update(refunded=True):
                    wallet.credit(job.user, job.cost, CoinTransaction.Kind.APP_REFUND,
                                  note=job.original_name, by=request.user)
                    n += 1
        self.message_user(request, _("%(n)d jobs refunded.") % {"n": n}, messages.SUCCESS)


@admin.register(AppToken)
class AppTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "device", "created_at", "last_used_at")
    search_fields = ("user__username", "device")
    list_select_related = ("user",)
    readonly_fields = ("user", "device", "created_at", "last_used_at")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False
