from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

admin.site.site_header = _("Media Enhancer")
admin.site.site_title = _("Media Enhancer")
admin.site.index_title = _("Admin panel")

urlpatterns = [
    path("manage/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("accounts.urls")),
    path("", include("enhancer.urls")),
]
