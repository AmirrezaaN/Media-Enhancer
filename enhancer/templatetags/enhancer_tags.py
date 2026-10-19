from datetime import timedelta

from django import template
from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import CoinTransaction, User
from enhancer.models import Job, WorkerStatus

register = template.Library()


@register.simple_tag
def admin_stats():
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    jobs = Job.objects.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(created_at__gte=day_ago)),
        queued=Count("id", filter=Q(status=Job.Status.QUEUED)),
        processing=Count("id", filter=Q(status=Job.Status.PROCESSING)),
        done=Count("id", filter=Q(status=Job.Status.DONE)),
        failed=Count("id", filter=Q(status=Job.Status.FAILED)),
    )
    spent = CoinTransaction.objects.filter(kind=CoinTransaction.Kind.JOB_CHARGE).aggregate(s=Sum("amount"))["s"] or 0
    refunded = CoinTransaction.objects.filter(kind=CoinTransaction.Kind.JOB_REFUND).aggregate(s=Sum("amount"))["s"] or 0
    return {
        "users": User.objects.count(),
        "users_today": User.objects.filter(date_joined__gte=day_ago).count(),
        "coins_in_wallets": User.objects.aggregate(s=Sum("coins"))["s"] or 0,
        "coins_spent": -spent - refunded,
        "jobs": jobs,
        "worker_online": WorkerStatus.is_online(),
        "worker": WorkerStatus.objects.filter(pk=1).first(),
    }


@register.filter
def duration(seconds):
    if seconds is None:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@register.simple_tag(takes_context=True)
def lang_url(context):
    request = context.get("request")
    return request.get_full_path() if request else "/"
