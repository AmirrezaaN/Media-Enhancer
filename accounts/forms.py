from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label=_("Email"), max_length=254)
    referral_code = forms.CharField(
        label=_("Referral code (optional)"),
        max_length=12,
        required=False,
    )

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email

    def clean_referral_code(self):
        code = self.cleaned_data.get("referral_code", "").strip().upper()
        if not code:
            return None
        referrer = User.objects.filter(referral_code=code, is_active=True).first()
        if referrer is None:
            raise forms.ValidationError(_("This referral code is not valid."))
        return referrer


class LoginForm(AuthenticationForm):
    username = forms.CharField(label=_("Username or email"), max_length=254)

    def clean(self):
        # Allow logging in with the email address as well.
        username = self.cleaned_data.get("username", "")
        if "@" in username:
            user = User.objects.filter(email__iexact=username.strip()).first()
            if user:
                self.cleaned_data["username"] = user.get_username()
        return super().clean()
