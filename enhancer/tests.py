import io
import shutil
import tempfile
from types import SimpleNamespace

import torch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts import wallet
from accounts.models import CoinTransaction, User

from mecore.core import Engine, Upscaler
from mecore.media import MediaInfo
from mecore.pipeline import make_plan, source_color_matrix

from .models import Job, SiteSettings
from .views import refund_job

TEMP_MEDIA = tempfile.mkdtemp()


def png_upload(name="photo.png", size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 30, 200)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class PricingTests(TestCase):
    def test_image_price(self):
        s = SiteSettings.get()
        self.assertEqual(s.price("image", "fast", 2, False, False), s.image_fast_cost)
        self.assertEqual(
            s.price("image", "high", 4, True, False),
            s.image_high_cost + s.image_4x_extra + s.image_face_cost,
        )

    def test_video_price_per_started_10_seconds(self):
        s = SiteSettings.get()
        self.assertEqual(s.price("video", "fast", 2, False, False, duration=4), s.video_fast_cost)
        self.assertEqual(s.price("video", "fast", 2, False, False, duration=10.0), s.video_fast_cost)
        self.assertEqual(s.price("video", "fast", 2, False, True, duration=10.5), 2 * (s.video_fast_cost + s.video_fps_cost))


class PlanTests(TestCase):
    def test_output_is_capped(self):
        plan = make_plan(1920, 1080, 4, "high", 3840, even=True)
        self.assertEqual((plan.out_w, plan.out_h), (3840, 2160))
        self.assertEqual(plan.model, "RealESRGAN_x2plus")

    def test_small_input_uses_4x_model(self):
        plan = make_plan(640, 360, 4, "high", 3840)
        self.assertEqual((plan.out_w, plan.out_h, plan.model), (2560, 1440, "RealESRGAN_x4plus"))

    def test_fast_mode_model(self):
        self.assertEqual(make_plan(640, 360, 2, "fast", 3840).model, "realesr-general-x4v3")


class EngineLogicTests(TestCase):
    """Engine rules that do not need a GPU."""

    def _guard(self, x, y, scale=2):
        fake = SimpleNamespace(scale=scale, GUARD_THRESHOLD=Upscaler.GUARD_THRESHOLD,
                               GUARD_MIN_PIXELS=Upscaler.GUARD_MIN_PIXELS)
        return Upscaler._corrupt(fake, x, y)

    def test_guard_accepts_a_faithful_upscale(self):
        x = torch.rand(1, 3, 64, 64)
        y = torch.nn.functional.interpolate(x, scale_factor=2, mode="nearest")
        self.assertFalse(self._guard(x, y))

    def test_guard_catches_garbage_block_and_nan(self):
        x = torch.full((1, 3, 64, 64), 0.6)
        y = torch.nn.functional.interpolate(x, scale_factor=2, mode="nearest")
        y[:, :, 40:46, 40:46] = 0.0  # a small black dot
        self.assertTrue(self._guard(x, y))
        y2 = torch.nn.functional.interpolate(x, scale_factor=2, mode="nearest")
        y2[0, 0, 5, 5] = float("nan")
        self.assertTrue(self._guard(x, y2))

    def test_precision_policy(self):
        def engine(precision):
            return SimpleNamespace(cuda=True, config=SimpleNamespace(precision=precision))

        self.assertTrue(Engine.uses_half(engine("auto"), "RealESRGAN_x4plus"))
        self.assertTrue(Engine.uses_half(engine("fp16"), "realesr-general-x4v3"))
        self.assertFalse(Engine.uses_half(engine("fp32"), "RealESRGAN_x4plus"))
        self.assertFalse(Engine.uses_half(SimpleNamespace(cuda=False, config=SimpleNamespace(precision="auto")), "x"))

    def test_color_matrix(self):
        self.assertEqual(source_color_matrix(MediaInfo(1920, 1080, color_space="bt709")), "bt709")
        self.assertEqual(source_color_matrix(MediaInfo(640, 480, color_space="smpte170m")), "bt601")
        # Untagged files follow the player convention: HD = BT.709, SD = BT.601.
        self.assertEqual(source_color_matrix(MediaInfo(1280, 720)), "bt709")
        self.assertEqual(source_color_matrix(MediaInfo(480, 834)), "bt601")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class JobViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()  # cached SiteSettings would otherwise survive the per-test rollback
        self.user = User.objects.create_user("u1", "u1@example.test", "a-strong-pass-123")
        wallet.credit(self.user, 100, CoinTransaction.Kind.ADMIN_GRANT)
        self.client.force_login(self.user)

    def post_job(self, upload, **opts):
        data = {"file": upload, "quality": "fast", "scale": "2", **opts}
        return self.client.post(reverse("enhancer:create_job"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_create_image_job_charges_coins(self):
        response = self.post_job(png_upload())
        self.assertEqual(response.status_code, 200, response.content)
        job = Job.objects.get()
        self.assertEqual((job.input_width, job.input_height, job.status), (64, 48, "queued"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 100 - job.cost)

    def test_fake_image_rejected_and_not_charged(self):
        response = self.post_job(SimpleUploadedFile("x.jpg", b"<?php system($_GET[1]); ?>"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Job.objects.exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 100)

    def test_unsupported_extension_rejected(self):
        self.assertEqual(self.post_job(SimpleUploadedFile("x.exe", b"MZ")).status_code, 400)

    def test_insufficient_coins(self):
        wallet.debit(self.user, 99, CoinTransaction.Kind.ADMIN_DEDUCT)
        self.assertEqual(self.post_job(png_upload(), quality="high").status_code, 400)
        self.assertFalse(Job.objects.exists())

    def test_cancel_refunds_once(self):
        self.post_job(png_upload())
        job = Job.objects.get()
        self.client.post(reverse("enhancer:job_cancel", args=[job.pk]))
        self.client.post(reverse("enhancer:job_cancel", args=[job.pk]))
        refund_job(job, "again")
        self.user.refresh_from_db()
        self.assertEqual(self.user.coins, 100)
        self.assertEqual(Job.objects.get().status, "cancelled")

    def test_other_users_cannot_see_job_or_files(self):
        self.post_job(png_upload())
        job = Job.objects.get()
        other = User.objects.create_user("u2", "u2@example.test", "a-strong-pass-123")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("enhancer:job_detail", args=[job.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("enhancer:job_file", args=[job.pk, "input"])).status_code, 404)
        self.client.logout()
        response = self.client.get(reverse("enhancer:job_file", args=[job.pk, "input"]))
        self.assertEqual(response.status_code, 302)

    def test_owner_can_download_input(self):
        self.post_job(png_upload())
        job = Job.objects.get()
        response = self.client.get(reverse("enhancer:job_file", args=[job.pk, "input"]) + "?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        response.close()

    def test_job_limit_per_user(self):
        site = SiteSettings.get()
        for _ in range(site.max_active_jobs):
            self.assertEqual(self.post_job(png_upload()).status_code, 200)
        self.assertEqual(self.post_job(png_upload()).status_code, 400)

    def test_maintenance_mode_blocks_new_jobs(self):
        site = SiteSettings.get()
        site.maintenance_mode = True
        site.save()
        self.assertEqual(self.post_job(png_upload()).status_code, 400)
