# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pure quoting pipeline.

Zero ORM, zero Django imports — same inputs always produce the same output. Every fetch
(observations, bounds, config, rules) lives in engine_inputs.py; this module only computes.
`now` is always passed in (never `timezone.now()`) so unit tests stay deterministic.

Contract with callers: `EngineInput.current_price` must already be resolved to a real value —
callers only build an EngineInput for (sku, market) pairs where a CurrentPrice row exists.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


class Estimator:
    MIN = "min"
    SECOND_BEST = "second_best"
    MEDIAN = "median"


class Strategy:
    HOLD = "hold"
    COMPETE = "compete"
    RAISE = "raise"


class Recommendation:
    COMPETE = "compete"
    RAISE = "raise"
    HOLD = "hold"
    REVERT_BASELINE = "revert_baseline"
    HOLD_AT_FLOOR = "hold_at_floor"
    NO_RECOMMENDATION = "no_recommendation"


class ObservationFlag:
    VALID = "valid"
    STALE = "stale"
    UNTRUSTED = "untrusted"
    OOS = "oos"
    CURRENCY_MISMATCH = "currency_mismatch"


@dataclass(frozen=True)
class ObservationInput:
    source_idx: str
    price: Decimal
    currency: str | None
    stock: int | None
    ts: datetime
    is_trusted: bool
    source_country: str | None  # None = global source


@dataclass(frozen=True)
class ObservationView:
    source_idx: str
    price: Decimal
    currency: str | None
    stock: int | None
    ts: datetime
    is_trusted: bool
    flag: str


@dataclass(frozen=True)
class QuoteConfigRow:
    range_from: Decimal
    range_to: Decimal | None
    band_dn: Decimal
    band_up: Decimal
    undercut: Decimal
    headroom: Decimal
    max_step: Decimal
    rounding: str  # "none" | ".99" | ".95" | "int"


@dataclass(frozen=True)
class EngineInput:
    sku: str
    channel_idx: str
    country: str
    currency: str
    current_price: Decimal
    current_price_net: Decimal
    current_price_source: str | None
    cost: Decimal | None
    floor: Decimal | None
    baseline: Decimal | None
    observations: list[ObservationInput]
    quote_config_rows: list[QuoteConfigRow]
    strategy: str
    mode: str
    price_war: bool
    now: datetime
    staleness_days: int
    estimator: str


@dataclass(frozen=True)
class EngineDecision:
    sku: str
    channel_idx: str
    country: str
    currency: str
    current_price: Decimal
    current_price_net: Decimal
    cost: Decimal | None
    floor: Decimal | None
    baseline: Decimal | None
    reference_price: Decimal | None
    estimator: str
    gap_baseline: Decimal | None
    gap_current: Decimal | None
    observations: list[ObservationView]
    recommendation: str
    suggested_price: Decimal | None
    reason: str
    strategy: str
    mode: str
    price_war: bool
    clamped_floor: bool = False
    clamped_step: bool = False


def estimate_reference_price(prices: list[Decimal], estimator: str) -> Decimal:
    """R from a batch of valid observation prices. Deterministic — never averages a price
    that wasn't observed."""
    ordered = sorted(prices)
    if estimator == Estimator.SECOND_BEST:
        return ordered[1] if len(ordered) > 1 else ordered[0]
    if estimator == Estimator.MEDIAN:
        n = len(ordered)
        mid = n // 2 if n % 2 else n // 2 - 1  # even count -> lower middle
        return ordered[mid]
    return ordered[0]  # MIN (default)


def _flag_observations(
    observations: list[ObservationInput],
    *,
    market_country: str,
    market_currency: str,
    staleness_days: int,
    now: datetime,
) -> list[ObservationView]:
    cutoff = now - timedelta(days=staleness_days)
    in_market = [o for o in observations if o.source_country is None or o.source_country == market_country]
    views = []
    for o in in_market:
        if o.ts < cutoff:
            flag = ObservationFlag.STALE
        elif not o.is_trusted:
            flag = ObservationFlag.UNTRUSTED
        elif o.currency != market_currency:
            flag = ObservationFlag.CURRENCY_MISMATCH
        elif o.stock == 0:
            flag = ObservationFlag.OOS
        else:
            flag = ObservationFlag.VALID
        views.append(
            ObservationView(
                source_idx=o.source_idx,
                price=o.price,
                currency=o.currency,
                stock=o.stock,
                ts=o.ts,
                is_trusted=o.is_trusted,
                flag=flag,
            )
        )
    return views


def _no_comp_reason(views: list[ObservationView]) -> str:
    if not views:
        return "no_competitor"
    return max(views, key=lambda v: v.ts).flag


def _apply_rounding(value: Decimal, rounding: str) -> Decimal:
    if rounding == "int":
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if rounding in (".99", ".95"):
        suffix = Decimal("0.99") if rounding == ".99" else Decimal("0.95")
        return value.to_integral_value(rounding=ROUND_FLOOR) + suffix
    return value  # "none"


def _clamp_floor(value: Decimal, floor: Decimal | None) -> tuple[Decimal, bool]:
    if floor is not None and value < floor:
        return floor, True
    return value, False


def _limit_step(value: Decimal, current: Decimal, max_step: Decimal) -> tuple[Decimal, bool]:
    delta = value - current
    if abs(delta) > max_step:
        return current + (max_step if delta > 0 else -max_step), True
    return value, False


def _find_quote_config(rows: list[QuoteConfigRow], reference_price: Decimal) -> QuoteConfigRow | None:
    for row in rows:
        if row.range_from <= reference_price and (row.range_to is None or reference_price < row.range_to):
            return row
    return None


def _side_permission(raw_side: str, strategy: str) -> str:
    """PricingRule.strategy is a directional permission, not an engine on/off switch: `compete`
    only ever competes downward, `raise` only ever grabs margin upward, `hold` never moves."""
    if strategy == Strategy.HOLD:
        return Recommendation.HOLD
    if strategy == Strategy.COMPETE:
        return raw_side if raw_side in (Recommendation.COMPETE, Recommendation.HOLD) else Recommendation.HOLD
    if strategy == Strategy.RAISE:
        return raw_side if raw_side in (Recommendation.RAISE, Recommendation.HOLD) else Recommendation.HOLD
    return Recommendation.HOLD


def compute_decision(inp: EngineInput) -> EngineDecision:
    views = _flag_observations(
        inp.observations,
        market_country=inp.country,
        market_currency=inp.currency,
        staleness_days=inp.staleness_days,
        now=inp.now,
    )
    valid = [v for v in views if v.flag == ObservationFlag.VALID]

    base = {
        "sku": inp.sku,
        "channel_idx": inp.channel_idx,
        "country": inp.country,
        "currency": inp.currency,
        "current_price": inp.current_price,
        "current_price_net": inp.current_price_net,
        "cost": inp.cost,
        "floor": inp.floor,
        "baseline": inp.baseline,
        "observations": views,
        "estimator": inp.estimator,
        "strategy": inp.strategy,
        "mode": inp.mode,
        "price_war": inp.price_war,
    }

    if not valid:
        cause = _no_comp_reason(views)
        if inp.current_price_source == "pricefighter" and inp.baseline is not None:
            return EngineDecision(
                **base,
                reference_price=None,
                gap_baseline=None,
                gap_current=None,
                recommendation=Recommendation.REVERT_BASELINE,
                suggested_price=inp.baseline,
                reason=cause,
            )
        if inp.current_price_source == "pricefighter":
            return EngineDecision(
                **base,
                reference_price=None,
                gap_baseline=None,
                gap_current=None,
                recommendation=Recommendation.HOLD,
                suggested_price=inp.current_price,
                reason="no_baseline",
            )
        return EngineDecision(
            **base,
            reference_price=None,
            gap_baseline=None,
            gap_current=None,
            recommendation=Recommendation.HOLD,
            suggested_price=inp.current_price,
            reason=cause,
        )

    reference_price = estimate_reference_price([v.price for v in valid], inp.estimator)
    gap_current = reference_price - inp.current_price

    if inp.baseline is None:
        return EngineDecision(
            **base,
            reference_price=reference_price,
            gap_baseline=None,
            gap_current=gap_current,
            recommendation=Recommendation.NO_RECOMMENDATION,
            suggested_price=None,
            reason="no_cost",
        )

    gap_baseline = reference_price - inp.baseline
    config_row = _find_quote_config(inp.quote_config_rows, reference_price)
    if config_row is None:
        return EngineDecision(
            **base,
            reference_price=reference_price,
            gap_baseline=gap_baseline,
            gap_current=gap_current,
            recommendation=Recommendation.HOLD,
            suggested_price=inp.current_price,
            reason="no_quote_config",
        )

    if gap_baseline > config_row.band_up:
        raw_side = Recommendation.RAISE
    elif gap_baseline < -config_row.band_dn:
        raw_side = Recommendation.COMPETE
    else:
        raw_side = Recommendation.HOLD

    if inp.price_war and raw_side == Recommendation.COMPETE:
        if inp.floor is None:
            return EngineDecision(
                **base,
                reference_price=reference_price,
                gap_baseline=gap_baseline,
                gap_current=gap_current,
                recommendation=Recommendation.HOLD,
                suggested_price=inp.current_price,
                reason="price_war_no_floor",
            )
        return EngineDecision(
            **base,
            reference_price=reference_price,
            gap_baseline=gap_baseline,
            gap_current=gap_current,
            recommendation=Recommendation.HOLD_AT_FLOOR,
            suggested_price=inp.floor.quantize(CENTS),
            reason="price_war",
        )

    side = _side_permission(raw_side, inp.strategy)
    if side == Recommendation.HOLD:
        reason = "in_band" if raw_side == Recommendation.HOLD else "strategy_scope"
        return EngineDecision(
            **base,
            reference_price=reference_price,
            gap_baseline=gap_baseline,
            gap_current=gap_current,
            recommendation=Recommendation.HOLD,
            suggested_price=inp.current_price,
            reason=reason,
        )

    target = reference_price - (config_row.undercut if side == Recommendation.COMPETE else config_row.headroom)
    target = _apply_rounding(target, config_row.rounding)
    target, clamped_floor = _clamp_floor(target, inp.floor)
    target, clamped_step = _limit_step(target, inp.current_price, config_row.max_step)
    target = target.quantize(CENTS)
    reason = "clamped_floor" if clamped_floor else ("clamped_step" if clamped_step else "ok")

    return EngineDecision(
        **base,
        reference_price=reference_price,
        gap_baseline=gap_baseline,
        gap_current=gap_current,
        recommendation=side,
        suggested_price=target,
        reason=reason,
        clamped_floor=clamped_floor,
        clamped_step=clamped_step,
    )
