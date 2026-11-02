"""JSON API used by the desktop app. Authentication is a bearer token from /login/."""

import json
import logging
from functools import wraps

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts import wallet
from accounts.models import CoinTransaction, User
from accounts.views import LOGIN_MAX_FAILURES, LOGIN_WINDOW, client_ip
from enhancer.models import SiteSettings

from .models import AppJob, AppToken, hash_key

logger = logging.getLogger("enhancer")

MAX_BODY = 16 * 1024


def error(message, status=400, code="error"):
    return JsonResponse({"ok": False, "code": code, "error": str(message)}, status=status)


def read_json(request):
    if len(request.body) > MAX_BODY:
        raise ValueError("body too large")
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid JSON")
    return data


def token_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        key = header[6:].strip() if header.startswith("Token ") else ""
        token = AppToken.objects.select_related("user").filter(key_hash=hash_key(key)).first() if key else None
        if token is None or token.expired or not token.user.is_active:
            if token is not None:
                token.delete()
            return error(_("Your session has expired. Please log in again."), 401, "auth")
        if not SiteSettings.get().app_enabled:
            return error(_("The desktop app is disabled right now. Please use the website."), 403, "disabled")
        AppToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        request.app_token = token
        request.user = token.user
        return view(request, *args, **kwargs)

    return wrapper


def account_payload(user, site):
    return {
        "username": user.username,
        "email": user.email,
        "coins": user.coins,
        "app_price_percent": site.app_price_percent,
        "prices": site.price_table(),
        "limits": {
            "max_image_side": site.max_image_output_side,
            "max_video_side": site.max_video_output_side,
        },
        "video_denoise": site.video_denoise,
    }


@csrf_exempt
@require_POST
def login(request):
    site = SiteSettings.get()
    if not site.app_enabled:
        return error(_("The desktop app is disabled right now. Please use the website."), 403, "disabled")
    key = f"login-fail:{client_ip(request)}"
    if cache.get(key, 0) >= LOGIN_MAX_FAILURES:
        return error(_("Too many failed attempts. Please try again in 15 minutes."), 429, "throttled")
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(exc)

    username = str(data.get("username", "")).strip()[:254]
    password = str(data.get("password", ""))[:256]
    if "@" in username:
        match = User.objects.filter(email__iexact=username).first()
        if match:
            username = match.get_username()
    user = authenticate(request, username=username, password=password) if username and password else None
    if user is None:
        cache.add(key, 0, LOGIN_WINDOW)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_WINDOW)
        return error(_("Wrong username or password."), 401, "credentials")

    cache.delete(key)
    _token, raw_key = AppToken.issue(user, str(data.get("device", "")))
    logger.info("Desktop app login: %s", user.username)
    return JsonResponse({"ok": True, "token": raw_key, "account": account_payload(user, site)})


@csrf_exempt
@require_POST
@token_required
def logout(request):
    request.app_token.delete()
    return JsonResponse({"ok": True})


@require_GET
@token_required
def me(request):
    return JsonResponse({"ok": True, "account": account_payload(request.user, SiteSettings.get())})


@csrf_exempt
@require_POST
@token_required
def start_job(request):
    """Charge coins for a job the app is about to run locally."""
    site = SiteSettings.get()
    try:
        data = read_json(request)
        media_type = data.get("media_type")
        quality = data.get("quality")
        scale = int(data.get("scale", 0))
        face = bool(data.get("face", False))
        fps_boost = bool(data.get("fps_boost", False)) and media_type == "video"
        duration = float(data.get("duration", 0) or 0)
        width, height = int(data.get("width", 0)), int(data.get("height", 0))
    except (TypeError, ValueError):
        return error(_("Invalid request."))
    if media_type not in ("image", "video") or quality not in ("fast", "high") or scale not in (2, 4):
        return error(_("Invalid request."))
    if media_type == "video" and not (0 < duration <= 24 * 3600):
        return error(_("Invalid request."))

    cost = site.app_price(media_type, quality, scale, face, fps_boost, duration)
    job = AppJob(
        user=request.user, token=request.app_token, media_type=media_type, quality=quality, scale=scale,
        face_enhance=face, fps_boost=fps_boost, duration=duration if media_type == "video" else 0,
        input_width=max(0, width), input_height=max(0, height), cost=cost,
        original_name=str(data.get("name", ""))[:255], gpu=str(data.get("gpu", ""))[:150],
        app_version=str(data.get("app_version", ""))[:20],
    )
    try:
        with transaction.atomic():
            job.save()
            if cost > 0:
                wallet.debit(request.user, cost, CoinTransaction.Kind.APP_CHARGE, note=job.original_name)
    except wallet.InsufficientCoins:
        return error(
            _("Not enough coins. This job costs %(cost)d coins and you have %(have)d.")
            % {"cost": cost, "have": request.user.coins},
            402, "coins",
        )
    request.user.refresh_from_db(fields=["coins"])
    return JsonResponse({"ok": True, "job_id": str(job.pk), "cost": cost, "coins": request.user.coins})


@csrf_exempt
@require_POST
@token_required
def finish_job(request, pk):
    """Report the outcome. Failed or cancelled jobs get their coins back (once)."""
    job = AppJob.objects.filter(pk=pk, user=request.user).first()
    if job is None:
        return error(_("Job not found."), 404, "not_found")
    try:
        data = read_json(request)
    except ValueError as exc:
        return error(exc)
    status = data.get("status")
    if status not in (AppJob.Status.DONE, AppJob.Status.FAILED, AppJob.Status.CANCELLED):
        return error(_("Invalid request."))

    with transaction.atomic():
        updated = AppJob.objects.filter(pk=job.pk, status=AppJob.Status.STARTED).update(
            status=status,
            finished_at=timezone.now(),
            processing_seconds=max(0, int(data.get("seconds") or 0)),
            error_message=str(data.get("error", ""))[:2000],
        )
        if updated and status != AppJob.Status.DONE and job.cost > 0:
            if AppJob.objects.filter(pk=job.pk, refunded=False).update(refunded=True):
                wallet.credit(request.user, job.cost, CoinTransaction.Kind.APP_REFUND, note=job.original_name)
    request.user.refresh_from_db(fields=["coins"])
    return JsonResponse({"ok": True, "coins": request.user.coins})
