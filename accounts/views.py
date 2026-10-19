import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from enhancer.models import SiteSettings

from . import wallet
from .forms import LoginForm, RegisterForm
from .models import CoinTransaction

logger = logging.getLogger(__name__)

LOGIN_MAX_FAILURES = 8
LOGIN_WINDOW = 15 * 60
REGISTER_MAX_PER_IP = 5
REGISTER_WINDOW = 60 * 60


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    redirect_authenticated_user = True

    def _key(self):
        return f"login-fail:{client_ip(self.request)}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= LOGIN_MAX_FAILURES:
            messages.error(request, _("Too many failed attempts. Please try again in 15 minutes."))
            return self.render_to_response(self.get_context_data(form=self.form_class(request)))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.add(key, 0, LOGIN_WINDOW)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_WINDOW)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("enhancer:dashboard")
    site = SiteSettings.get()
    if not site.registration_open:
        return render(request, "accounts/register_closed.html")

    initial = {"referral_code": request.GET.get("ref", "")[:12]}
    form = RegisterForm(request.POST or None, initial=initial)
    if request.method == "POST":
        ip_key = f"register:{client_ip(request)}"
        if cache.get(ip_key, 0) >= REGISTER_MAX_PER_IP:
            messages.error(request, _("Too many accounts were created from your network. Please try again later."))
        elif form.is_valid():
            referrer = form.cleaned_data.get("referral_code")
            with transaction.atomic():
                user = form.save(commit=False)
                user.referred_by = referrer
                user.save()
                if site.signup_bonus > 0:
                    wallet.credit(user, site.signup_bonus, CoinTransaction.Kind.SIGNUP_BONUS)
                if referrer:
                    if site.referral_bonus_new_user > 0:
                        wallet.credit(
                            user, site.referral_bonus_new_user, CoinTransaction.Kind.REFERRAL_BONUS,
                            note=f"invited by {referrer.username}",
                        )
                    if site.referral_bonus_referrer > 0:
                        wallet.credit(
                            referrer, site.referral_bonus_referrer, CoinTransaction.Kind.REFERRAL_BONUS,
                            note=f"invited {user.username}",
                        )
            cache.add(ip_key, 0, REGISTER_WINDOW)
            cache.incr(ip_key)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            logger.info("New user registered: %s", user.username)
            messages.success(request, _("Welcome! Your account was created."))
            return redirect("enhancer:dashboard")
    return render(request, "accounts/register.html", {"form": form, "site": site})


@login_required
def wallet_view(request):
    page = Paginator(request.user.transactions.select_related("job"), 20).get_page(request.GET.get("page"))
    referral_link = request.build_absolute_uri(reverse("accounts:register")) + f"?ref={request.user.referral_code}"
    return render(
        request,
        "accounts/wallet.html",
        {
            "page": page,
            "referral_link": referral_link,
            "referral_count": request.user.referrals.count(),
            "site": SiteSettings.get(),
        },
    )


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:wallet")

    def form_valid(self, form):
        messages.success(self.request, _("Your password was changed."))
        return super().form_valid(form)
