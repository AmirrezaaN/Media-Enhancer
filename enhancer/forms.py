from django import forms
from django.utils.translation import gettext_lazy as _

from .media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, media_type_for
from .models import Job, SiteSettings


class NewJobForm(forms.Form):
    file = forms.FileField(label=_("Image or video"))
    quality = forms.ChoiceField(label=_("Mode"), choices=Job.Quality.choices, initial=Job.Quality.HIGH)
    scale = forms.TypedChoiceField(label=_("Upscale"), choices=[(2, "2x"), (4, "4x")], coerce=int, initial=4)
    face_enhance = forms.BooleanField(label=_("Restore faces"), required=False)
    fps_boost = forms.BooleanField(label=_("Smooth motion (double FPS, video only)"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accept = ",".join(f".{e}" for e in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))
        self.fields["file"].widget.attrs.update({"accept": accept, "id": "file-input"})

    def clean_file(self):
        f = self.cleaned_data["file"]
        media_type = media_type_for(f.name)
        if media_type is None:
            raise forms.ValidationError(_("This file type is not supported."))
        site = SiteSettings.get()
        limit_mb = site.max_image_mb if media_type == "image" else site.max_video_mb
        if f.size > limit_mb * 1024 * 1024:
            raise forms.ValidationError(_("The file is too large. Maximum: %(mb)s MB") % {"mb": limit_mb})
        self.media_type = media_type
        return f

    def clean(self):
        data = super().clean()
        if getattr(self, "media_type", None) == "image":
            data["fps_boost"] = False
        return data
