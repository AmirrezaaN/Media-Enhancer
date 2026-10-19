import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts import wallet
from accounts.models import CoinTransaction

from .forms import NewJobForm
from .media import MediaError, probe_image, probe_video
from .models import Job, SiteSettings, WorkerStatus

logger = logging.getLogger(__name__)

FILE_FIELDS = {
    "input": "input_file",
    "output": "output_file",
    "before": "input_preview",
    "after": "output_preview",
}


def stage_labels():
    return {
        "": "",
        "waiting": _("Waiting in queue"),
        "loading": _("Loading AI models"),
        "upscaling": _("Enhancing details"),
        "faces": _("Restoring faces"),
        "interpolating": _("Generating extra frames"),
        "encoding": _("Saving the result"),
        "done": _("Finished"),
    }


def home(request):
    return render(request, "enhancer/home.html", {"site": SiteSettings.get()})


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _dashboard_context(request, form=None):
    site = SiteSettings.get()
    return {
        "form": form or NewJobForm(),
        "site": site,
        "prices": {**site.price_table(), "coins": request.user.coins},
        "js_text": {
            "perUnits": _("(%s × 10 seconds)"),
            "notEnough": _("You do not have enough coins for this job."),
            "uploading": _("Uploading... %s%"),
            "processing": _("Upload finished, starting..."),
            "failed": _("Upload failed. Please try again."),
            "chooseFile": _("Please choose a file first."),
            "seconds": _("seconds"),
        },
        "recent_jobs": request.user.jobs.all()[:6],
        "worker_online": WorkerStatus.is_online(),
    }


@login_required
def dashboard(request):
    return render(request, "enhancer/dashboard.html", _dashboard_context(request))


def _fail(request, message, form=None):
    if _wants_json(request):
        return JsonResponse({"ok": False, "error": message}, status=400)
    messages.error(request, message)
    return render(request, "enhancer/dashboard.html", _dashboard_context(request, form), status=400)


@login_required
@require_POST
def create_job(request):
    site = SiteSettings.get()
    if site.maintenance_mode:
        return _fail(request, _("New jobs are paused right now. Please try again later."))

    active = request.user.jobs.filter(status__in=Job.ACTIVE_STATUSES).count()
    if active >= site.max_active_jobs:
        return _fail(request, _("You already have %(n)d jobs in progress. Wait for them to finish.") % {"n": active})

    form = NewJobForm(request.POST, request.FILES)
    if not form.is_valid():
        first_error = next(iter(form.errors.values()))[0]
        return _fail(request, first_error, form)

    data = form.cleaned_data
    upload = data["file"]
    job = Job(
        user=request.user,
        media_type=form.media_type,
        quality=data["quality"],
        scale=data["scale"],
        face_enhance=data["face_enhance"],
        fps_boost=data["fps_boost"],
        original_name=os.path.basename(upload.name)[:255],
    )
    job.input_file.save(upload.name, upload, save=False)

    def discard(message):
        job.input_file.delete(save=False)
        return _fail(request, message, form)

    try:
        if job.is_image:
            info = probe_image(job.input_file.path)
        else:
            info = probe_video(job.input_file.path)
    except MediaError:
        return discard(_("The file could not be read. It may be damaged or in an unsupported format."))

    if min(info.width, info.height) < 16:
        return discard(_("The image is too small."))
    if job.is_image and info.width * info.height > site.max_image_megapixels * 1_000_000:
        return discard(
            _("The image resolution is too high. Maximum: %(mp)s megapixels") % {"mp": site.max_image_megapixels}
        )
    if not job.is_image and info.duration > site.max_video_seconds:
        return discard(_("The video is too long. Maximum: %(s)s seconds") % {"s": site.max_video_seconds})

    job.input_width, job.input_height = info.width, info.height
    job.duration, job.fps = info.duration, info.fps
    job.cost = site.price(job.media_type, job.quality, job.scale, job.face_enhance, job.fps_boost, info.duration)

    try:
        with transaction.atomic():
            job.save()
            if job.cost > 0:
                wallet.debit(request.user, job.cost, CoinTransaction.Kind.JOB_CHARGE, note=job.original_name, job=job)
    except wallet.InsufficientCoins:
        return discard(
            _("Not enough coins. This job costs %(cost)d coins and you have %(have)d.")
            % {"cost": job.cost, "have": request.user.coins}
        )

    logger.info("Job %s created by %s (%s, %d coins)", job.id, request.user.username, job.media_type, job.cost)
    url = reverse("enhancer:job_detail", args=[job.id])
    if _wants_json(request):
        return JsonResponse({"ok": True, "redirect": url})
    return redirect(url)


@login_required
def job_list(request):
    page = Paginator(request.user.jobs.all(), 12).get_page(request.GET.get("page"))
    return render(request, "enhancer/job_list.html", {"page": page})


def _get_user_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if job.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return job


def _queue_position(job):
    if job.status != Job.Status.QUEUED:
        return 0
    return Job.objects.filter(status=Job.Status.QUEUED, created_at__lt=job.created_at).count() + 1


def _status_payload(job):
    eta = None
    if job.status == Job.Status.PROCESSING and job.started_at and job.progress >= 3:
        elapsed = (timezone.now() - job.started_at).total_seconds()
        eta = int(elapsed / job.progress * (100 - job.progress))
    return {
        "status": job.status,
        "status_display": job.get_status_display(),
        "progress": round(job.progress, 1),
        "stage": stage_labels().get(job.stage, job.stage),
        "queue_position": _queue_position(job),
        "eta_seconds": eta,
        "error": job.error_message if job.status == Job.Status.FAILED else "",
        "finished": job.status in (Job.Status.DONE, Job.Status.FAILED, Job.Status.CANCELLED),
    }


@login_required
def job_detail(request, pk):
    job = _get_user_job(request, pk)
    return render(
        request,
        "enhancer/job_detail.html",
        {"job": job, "status": _status_payload(job), "worker_online": WorkerStatus.is_online()},
    )


@login_required
def job_status(request, pk):
    job = _get_user_job(request, pk)
    return JsonResponse(_status_payload(job))


@login_required
def job_file(request, pk, kind):
    job = _get_user_job(request, pk)
    if kind not in FILE_FIELDS or job.files_deleted:
        raise Http404
    field = getattr(job, FILE_FIELDS[kind])
    if not field or not os.path.exists(field.path):
        raise Http404
    download = request.GET.get("download") == "1"
    if kind == "output":
        filename = job.output_filename()
    elif kind == "input":
        filename = job.original_name
    else:
        filename = f"{kind}.jpg"
    response = FileResponse(open(field.path, "rb"), as_attachment=download, filename=filename)
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@require_POST
def job_cancel(request, pk):
    job = _get_user_job(request, pk)
    with transaction.atomic():
        updated = Job.objects.filter(pk=job.pk, status__in=Job.ACTIVE_STATUSES).update(
            status=Job.Status.CANCELLED, finished_at=timezone.now(), stage=""
        )
    if updated:
        job.refresh_from_db()
        refund_job(job, _("Cancelled"))
        messages.success(request, _("The job was cancelled and your coins were returned."))
    return redirect("enhancer:job_detail", pk=job.pk)


@login_required
@require_POST
def job_delete(request, pk):
    job = _get_user_job(request, pk)
    if job.is_active:
        messages.error(request, _("Cancel the job before deleting it."))
        return redirect("enhancer:job_detail", pk=job.pk)
    delete_job_files(job)
    job.delete()
    messages.success(request, _("The job and its files were deleted."))
    return redirect("enhancer:job_list")


def refund_job(job, reason):
    """Give the coins of a failed/cancelled job back exactly once."""
    with transaction.atomic():
        claimed = Job.objects.filter(pk=job.pk, refunded=False).update(refunded=True)
        if claimed and job.cost > 0:
            wallet.credit(job.user, job.cost, CoinTransaction.Kind.JOB_REFUND, note=str(reason), job=job)
    job.refunded = True


def delete_job_files(job):
    for name in FILE_FIELDS.values():
        field = getattr(job, name)
        if field:
            try:
                field.delete(save=False)
            except OSError:
                logger.warning("Could not delete %s", field.name)
    Job.objects.filter(pk=job.pk).update(
        files_deleted=True, input_file="", output_file="", input_preview="", output_preview=""
    )
