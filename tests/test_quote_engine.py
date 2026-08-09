# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit tests for the pure quoting pipeline — no DB."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from django_pricefighter.services.quote_engine import (
    EngineInput,
    ObservationInput,
    QuoteConfigRow,
    Recommendation,
    compute_decision,
    estimate_reference_price,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def obs(price, *, currency="USD", stock=None, ts=NOW, trusted=True, country=None, idx="src"):
    return ObservationInput(
        source_idx=idx,
        price=Decimal(str(price)),
        currency=currency,
        stock=stock,
        ts=ts,
        is_trusted=trusted,
        source_country=country,
    )


def quote_config(**overrides):
    defaults = {
        "range_from": Decimal("0"),
        "range_to": None,
        "band_dn": Decimal("3.00"),
        "band_up": Decimal("3.00"),
        "undercut": Decimal("1.00"),
        "headroom": Decimal("1.00"),
        "max_step": Decimal("40.00"),
        "rounding": "none",
    }
    defaults.update(overrides)
    return QuoteConfigRow(**defaults)


def engine_input(**overrides):
    defaults = {
        "sku": "SKU-1",
        "channel_idx": "ch",
        "country": "DE",
        "currency": "USD",
        "current_price": Decimal("100.00"),
        "current_price_net": Decimal("81.30"),
        "current_price_source": "csv_import",
        "cost": Decimal("60.00"),
        "floor": Decimal("70.00"),
        "baseline": Decimal("90.00"),
        "observations": [],
        "quote_config_rows": [quote_config()],
        "strategy": "compete",
        "mode": "suggestion",
        "price_war": False,
        "now": NOW,
        "staleness_days": 3,
        "estimator": "min",
    }
    defaults.update(overrides)
    return EngineInput(**defaults)


class TestEstimator:
    def test_min(self):
        assert estimate_reference_price([Decimal("10"), Decimal("5"), Decimal("8")], "min") == Decimal("5")

    def test_second_best_multiple(self):
        assert estimate_reference_price([Decimal("10"), Decimal("5"), Decimal("8")], "second_best") == Decimal("8")

    def test_second_best_single_falls_back_to_min(self):
        assert estimate_reference_price([Decimal("10")], "second_best") == Decimal("10")

    def test_median_odd(self):
        assert estimate_reference_price([Decimal("1"), Decimal("3"), Decimal("2")], "median") == Decimal("2")

    def test_median_even_takes_lower_middle(self):
        assert estimate_reference_price([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")], "median") == Decimal(
            "2"
        )


class TestObservationFilters:
    def test_stale_dropped(self):
        inp = engine_input(observations=[obs(50, ts=NOW - timedelta(days=10))])
        result = compute_decision(inp)
        assert result.observations[0].flag == "stale"
        assert result.recommendation == Recommendation.HOLD

    def test_untrusted_dropped(self):
        inp = engine_input(observations=[obs(50, trusted=False)])
        result = compute_decision(inp)
        assert result.observations[0].flag == "untrusted"

    def test_oos_dropped(self):
        inp = engine_input(observations=[obs(50, stock=0)])
        result = compute_decision(inp)
        assert result.observations[0].flag == "oos"

    def test_missing_stock_key_counts_as_valid(self):
        inp = engine_input(observations=[obs(50, stock=None)])
        result = compute_decision(inp)
        assert result.observations[0].flag == "valid"

    def test_currency_mismatch_dropped(self):
        inp = engine_input(observations=[obs(50, currency="EUR")], currency="USD")
        result = compute_decision(inp)
        assert result.observations[0].flag == "currency_mismatch"

    def test_country_scoped_source_from_other_market_excluded_from_view(self):
        inp = engine_input(country="DE", observations=[obs(50, country="FR")])
        result = compute_decision(inp)
        assert result.observations == []

    def test_global_source_included(self):
        inp = engine_input(country="DE", observations=[obs(50, country=None)])
        result = compute_decision(inp)
        assert result.observations[0].flag == "valid"


class TestNoComp:
    def test_pricefighter_source_reverts_to_baseline(self):
        inp = engine_input(current_price_source="pricefighter", baseline=Decimal("90.00"), observations=[])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.REVERT_BASELINE
        assert result.suggested_price == Decimal("90.00")
        assert result.reason == "no_competitor"

    def test_pricefighter_source_no_baseline_holds(self):
        inp = engine_input(current_price_source="pricefighter", baseline=None, observations=[])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "no_baseline"

    def test_other_source_holds(self):
        inp = engine_input(current_price_source="csv_import", observations=[])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.suggested_price == inp.current_price
        assert result.reason == "no_competitor"

    def test_stale_only_reports_stale_reason(self):
        inp = engine_input(current_price_source="csv_import", observations=[obs(50, ts=NOW - timedelta(days=10))])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "stale"


class TestGapAndHysteresis:
    def test_deep_compete_below_band(self):
        inp = engine_input(baseline=Decimal("90.00"), observations=[obs(80)])  # gap = 80-90 = -10 < -3
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.COMPETE
        assert result.suggested_price == Decimal("79.00")  # R - undercut

    def test_raise_above_band(self):
        inp = engine_input(baseline=Decimal("90.00"), strategy="raise", observations=[obs(100)])  # gap=10>3
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.RAISE
        assert result.suggested_price == Decimal("99.00")  # R - headroom

    def test_in_band_holds(self):
        inp = engine_input(baseline=Decimal("90.00"), observations=[obs(91)])  # gap=1, within +-3
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.suggested_price == inp.current_price
        assert result.reason == "in_band"

    def test_strategy_hold_forces_hold_even_with_deep_gap(self):
        inp = engine_input(baseline=Decimal("90.00"), strategy="hold", observations=[obs(80)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "strategy_scope"

    def test_compete_strategy_suppresses_raise_side(self):
        inp = engine_input(baseline=Decimal("90.00"), strategy="compete", observations=[obs(100)])  # would RAISE
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "strategy_scope"

    def test_raise_strategy_suppresses_compete_side(self):
        inp = engine_input(baseline=Decimal("90.00"), strategy="raise", observations=[obs(80)])  # would COMPETE
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "strategy_scope"


class TestRoundingAndClamps:
    def test_rounding_dot99(self):
        cfg = quote_config(rounding=".99")
        inp = engine_input(baseline=Decimal("90.00"), quote_config_rows=[cfg], observations=[obs(80)])
        result = compute_decision(inp)
        assert result.suggested_price == Decimal("79.99")  # R-undercut=79 -> floor(79)=79 -> 79.99

    def test_rounding_int(self):
        cfg = quote_config(rounding="int")
        inp = engine_input(baseline=Decimal("90.00"), quote_config_rows=[cfg], observations=[obs(80.4)])
        result = compute_decision(inp)
        assert result.suggested_price == Decimal("79")

    def test_clamp_to_floor(self):
        inp = engine_input(baseline=Decimal("90.00"), floor=Decimal("85.00"), observations=[obs(80)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.COMPETE
        assert result.suggested_price == Decimal("85.00")
        assert result.clamped_floor is True

    def test_max_step_limits_move(self):
        cfg = quote_config(max_step=Decimal("5.00"))
        inp = engine_input(
            baseline=Decimal("90.00"),
            current_price=Decimal("100.00"),
            floor=Decimal("1.00"),
            quote_config_rows=[cfg],
            observations=[obs(50)],
        )
        result = compute_decision(inp)
        assert result.suggested_price == Decimal("95.00")
        assert result.clamped_step is True


class TestPriceWar:
    def test_price_war_holds_at_floor_on_deep_compete(self):
        inp = engine_input(baseline=Decimal("90.00"), floor=Decimal("70.00"), price_war=True, observations=[obs(50)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD_AT_FLOOR
        assert result.suggested_price == Decimal("70.00")
        assert result.reason == "price_war"

    def test_price_war_no_floor_holds(self):
        inp = engine_input(baseline=Decimal("90.00"), floor=None, price_war=True, observations=[obs(50)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "price_war_no_floor"


class TestMissingConfig:
    def test_no_cost_means_no_recommendation(self):
        inp = engine_input(baseline=None, observations=[obs(80)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.NO_RECOMMENDATION
        assert result.suggested_price is None
        assert result.reason == "no_cost"
        assert result.reference_price == Decimal("80")

    def test_missing_quote_config_row_holds(self):
        cfg = quote_config(range_from=Decimal("1000.00"), range_to=None)  # R=80 falls outside
        inp = engine_input(baseline=Decimal("90.00"), quote_config_rows=[cfg], observations=[obs(80)])
        result = compute_decision(inp)
        assert result.recommendation == Recommendation.HOLD
        assert result.reason == "no_quote_config"


@pytest.mark.parametrize("estimator", ["min", "second_best", "median"])
def test_full_observation_list_always_included_even_when_filtered(estimator):
    inp = engine_input(
        estimator=estimator,
        observations=[obs(80, idx="a"), obs(60, trusted=False, idx="b"), obs(999, stock=0, idx="c")],
    )
    result = compute_decision(inp)
    assert len(result.observations) == 3
    assert {o.source_idx for o in result.observations} == {"a", "b", "c"}
