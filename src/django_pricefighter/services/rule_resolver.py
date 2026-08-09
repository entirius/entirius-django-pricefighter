# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""PricingRule resolution — most-specific-wins: sku > category > channel."""

from dataclasses import dataclass

from django_pricefighter.models import Channel, PricingRule


@dataclass(frozen=True)
class ResolvedRule:
    strategy: str
    mode: str
    price_war: bool
    rule_id: int | None


DEFAULT_RESOLVED_RULE = ResolvedRule(
    strategy=PricingRule.Strategy.HOLD, mode=PricingRule.Mode.SUGGESTION, price_war=False, rule_id=None
)


def resolve(sku: str | None, category_idx: str | None, channel: Channel | None) -> ResolvedRule:
    """Resolve the pricing strategy for a sku×market. Most-specific-wins, deterministic tie-break by pk."""
    rule = None
    if sku:
        rule = PricingRule.objects.filter(sku__iexact=sku).order_by("pk").first()
    if rule is None and category_idx:
        rule = PricingRule.objects.filter(category_idx=category_idx).order_by("pk").first()
    if rule is None and channel is not None:
        rule = PricingRule.objects.filter(channel=channel).order_by("pk").first()

    if rule is None:
        return DEFAULT_RESOLVED_RULE

    return ResolvedRule(strategy=rule.strategy, mode=rule.mode, price_war=rule.price_war, rule_id=rule.pk)


def resolve_bulk(items: list[tuple[str, str, Channel | None]]) -> dict[tuple[str, int | None], ResolvedRule]:
    """Batch resolve() for many (sku, category_idx, channel) items — one query for every
    PricingRule instead of up to 3 per item. Same most-specific-wins + pk tie-break semantics
    as resolve(). Keyed by (sku.lower(), channel.pk or None)."""
    by_sku: dict[str, PricingRule] = {}
    by_category: dict[str, PricingRule] = {}
    by_channel: dict[int, PricingRule] = {}
    for rule in PricingRule.objects.all().order_by("pk"):
        if rule.sku:
            by_sku.setdefault(rule.sku.lower(), rule)
        elif rule.category_idx:
            by_category.setdefault(rule.category_idx, rule)
        elif rule.channel_id:
            by_channel.setdefault(rule.channel_id, rule)

    result: dict[tuple[str, int | None], ResolvedRule] = {}
    for sku, category_idx, channel in items:
        rule = by_sku.get(sku.lower())
        if rule is None and category_idx:
            rule = by_category.get(category_idx)
        if rule is None and channel is not None:
            rule = by_channel.get(channel.pk)
        resolved = (
            ResolvedRule(strategy=rule.strategy, mode=rule.mode, price_war=rule.price_war, rule_id=rule.pk)
            if rule is not None
            else DEFAULT_RESOLVED_RULE
        )
        result[(sku.lower(), channel.pk if channel else None)] = resolved
    return result
