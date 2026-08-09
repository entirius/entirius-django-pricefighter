# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""apply_service integration tests — single apply, stale rejection, precedence
lock, MAP clamp, batch best-effort, PriceDecision snapshot."""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _preview(sku="SKU-A", channel_idx="ch1", country="DE", currency="USD"):
    from django_pricefighter.services.decision_view_service import build_decision_rows

    rows, _ = build_decision_rows(skus=[sku])
    row = next(r for r in rows if r.decision.channel_idx == channel_idx and r.decision.country == country)
    return row.decision


def _allow_compete(sku="SKU-A"):
    """No PricingRule -> DEFAULT_RESOLVED_RULE.strategy=HOLD — a sku-scoped compete rule is
    needed for the deep-gap scenarios below to actually reach the COMPETE side."""
    from django_pricefighter.models import PricingRule

    return PricingRule.objects.create(strategy=PricingRule.Strategy.COMPETE, sku=sku)


class TestApplySingle:
    def test_applies_and_logs_decision(self, decision_fixture, regular_user):
        from django_pricemanager.models import CurrentPrice, PriceHistory

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        _allow_compete()
        decision = _preview()
        assert decision.recommendation == "compete"

        item = ApplyItem(
            sku="SKU-A", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        result = apply_single(item, user=regular_user)

        assert result.bucket == "applied"
        cp = CurrentPrice.objects.get(
            product__sku="SKU-A", channel__idx="ch1", country__iso2="DE", customer_representation__isnull=True
        )
        assert cp.gross_value == decision.suggested_price
        assert cp.source == "pricefighter"
        assert PriceHistory.objects.filter(product__sku="SKU-A", source="pricefighter").exists()

        pd = PriceDecision.objects.get(representation__sku="SKU-A")
        assert pd.strategy == PriceDecision.Strategy.COMPETE
        assert pd.new_price == decision.suggested_price
        assert pd.old_price == decision.current_price
        assert pd.reason["reference_price"] == str(decision.reference_price)
        assert pd.applied_by_id == regular_user.id

    def test_country_scoped_write_does_not_touch_other_country(self, decision_fixture):
        from django_pricemanager.models import Channel as PmChannel
        from django_pricemanager.models import CurrentPrice, TaxRate

        # add a second country (FR) with the same price, untouched by the DE-scoped apply
        from django_regional.models import Country

        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        fr = Country.objects.filter(iso2__iexact="FR").first()
        if fr is None:
            Country.objects.bulk_create(
                [Country(iso2="FR", iso3="FRA", name_en="France", name_pl="Francja", prefix="")]
            )
            fr = Country.objects.get(iso2="FR")
        pm_channel = PmChannel.objects.get(idx="ch1")
        pm_channel.calculate_countries.add(fr)
        tax_rate_fr = TaxRate.objects.create(tax_class=decision_fixture.tax_class, country=fr, rate=Decimal("0.2000"))
        cp_fr = CurrentPrice.objects.create(
            product=decision_fixture.sku_a,
            channel=pm_channel,
            country=fr,
            currency=decision_fixture.usd,
            tax_rate=tax_rate_fr,
            net_value=Decimal("83.33"),
            gross_value=Decimal("100.00"),
            source="csv_import",
        )

        _allow_compete()
        decision = _preview()
        item = ApplyItem(
            sku="SKU-A", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        apply_single(item)

        cp_fr.refresh_from_db()
        assert cp_fr.gross_value == Decimal("100.00")
        assert cp_fr.source == "csv_import"

    def test_stale_preview_rejected_with_zero_write(self, decision_fixture):
        from django_pricemanager.models import CurrentPrice

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        _allow_compete()
        before = CurrentPrice.objects.get(product__sku="SKU-A", country__iso2="DE").gross_value
        item = ApplyItem(
            sku="SKU-A",
            channel_idx="ch1",
            country="DE",
            currency="USD",
            expected_new_price=Decimal("1.23"),  # doesn't match the freshly-recomputed suggestion
        )
        result = apply_single(item)

        assert result.bucket == "stale"
        after = CurrentPrice.objects.get(product__sku="SKU-A", country__iso2="DE").gross_value
        assert after == before
        assert PriceDecision.objects.count() == 0

    def test_admin_edit_lock_is_skipped(self, decision_fixture):
        from django_pricemanager.models import CurrentPrice
        from django_pricemanager.services.price_edit_service import edit_price

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        edit_price(
            channel=decision_fixture.pm_channel,
            sku="SKU-A",
            value=Decimal("77.00"),
            country=decision_fixture.de,
            source="admin_edit",
        )
        before = CurrentPrice.objects.get(product__sku="SKU-A", country__iso2="DE").gross_value

        _allow_compete()
        decision = _preview()
        item = ApplyItem(
            sku="SKU-A", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        result = apply_single(item)

        assert result.bucket == "skipped"
        after = CurrentPrice.objects.get(product__sku="SKU-A", country__iso2="DE").gross_value
        assert after == before
        assert PriceDecision.objects.count() == 0

    def test_revert_below_map_is_clamped_at_write_time(self, decision_fixture):
        """revert_baseline is the one recommendation the engine does NOT pre-clamp to floor
        (the floor gate only applies to compete/raise targets) — so a baseline
        below MAP genuinely reaches edit_price's guard, which clamps it up to the floor."""
        from django_pricemanager.models.choices import PriceSource
        from django_pricemanager.models.price_bounds import PriceBoundsConfig
        from django_pricemanager.services.price_edit_service import edit_price

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        PriceBoundsConfig.objects.create(
            product=decision_fixture.sku_b, channel=decision_fixture.pm_channel, map_value=Decimal("90.00")
        )
        edit_price(
            channel=decision_fixture.pm_channel,
            sku="SKU-B",
            value=Decimal("70.00"),
            country=decision_fixture.de,
            source=PriceSource.PRICEFIGHTER,
        )

        decision = _preview(sku="SKU-B")
        assert decision.recommendation == "revert_baseline"
        assert decision.suggested_price < Decimal("90.00")  # baseline itself is below the MAP floor

        item = ApplyItem(
            sku="SKU-B", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        result = apply_single(item)

        assert result.bucket == "clamped"
        pd = PriceDecision.objects.get(representation__sku="SKU-B")
        assert pd.new_price == Decimal("90.00")

    def test_revert_baseline_writes_source_baseline(self, decision_fixture):
        from django_pricemanager.models import CurrentPrice
        from django_pricemanager.models.choices import PriceSource
        from django_pricemanager.services.price_edit_service import edit_price

        from django_pricefighter.models import PriceDecision
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        # SKU-B has no observations (NO_COMP) and is currently owned by pricefighter -> revert.
        edit_price(
            channel=decision_fixture.pm_channel,
            sku="SKU-B",
            value=Decimal("90.00"),
            country=decision_fixture.de,
            source=PriceSource.PRICEFIGHTER,
        )
        decision = _preview(sku="SKU-B")
        assert decision.recommendation == "revert_baseline"

        item = ApplyItem(
            sku="SKU-B", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        result = apply_single(item)

        assert result.bucket == "applied"
        cp = CurrentPrice.objects.get(product__sku="SKU-B", country__iso2="DE")
        assert cp.source == "baseline"
        pd = PriceDecision.objects.get(representation__sku="SKU-B")
        assert pd.strategy == PriceDecision.Strategy.REVERT_BASELINE

    def test_hold_recommendation_is_not_actionable(self, decision_fixture):
        from django_pricefighter.models import PricingRule
        from django_pricefighter.services.apply_service import ApplyItem, apply_single

        PricingRule.objects.create(strategy=PricingRule.Strategy.HOLD, channel=decision_fixture.pf_channel)
        decision = _preview()
        assert decision.recommendation == "hold"

        item = ApplyItem(
            sku="SKU-A", channel_idx="ch1", country="DE", currency="USD", expected_new_price=decision.suggested_price
        )
        result = apply_single(item)
        assert result.bucket == "skipped"
        assert result.reason.startswith("not_actionable")


class TestApplyBatch:
    def test_mixed_outcomes_in_one_report(self, decision_fixture):
        from django_pricefighter.services.apply_service import ApplyItem, apply_batch

        # SKU-A: normal apply -> applied
        _allow_compete()
        decision_a = _preview()
        # SKU-B: no observations, csv_import owned -> HOLD -> not actionable -> skipped
        decision_b = _preview(sku="SKU-B")
        # A ghost sku with a bogus expected price -> stale
        items = [
            ApplyItem(
                sku="SKU-A",
                channel_idx="ch1",
                country="DE",
                currency="USD",
                expected_new_price=decision_a.suggested_price,
            ),
            ApplyItem(
                sku="SKU-B",
                channel_idx="ch1",
                country="DE",
                currency="USD",
                expected_new_price=decision_b.current_price,
            ),
            ApplyItem(sku="SKU-A", channel_idx="ch1", country="DE", currency="USD", expected_new_price=Decimal("0.01")),
        ]
        report = apply_batch(items)

        assert len(report["applied"]) == 1
        assert len(report["skipped"]) == 1
        assert len(report["stale"]) == 1
        assert len(report["clamped"]) == 0
        assert len(report["failed"]) == 0
        assert report["stale"][0].item.expected_new_price == Decimal("0.01")

    def test_unexpected_exception_in_one_item_does_not_abort_the_batch(self, decision_fixture, monkeypatch):
        from django_pricefighter.services import apply_service
        from django_pricefighter.services.apply_service import ApplyItem

        _allow_compete()
        decision_a = _preview()

        original_apply_single = apply_service.apply_single

        def _boom_for_ghost_sku(item, *, user=None, policy_map=None):
            if item.sku == "SKU-GHOST":
                raise RuntimeError("unexpected failure e.g. IntegrityError")
            return original_apply_single(item, user=user, policy_map=policy_map)

        monkeypatch.setattr(apply_service, "apply_single", _boom_for_ghost_sku)

        items = [
            ApplyItem(
                sku="SKU-GHOST", channel_idx="ch1", country="DE", currency="USD", expected_new_price=Decimal("1.00")
            ),
            ApplyItem(
                sku="SKU-A",
                channel_idx="ch1",
                country="DE",
                currency="USD",
                expected_new_price=decision_a.suggested_price,
            ),
        ]
        report = apply_service.apply_batch(items)

        assert len(report["failed"]) == 1
        assert report["failed"][0].reason == "internal_error"
        assert len(report["applied"]) == 1


class TestRetentionBeat:
    def test_prune_deletes_only_stale_decisions(self, decision_fixture):
        from datetime import timedelta

        from django.utils import timezone

        from django_pricefighter.models import PriceDecision, ProductRepresentation
        from django_pricefighter.tasks import prune_decisions

        representation = ProductRepresentation.objects.get(sku="SKU-A", channel=decision_fixture.pf_channel)
        old = PriceDecision.objects.create(
            representation=representation,
            channel=decision_fixture.pf_channel,
            country="DE",
            currency="USD",
            old_price=Decimal("1"),
            new_price=Decimal("2"),
            strategy=PriceDecision.Strategy.COMPETE,
            mode="suggestion",
            reason={},
        )
        PriceDecision.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))

        fresh = PriceDecision.objects.create(
            representation=representation,
            channel=decision_fixture.pf_channel,
            country="DE",
            currency="USD",
            old_price=Decimal("1"),
            new_price=Decimal("2"),
            strategy=PriceDecision.Strategy.COMPETE,
            mode="suggestion",
            reason={},
        )

        deleted = prune_decisions()

        assert deleted == 1
        assert not PriceDecision.objects.filter(pk=old.pk).exists()
        assert PriceDecision.objects.filter(pk=fresh.pk).exists()
