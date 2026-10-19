from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from . import wallet
from .models import CoinTransaction, User


class CoinAdjustForm(forms.Form):
    amount = forms.IntegerField(
        label=_("Amount"),
        help_text=_("Positive to add coins, negative to remove coins."),
    )
    note = forms.CharField(label=_("Note"), max_length=200, required=False)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError(_("Amount cannot be zero."))
        if abs(amount) > 1_000_000:
            raise forms.ValidationError(_("Amount is too large."))
        return amount


def apply_adjustment(users, amount, note, by):
    count = 0
    with transaction.atomic():
        for user in users:
            if amount > 0:
                wallet.credit(user, amount, CoinTransaction.Kind.ADMIN_GRANT, note=note, by=by)
            else:
                wallet.debit(user, -amount, CoinTransaction.Kind.ADMIN_DEDUCT, note=note, by=by, allow_partial=True)
            count += 1
    return count


class AdminUserChangeForm(UserChangeForm):
    coin_adjustment = forms.IntegerField(
        label=_("Add / remove coins"),
        required=False,
        help_text=_("Example: 50 adds 50 coins, -20 removes 20 coins. Leave empty for no change."),
    )
    coin_note = forms.CharField(label=_("Coin change note"), max_length=200, required=False)


class TransactionInline(admin.TabularInline):
    model = CoinTransaction
    fk_name = "user"
    extra = 0
    can_delete = False
    max_num = 0
    fields = ("created_at", "kind", "amount", "balance_after", "note", "created_by")
    readonly_fields = fields
    ordering = ("-created_at",)
    show_change_link = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = AdminUserChangeForm
    list_display = ("username", "email", "coins", "is_active", "is_staff", "date_joined", "referral_count")
    list_filter = ("is_active", "is_staff", "date_joined")
    search_fields = ("username", "email", "referral_code")
    readonly_fields = ("coins", "referral_code", "referred_by", "last_login", "date_joined")
    actions = ["adjust_coins_action", "activate_users", "deactivate_users"]
    inlines = [TransactionInline]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (_("Coins"), {"fields": ("coins", "coin_adjustment", "coin_note", "referral_code", "referred_by")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "email", "password1", "password2")}),
    )

    @admin.display(description=_("referrals"))
    def referral_count(self, obj):
        return obj.referrals.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        amount = form.cleaned_data.get("coin_adjustment") if change else None
        if amount:
            note = form.cleaned_data.get("coin_note", "")
            apply_adjustment([obj], amount, note, request.user)
            obj.refresh_from_db(fields=["coins"])
            messages.success(request, _("Coins updated. New balance: %(coins)s") % {"coins": obj.coins})

    @admin.action(description=_("Add / remove coins for selected users"))
    def adjust_coins_action(self, request, queryset):
        if "apply" in request.POST:
            form = CoinAdjustForm(request.POST)
            if form.is_valid():
                n = apply_adjustment(
                    list(queryset), form.cleaned_data["amount"], form.cleaned_data["note"], request.user
                )
                self.message_user(request, _("Coins updated for %(n)d users.") % {"n": n}, messages.SUCCESS)
                return None
        else:
            form = CoinAdjustForm()
        return render(
            request,
            "admin/accounts/adjust_coins.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Add / remove coins"),
                "form": form,
                "users": queryset,
                "action": "adjust_coins_action",
                "selected": request.POST.getlist(admin.helpers.ACTION_CHECKBOX_NAME),
                "opts": self.model._meta,
            },
        )

    @admin.action(description=_("Activate selected users"))
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description=_("Deactivate (block) selected users"))
    def deactivate_users(self, request, queryset):
        queryset.exclude(pk=request.user.pk).update(is_active=False)

    def get_urls(self):
        custom = [
            path(
                "grant-all/",
                self.admin_site.admin_view(self.grant_all_view),
                name="accounts_user_grant_all",
            ),
        ]
        return custom + super().get_urls()

    def grant_all_view(self, request):
        if not request.user.has_perm("accounts.change_user"):
            return redirect("admin:index")
        form = CoinAdjustForm(request.POST or None)
        users = User.objects.filter(is_active=True)
        if request.method == "POST" and form.is_valid():
            n = apply_adjustment(list(users), form.cleaned_data["amount"], form.cleaned_data["note"], request.user)
            self.message_user(request, _("Coins updated for %(n)d users.") % {"n": n}, messages.SUCCESS)
            return redirect(reverse("admin:accounts_user_changelist"))
        return render(
            request,
            "admin/accounts/grant_all.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Add / remove coins for all users"),
                "form": form,
                "user_count": users.count(),
                "opts": self.model._meta,
            },
        )


@admin.register(CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "amount", "balance_after", "note", "created_by")
    list_filter = ("kind", "created_at")
    search_fields = ("user__username", "user__email", "note")
    list_select_related = ("user", "created_by")
    date_hierarchy = "created_at"

    # The ledger is append-only: it can be viewed but not edited or deleted.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
