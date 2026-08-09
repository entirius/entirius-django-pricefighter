# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply a quoted decision: recompute on apply (never trust a stale preview),
compare against `expected_new_price`, write through pricemanager's edit_price() (which owns
precedence + bounds), and log a PriceDecision only for an actual write. Best-effort — one
item failing does not roll back the rest of a batch.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone
from django_pricemanager.models import Channel as PmChannel
from django_pricemanager.models.channel import CalculateDirectionEnum
from django_pricemanager.models.choices import PriceSource
from django_pricemanager.services.price_bounds_service import get_current_prices_bulk
from django_pricemanager.services.price_edit_service import edit_price
from django_pricemanager.services.price_write_guard import load_policy_map
from django_regional.models import Country, Currency

from django_pricefighter import settings as pf_settings
from django_pricefighter.models import Channel as PfChannel
from django_pricefighter.models import PriceDecision, ProductRepresentation
from django_pricefighter.services import engine_inputs, market_service
from django_pricefighter.services.quote_engine import EngineDecision, Recommendation, compute_decision

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")

_ACTIONABLE = frozenset(
    {Recommendation.COMPETE, Recommendation.RAISE, Recommendation.REVERT_BASELINE, Recommendation.HOLD_AT_FLOOR}
)

_STRATEGY_FOR_RECOMMENDATION = {
    Recommendation.COMPETE: PriceDecision.Strategy.COMPETE,
    Recommendation.RAISE: PriceDecision.Strategy.RAISE,
    Recommendation.REVERT_BASELINE: PriceDecision.Strategy.REVERT_BASELINE,
    Recommendation.HOLD_AT_FLOOR: PriceDecision.Strategy.HOLD_AT_FLOOR,
}


@dataclass(frozen=True)
class ApplyItem:
    sku: str
    channel_idx: str
    country: str
    currency: str
    expected_new_price: Decimal


@dataclass(frozen=True)
class ApplyResult:
    item: ApplyItem
    bucket: str  # applied | clamped | skipped | failed | stale
    reason: str


def record_strategy_outcome(*, decision: EngineDecision, price_decision: PriceDecision) -> None:
    """v2 hook — no-op. StrategyOutcome (source x price-range x strategy x market memory) is a
    v2 concept; the call site is wired now so v2 doesn't need to touch apply_service again."""


def _serialize_reason(decision: EngineDecision) -> dict:
    return {
        "reference_price": str(decision.reference_price) if decision.reference_price is not None else None,
        "baseline": str(decision.baseline) if decision.baseline is not None else None,
        "floor": str(decision.floor) if decision.floor is not None else None,
        "current_price": str(decision.current_price),
        "gap_baseline": str(decision.gap_baseline) if decision.gap_baseline is not None else None,
        "gap_current": str(decision.gap_current) if decision.gap_current is not None else None,
        "estimator": decision.estimator,
        "no_action_reason": decision.reason,
        "observations": [
            {
                "source_idx": o.source_idx,
                "price": str(o.price),
                "currency": o.currency,
                "stock": o.stock,
                "ts": o.ts.isoformat(),
                "is_trusted": o.is_trusted,
                "flag": o.flag,
            }
            for o in decision.observations
        ],
    }


def _resolve_market_objects(channel_idx: str, country: str, currency: str):
    pm_channel = PmChannel.objects.filter(idx=channel_idx).first()
    pf_channel = PfChannel.objects.filter(idx=channel_idx).first()
    country_obj = Country.objects.filter(iso2=country).first()
    currency_obj = Currency.objects.filter(iso3=currency).first()
    return pm_channel, pf_channel, country_obj, currency_obj


def _apply_value_for_direction(target: Decimal, pm_channel: PmChannel, tax_rate) -> Decimal:
    if pm_channel.calculate_direction == CalculateDirectionEnum.FROM_GROSS_TO_NET:
        return target
    return tax_rate.net_price(target)


@transaction.atomic
def apply_single(item: ApplyItem, *, user=None, policy_map=None) -> ApplyResult:
    """Recompute the decision for exactly this (sku, market), verify it still matches what the
    operator saw (`expected_new_price`), and write it. `country` scopes the write to exactly
    this market — other countries on the same channel are never touched.
    """
    now = timezone.now()
    markets = [market_service.Market(channel_idx=item.channel_idx, country=item.country, currency=item.currency)]
    inputs = engine_inputs.build_engine_inputs(
        [item.sku],
        markets,
        now=now,
        staleness_days=pf_settings.PRICEFIGHTER_STALENESS_DAYS,
        estimator=pf_settings.PRICEFIGHTER_REF_ESTIMATOR,
    )
    if not inputs:
        return ApplyResult(item=item, bucket="failed", reason="no_current_price")
    decision = compute_decision(inputs[0])

    if decision.recommendation not in _ACTIONABLE:
        return ApplyResult(item=item, bucket="skipped", reason=f"not_actionable:{decision.reason}")

    if decision.suggested_price is None or decision.suggested_price.quantize(CENTS) != item.expected_new_price.quantize(
        CENTS
    ):
        return ApplyResult(item=item, bucket="stale", reason="expected_new_price_mismatch")

    pm_channel, pf_channel, country_obj, currency_obj = _resolve_market_objects(
        item.channel_idx, item.country, item.currency
    )
    if not all([pm_channel, pf_channel, country_obj, currency_obj]):
        return ApplyResult(item=item, bucket="failed", reason="unknown_market")

    representation = (
        ProductRepresentation.objects.annotate(sku_lower=Lower("sku"))
        .filter(sku_lower=item.sku.lower(), channel=pf_channel)
        .first()
    )
    if representation is None:
        return ApplyResult(item=item, bucket="failed", reason="no_representation")

    cp = get_current_prices_bulk([(item.sku, pm_channel, country_obj, currency_obj)]).get(
        (item.sku, pm_channel.idx, country_obj.iso2, currency_obj.iso3)
    )
    if cp is None or cp.tax_rate is None:
        return ApplyResult(item=item, bucket="failed", reason="no_tax_rate")

    value = _apply_value_for_direction(decision.suggested_price, pm_channel, cp.tax_rate)
    is_revert = decision.recommendation == Recommendation.REVERT_BASELINE

    try:
        report = edit_price(
            channel=pm_channel,
            sku=item.sku,
            value=value,
            currency_code=item.currency,
            source=PriceSource.PRICEFIGHTER,
            country=country_obj,
            user=user,
            policy_map=policy_map,
            stored_source=PriceSource.BASELINE if is_revert else None,
        )
    except ValueError as exc:
        return ApplyResult(item=item, bucket="failed", reason=str(exc))

    if report.skipped:
        return ApplyResult(item=item, bucket="skipped", reason=report.skipped[0]["reason"])
    if not report.applied:
        return ApplyResult(item=item, bucket="failed", reason="no_row_applied")

    applied_cp = report.applied[0]
    bucket = "clamped" if report.clamped else "applied"

    price_decision = PriceDecision.objects.create(
        representation=representation,
        channel=pf_channel,
        country=item.country,
        currency=item.currency,
        old_price=decision.current_price,
        new_price=applied_cp.gross_value,
        strategy=_STRATEGY_FOR_RECOMMENDATION[decision.recommendation],
        mode=decision.mode,
        applied_by=user,
        reason=_serialize_reason(decision),
    )
    record_strategy_outcome(decision=decision, price_decision=price_decision)

    return ApplyResult(item=item, bucket=bucket, reason=report.clamped[0]["reason"] if report.clamped else "ok")


def apply_batch(items: list[ApplyItem], *, user=None) -> dict[str, list[ApplyResult]]:
    """Best-effort: every item resolves independently into exactly one bucket. One item's
    ValueError/skip/clamp never affects another item's outcome."""
    policy_map = load_policy_map()
    report: dict[str, list[ApplyResult]] = {"applied": [], "clamped": [], "skipped": [], "failed": [], "stale": []}
    for item in items:
        try:
            result = apply_single(item, user=user, policy_map=policy_map)
        except Exception:
            logger.exception("apply_single failed unexpectedly for %r", item)
            result = ApplyResult(item=item, bucket="failed", reason="internal_error")
        report[result.bucket].append(result)
    return report
