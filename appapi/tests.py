import json

from django.core.cache import cache
from django.test import TestCase

from accounts import wallet
from accounts.models import CoinTransaction, User
from enhancer.models import SiteSettings

from .models import AppJob, AppToken


class AppApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("reza", "reza@example.test", "a-strong-pass-123")
        wallet.credit(self.user, 100, CoinTransaction.Kind.ADMIN_GRANT)

    def post(self, url, data=None, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"} if token else {}
        return self.client.post(url, json.dumps(data or {}), content_type="application/json", **headers)

    def login(self):
        r = self.post("/api/app/login/", {"username": "reza", "password": "a-strong-pass-123", "device": "PC"})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["token"]

    def test_login_returns_token_and_only_hash_is_stored(self):
        token = self.login()
        stored = AppToken.objects.get()
        self.assertNotEqual(stored.key_hash, token)
        self.assertEqual(len(stored.key_hash), 64)

    def test_login_with_email(self):
        r = self.post("/api/app/login/", {"username": "REZA@example.test", "password": "a-strong-pass-123"})
        self.assertEqual(r.status_code, 200)

    def test_wrong_password_and_throttling(self):
        for _ in range(8):
            r = self.post("/api/app/login/", {"username": "reza", "password": "nope"})
            self.assertEqual(r.status_code, 401)
        r = self.post("/api/app/login/", {"username": "reza", "password": "a-strong-pass-123"})
        self.assertEqual(r.status_code, 429)

    def test_me_requires_valid_token(self):
        self.assertEqual(self.client.get("/api/app/me/").status_code, 401)
        self.assertEqual(self.client.get("/api/app/me/", HTTP_AUTHORIZATION="Token wrong").status_code, 401)
        token = self.login()
        r = self.client.get("/api/app/me/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.json()["account"]["coins"], 100)

    def test_job_charges_app_price_and_refunds_on_failure(self):
        site = SiteSettings.get()
        token = self.login()
        r = self.post("/api/app/jobs/", {"media_type": "video", "quality": "high", "scale": 4, "duration": 25}, token)
        self.assertEqual(r.status_code, 200, r.content)
        expected = site.app_price("video", "high", 4, False, False, 25)
        self.assertEqual(expected, -(-site.price("video", "high", 4, False, False, 25) * 50 // 100))
        self.assertEqual(r.json()["cost"], expected)
        self.assertEqual(r.json()["coins"], 100 - expected)

        job_id = r.json()["job_id"]
        r = self.post(f"/api/app/jobs/{job_id}/finish/", {"status": "failed", "error": "boom"}, token)
        self.assertEqual(r.json()["coins"], 100)
        # A second report cannot refund again or turn it into "done".
        r = self.post(f"/api/app/jobs/{job_id}/finish/", {"status": "cancelled"}, token)
        self.assertEqual(r.json()["coins"], 100)
        self.assertEqual(AppJob.objects.get().status, "failed")

    def test_done_job_keeps_charge(self):
        token = self.login()
        job_id = self.post("/api/app/jobs/", {"media_type": "image", "quality": "fast", "scale": 2}, token).json()["job_id"]
        r = self.post(f"/api/app/jobs/{job_id}/finish/", {"status": "done", "seconds": 3}, token)
        self.assertLess(r.json()["coins"], 100)

    def test_not_enough_coins(self):
        wallet.debit(self.user, 100, CoinTransaction.Kind.ADMIN_DEDUCT)
        token = self.login()
        r = self.post("/api/app/jobs/", {"media_type": "image", "quality": "high", "scale": 4}, token)
        self.assertEqual(r.status_code, 402)
        self.assertFalse(AppJob.objects.exists())

    def test_invalid_job_rejected(self):
        token = self.login()
        for bad in ({"media_type": "exe", "quality": "fast", "scale": 2},
                    {"media_type": "image", "quality": "ultra", "scale": 2},
                    {"media_type": "video", "quality": "fast", "scale": 2, "duration": 0}):
            self.assertEqual(self.post("/api/app/jobs/", bad, token).status_code, 400)

    def test_other_users_job_is_not_found(self):
        token = self.login()
        job_id = self.post("/api/app/jobs/", {"media_type": "image", "quality": "fast", "scale": 2}, token).json()["job_id"]
        User.objects.create_user("other", "o@example.test", "a-strong-pass-123")
        r = self.post("/api/app/login/", {"username": "other", "password": "a-strong-pass-123"})
        other_token = r.json()["token"]
        r = self.post(f"/api/app/jobs/{job_id}/finish/", {"status": "failed"}, other_token)
        self.assertEqual(r.status_code, 404)

    def test_logout_revokes_token(self):
        token = self.login()
        self.post("/api/app/logout/", token=token)
        self.assertEqual(self.client.get("/api/app/me/", HTTP_AUTHORIZATION=f"Token {token}").status_code, 401)

    def test_app_disabled(self):
        token = self.login()
        site = SiteSettings.get()
        site.app_enabled = False
        site.save()
        self.assertEqual(self.client.get("/api/app/me/", HTTP_AUTHORIZATION=f"Token {token}").status_code, 403)
        r = self.post("/api/app/login/", {"username": "reza", "password": "a-strong-pass-123"})
        self.assertEqual(r.status_code, 403)

    def test_free_when_percent_is_zero(self):
        site = SiteSettings.get()
        site.app_price_percent = 0
        site.save()
        token = self.login()
        r = self.post("/api/app/jobs/", {"media_type": "image", "quality": "high", "scale": 4, "face": True}, token)
        self.assertEqual((r.json()["cost"], r.json()["coins"]), (0, 100))
