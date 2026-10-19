from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EnhancerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "enhancer"
    verbose_name = _("Enhancement")
