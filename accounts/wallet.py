"""All coin balance changes go through this module so every change is atomic and logged."""

from django.db import transaction
from django.db.models import F

from .models import CoinTransaction, User


class InsufficientCoins(Exception):
    pass


def _log(user_id, amount, kind, note, job, by):
    balance = User.objects.values_list("coins", flat=True).get(pk=user_id)
    return CoinTransaction.objects.create(
        user_id=user_id,
        amount=amount,
        balance_after=balance,
        kind=kind,
        note=note[:255],
        job=job,
        created_by=by,
    )


def credit(user, amount, kind, note="", job=None, by=None):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(coins=F("coins") + amount)
        tx = _log(user.pk, amount, kind, note, job, by)
    user.coins = tx.balance_after
    return tx


def debit(user, amount, kind, note="", job=None, by=None, allow_partial=False):
    """Remove coins. Raises InsufficientCoins unless allow_partial, which removes at most the balance."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    with transaction.atomic():
        updated = User.objects.filter(pk=user.pk, coins__gte=amount).update(coins=F("coins") - amount)
        if not updated:
            if not allow_partial:
                raise InsufficientCoins()
            amount = User.objects.values_list("coins", flat=True).get(pk=user.pk)
            if amount == 0:
                user.coins = 0
                return None
            User.objects.filter(pk=user.pk).update(coins=F("coins") - amount)
        tx = _log(user.pk, -amount, kind, note, job, by)
    user.coins = tx.balance_after
    return tx
