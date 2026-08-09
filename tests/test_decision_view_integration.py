# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Integration tests for the decision view pipeline: market_service,
engine_inputs, decision_view_service against a real DB — pre-filter, sort, pagination,
constant query count, zero side-effects on render.
"""

from decimal import Decimal

import pytest
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestMarketService:
    def test_get_markets_reflects_current_price_rows(self, decision_fixture):
        from django_pricefighter.services.market_service import get_markets

        markets = get_markets()
        assert {"channel_idx": "ch1", "country": "DE", "currency": "USD"} in [
            {"channel_idx": m.channel_idx, "country": m.country, "currency": m.currency} for m in markets
        ]

    def test_candidate_skus_prefilters_to_observed_skus(self, decision_fixture):
        from django_pricefighter.services.market_service import get_candidate_skus

        assert get_candidate_skus() == {"SKU-A"}


class TestDecisionViewService:
    def test_default_prefilter_excludes_sku_without_observations(self, decision_fixture):
        from django_pricefighter.services.decision_view_service import build_decision_rows

        rows, total = build_decision_rows()
        assert total == 1
        assert rows[0].decision.sku == "SKU-A"

    def test_explicit_skus_bypasses_prefilter(self, decision_fixture):
        from django_pricefighter.services.decision_view_service import build_decision_rows

        rows, total = build_decision_rows(skus=["SKU-A", "SKU-B"])
        assert total == 2
        skus = {r.decision.sku for r in rows}
        assert skus == {"SKU-A", "SKU-B"}

    def test_row_shape_includes_name_and_margin(self, decision_fixture):
        from django_pricefighter.services.decision_view_service import build_decision_rows

        rows, _ = build_decision_rows(skus=["SKU-A"])
        row = rows[0]
        assert row.name == "Product SKU-A"
        assert row.margin is not None  # (net - cost) / net * 100

    def test_pagination_limit_offset(self, decision_fixture):
        from django_pricefighter.services.decision_view_service import build_decision_rows

        rows, total = build_decision_rows(skus=["SKU-A", "SKU-B"], offset=1, limit=1)
        assert total == 2
        assert len(rows) == 1

    def test_render_writes_nothing(self, decision_fixture):
        from django_pricemanager.models import CurrentPrice

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.decision_view_service import build_decision_rows

        before = CurrentPrice.objects.count()
        build_decision_rows(skus=["SKU-A", "SKU-B"])
        assert CurrentPrice.objects.count() == before
        assert PriceDecision.objects.count() == 0

    def test_sort_gap_desc_orders_rows(self, decision_fixture):
        from django_atlas.services.observation_service import record_observation

        from django_pricefighter.services.decision_view_service import build_decision_rows

        # SKU-A (fixture): baseline 85.68, observation 80.00 -> gap_baseline = -5.68 (COMPETE side)
        # SKU-C: cheaper cost -> baseline 42.84, observation 50.00 -> gap_baseline = +7.16 (RAISE side)
        decision_fixture.make_sku("SKU-C", cost=Decimal("30.00"))
        record_observation(source=decision_fixture.source, sku="SKU-C", value={"price": "50.00", "currency": "USD"})

        rows, total = build_decision_rows(skus=["SKU-A", "SKU-C"])
        assert total == 2
        gaps = [r.decision.gap_baseline for r in rows]
        assert gaps == sorted(gaps, reverse=True)
        assert rows[0].decision.sku == "SKU-C"


class TestEngineInputsQueryCount:
    def test_constant_query_count_regardless_of_sku_count(self, decision_fixture):
        from django_pricefighter.services import engine_inputs, market_service

        markets = market_service.get_markets()
        now = timezone.now()

        reset_queries()
        with CaptureQueriesContext(connection) as small:
            engine_inputs.build_engine_inputs(["SKU-A", "SKU-B"], markets, now=now, staleness_days=3, estimator="min")

        many_skus = ["SKU-A", "SKU-B"] + [f"SKU-{i}" for i in range(18)]
        for sku in many_skus[2:]:
            decision_fixture.make_sku(sku)

        with CaptureQueriesContext(connection) as big:
            engine_inputs.build_engine_inputs(many_skus, markets, now=now, staleness_days=3, estimator="min")

        # Absolute cap catches a regression that scales with batch size but happens to match between small/big.
        assert len(small.captured_queries) <= 18
        assert len(small.captured_queries) == len(big.captured_queries)
