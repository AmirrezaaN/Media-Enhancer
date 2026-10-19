from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from enhancer.models import SiteSettings

from . import wallet
from .models import CoinTransaction, User


class WalletTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", "ali@example.test", "a-strong-pass-123")

    def test_credit_and_debit_are_logged(self):
        wallet.credit(self.user, 10, CoinTransaction.Kind.ADMIN_GRANT)
        wallet.debit(self.user, 4, CoinTransaction.Kind.JOB_CHARGE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 6)
        self.assertEqual(list(self.user.transactions.values_list("amount", flat=True)), [-4, 10])
        self.assertEqual(self.user.transactions.first().balance_after, 6)

    def test_debit_never_goes_negative(self):
        wallet.credit(self.user, 3, CoinTransaction.Kind.ADMIN_GRANT)
        with self.assertRaises(wallet.InsufficientCoins):
            wallet.debit(self.user, 5, CoinTransaction.Kind.JOB_CHARGE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 3)

    def test_partial_debit_stops_at_zero(self):
        wallet.credit(self.user, 3, CoinTransaction.Kind.ADMIN_GRANT)
        wallet.debit(self.user, 50, CoinTransaction.Kind.ADMIN_DEDUCT, allow_partial=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 0)


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_signup_bonus_and_referral(self):
        site = SiteSettings.get()
        inviter = User.objects.create_user("inviter", "inv@example.test", "a-strong-pass-123")
        response = self.client.post(reverse("accounts:register"), {
            "username": "newuser", "email": "New@Example.test",
            "password1": "x-Very-strong-9", "password2": "x-Very-strong-9",
            "referral_code": inviter.referral_code.lower(),
        })
        self.assertEqual(response.status_code, 302)
        new = User.objects.get(username="newuser")
        inviter.refresh_from_db()
        self.assertEqual(new.email, "new@example.test")
        self.assertEqual(new.referred_by, inviter)
        self.assertEqual(new.coins, site.signup_bonus + site.referral_bonus_new_user)
        self.assertEqual(inviter.coins, site.referral_bonus_referrer)

    def test_duplicate_email_rejected(self):
        User.objects.create_user("a", "same@example.test", "a-strong-pass-123")
        response = self.client.post(reverse("accounts:register"), {
            "username": "b", "email": "SAME@example.test",
            "password1": "x-Very-strong-9", "password2": "x-Very-strong-9",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="b").exists())

    def test_login_with_email_and_lockout(self):
        User.objects.create_user("sara", "sara@example.test", "a-strong-pass-123")
        ok = self.client.post(reverse("accounts:login"), {"username": "sara@example.test", "password": "a-strong-pass-123"})
        self.assertEqual(ok.status_code, 302)
        self.client.logout()
        for _ in range(8):
            self.client.post(reverse("accounts:login"), {"username": "sara", "password": "wrong"})
        locked = self.client.post(reverse("accounts:login"), {"username": "sara", "password": "a-strong-pass-123"})
        self.assertEqual(locked.status_code, 200)  # still blocked even with the right password
