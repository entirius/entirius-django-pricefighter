# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API service for PricingRule CRUD. `_EDITABLE_FIELDS` is the whole
mass-assignment defense (django-rest-api rule §7) — no parallel field checks elsewhere.
`channel` is whitelisted as a scope FK (part of the rule's own contract, not an arbitrary
relation repoint) but is resolved by idx, never a raw PK, and validated to exist.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from django_pricefighter.models import Channel, PricingRule

_EDITABLE_FIELDS = frozenset({"strategy", "mode", "price_war", "sku", "category_idx", "channel"})


def _resolve_channel(channel_idx: str | None) -> Channel | None:
    if channel_idx is None:
        return None
    channel = Channel.objects.filter(idx=channel_idx).first()
    if channel is None:
        raise ValueError(f"Unknown channel: {channel_idx!r}")
    return channel


def _full_clean(rule: PricingRule) -> None:
    try:
        rule.full_clean()
    except DjangoValidationError as exc:
        raise ValueError("; ".join(exc.messages)) from exc


def list_rules() -> QuerySet[PricingRule]:
    return PricingRule.objects.select_related("channel").all()


def get_rule(pk: int) -> PricingRule:
    return PricingRule.objects.select_related("channel").get(pk=pk)


def create_rule(updates: dict) -> PricingRule:
    invalid = set(updates) - _EDITABLE_FIELDS
    if invalid:
        raise ValueError(f"Fields not editable via create_rule: {sorted(invalid)}")
    updates = dict(updates)
    channel = _resolve_channel(updates.pop("channel", None))
    rule = PricingRule(channel=channel, **updates)
    _full_clean(rule)
    rule.save()
    return rule


def update_rule(*, rule: PricingRule, updates: dict) -> PricingRule:
    invalid = set(updates) - _EDITABLE_FIELDS
    if invalid:
        raise ValueError(f"Fields not editable via update_rule: {sorted(invalid)}")
    updates = dict(updates)
    if "channel" in updates:
        rule.channel = _resolve_channel(updates.pop("channel"))
    for field, value in updates.items():
        setattr(rule, field, value)
    _full_clean(rule)
    rule.save()
    return rule


def delete_rule(rule: PricingRule) -> None:
    rule.delete()
