from .models import SiteSettings


def site(request):
    return {"site_settings": SiteSettings.get()}
