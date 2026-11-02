CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)


class DefaultLanguageMiddleware:
    """Show the site in the default language (LANGUAGE_CODE, English) until the visitor picks another
    one with the language button, instead of guessing from the browser's language.
    The desktop-app API keeps the Accept-Language header so the app gets messages in its own language.
    Must run before LocaleMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            request.META.pop("HTTP_ACCEPT_LANGUAGE", None)
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """Strict CSP for the public site. The Django admin keeps its own defaults."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/manage/"):
            response.setdefault("Content-Security-Policy", CSP)
        return response
