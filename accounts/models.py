import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

REFERRAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_referral_code():
    return "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(8))


class User(AbstractUser):
    email = models.EmailField(_("email address"), unique=True)
    coins = models.PositiveIntegerField(_("coins"), default=0)
    referral_code = models.CharField(_("referral code"), max_length=12, unique=True, editable=False)
    referred_by = models.ForeignKey(
        "self",
        verbose_name=_("referred by"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referrals",
    )

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def save(self, *args, **kwargs):
        if not self.referral_code:
            code = generate_referral_code()
            while User.objects.filter(referral_code=code).exists():
                code = generate_referral_code()
            self.referral_code = code
        super().save(*args, **kwargs)


class CoinTransaction(models.Model):
    class Kind(models.TextChoices):
        SIGNUP_BONUS = "signup_bonus", _("Sign-up bonus")
        REFERRAL_BONUS = "referral_bonus", _("Referral bonus")
        ADMIN_GRANT = "admin_grant", _("Added by admin")
        ADMIN_DEDUCT = "admin_deduct", _("Removed by admin")
        JOB_CHARGE = "job_charge", _("Enhancement")
        JOB_REFUND = "job_refund", _("Refund")
        APP_CHARGE = "app_charge", _("Enhancement (desktop app)")
        APP_REFUND = "app_refund", _("Refund (desktop app)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("user"), on_delete=models.CASCADE, related_name="transactions"
    )
    amount = models.IntegerField(_("amount"))
    balance_after = models.PositiveIntegerField(_("balance after"))
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    note = models.CharField(_("note"), max_length=255, blank=True)
    job = models.ForeignKey(
        "enhancer.Job", verbose_name=_("job"), null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("by"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(_("date"), auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("coin transaction")
        verbose_name_plural = _("coin transactions")

    def __str__(self):
        return f"{self.user} {self.amount:+d}"
