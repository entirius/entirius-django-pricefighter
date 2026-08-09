# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Model-level tests for django-pricefighter."""

import os
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction

from django_pricefighter.models import Channel, PricingRule, ProductRepresentation, QuoteConfig


@pytest.mark.django_db
def test_channel_str():
    channel = Channel.objects.create(idx="default-europe", name="Default Europe")
    assert str(channel) == "default-europe"
    assert channel.created_at is not None
    assert channel.modified_at is not None


@pytest.mark.django_db
def test_product_representation_unique_sku_case_insensitive_per_channel():
    channel = Channel.objects.create(idx="default-europe", name="Default Europe")
    ProductRepresentation.objects.create(sku="ENT-S001", channel=channel)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductRepresentation.objects.create(sku="ent-s001", channel=channel)


@pytest.mark.django_db
def test_product_representation_same_sku_different_channel_allowed():
    channel_a = Channel.objects.create(idx="default-local", name="Default Local")
    channel_b = Channel.objects.create(idx="default-europe", name="Default Europe")

    ProductRepresentation.objects.create(sku="ENT-S001", channel=channel_a)
    ProductRepresentation.objects.create(sku="ENT-S001", channel=channel_b)

    assert ProductRepresentation.objects.count() == 2


@pytest.mark.django_db
def test_product_representation_defaults():
    channel = Channel.objects.create(idx="default-europe", name="Default Europe")
    pr = ProductRepresentation.objects.create(sku="ENT-S001", channel=channel)
    assert pr.is_active is True
    assert pr.name == ""
    assert pr.category == ""


# ---------------------------------------------------------------------------
# PricingRule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pricing_rule_sku_scope_valid():
    rule = PricingRule(sku="ENT-S001", strategy=PricingRule.Strategy.RAISE)
    rule.full_clean()
    rule.save()
    assert str(rule) == "ENT-S001 → raise"


@pytest.mark.django_db
def test_pricing_rule_category_scope_valid():
    rule = PricingRule(category_idx="sofas", strategy=PricingRule.Strategy.HOLD)
    rule.full_clean()
    rule.save()
    assert rule.pk is not None


@pytest.mark.django_db
def test_pricing_rule_channel_scope_valid():
    channel = Channel.objects.create(idx="default-europe")
    rule = PricingRule(channel=channel, strategy=PricingRule.Strategy.COMPETE)
    rule.full_clean()
    rule.save()
    assert rule.pk is not None


@pytest.mark.django_db
def test_pricing_rule_no_scope_rejected():
    rule = PricingRule(strategy=PricingRule.Strategy.HOLD)
    with pytest.raises(ValidationError):
        rule.full_clean()


@pytest.mark.django_db
def test_pricing_rule_two_scopes_rejected():
    channel = Channel.objects.create(idx="default-europe")
    rule = PricingRule(sku="ENT-S001", channel=channel, strategy=PricingRule.Strategy.HOLD)
    with pytest.raises(ValidationError):
        rule.full_clean()


@pytest.mark.django_db
def test_pricing_rule_check_constraint_at_db_level():
    """Bypassing clean() (bulk path) still hits the CheckConstraint."""
    with pytest.raises(IntegrityError), transaction.atomic():
        PricingRule.objects.create(strategy=PricingRule.Strategy.HOLD)


# ---------------------------------------------------------------------------
# QuoteConfig
# ---------------------------------------------------------------------------


def _quote_config(**overrides):
    defaults = {
        "currency": "PLN",
        "range_from": Decimal("0"),
        "range_to": Decimal("50"),
        "band_dn": Decimal("2.00"),
        "band_up": Decimal("2.00"),
        "undercut": Decimal("1.00"),
        "headroom": Decimal("1.00"),
        "max_step": Decimal("5"),
        "rounding": QuoteConfig.Rounding.P99,
    }
    defaults.update(overrides)
    return QuoteConfig(**defaults)


@pytest.mark.django_db
def test_quote_config_valid_row_passes():
    qc = _quote_config()
    qc.full_clean()
    qc.save()
    assert qc.pk is not None
    assert str(qc) == "PLN 0-50"


@pytest.mark.django_db
def test_quote_config_open_ended_range_str():
    qc = _quote_config(range_from=Decimal("200"), range_to=None)
    qc.full_clean()
    qc.save()
    assert str(qc) == "PLN 200-∞"


@pytest.mark.django_db
def test_quote_config_band_dn_must_exceed_undercut():
    qc = _quote_config(band_dn=Decimal("1.00"), undercut=Decimal("1.00"))
    with pytest.raises(ValidationError):
        qc.full_clean()


@pytest.mark.django_db
def test_quote_config_band_up_must_exceed_undercut():
    qc = _quote_config(band_up=Decimal("0.50"), undercut=Decimal("1.00"))
    with pytest.raises(ValidationError):
        qc.full_clean()


@pytest.mark.django_db
def test_quote_config_rounding_grain_must_not_exceed_undercut():
    qc = _quote_config(
        undercut=Decimal("0.50"), band_dn=Decimal("1.00"), band_up=Decimal("1.00"), rounding=QuoteConfig.Rounding.P99
    )
    with pytest.raises(ValidationError):
        qc.full_clean()


@pytest.mark.django_db
def test_quote_config_rounding_none_has_zero_grain():
    qc = _quote_config(
        undercut=Decimal("0.10"), band_dn=Decimal("0.50"), band_up=Decimal("0.50"), rounding=QuoteConfig.Rounding.NONE
    )
    qc.full_clean()  # must not raise


@pytest.mark.django_db
def test_quote_config_overlapping_ranges_rejected():
    _quote_config(range_from=Decimal("0"), range_to=Decimal("50")).save()
    overlapping = _quote_config(range_from=Decimal("40"), range_to=Decimal("100"))
    with pytest.raises(ValidationError):
        overlapping.full_clean()


@pytest.mark.django_db
def test_quote_config_gap_between_ranges_rejected():
    _quote_config(range_from=Decimal("0"), range_to=Decimal("50")).save()
    gapped = _quote_config(range_from=Decimal("60"), range_to=Decimal("200"))
    with pytest.raises(ValidationError):
        gapped.full_clean()


@pytest.mark.django_db
def test_quote_config_multiple_open_ended_rejected():
    _quote_config(range_from=Decimal("0"), range_to=None).save()
    second_open = _quote_config(range_from=Decimal("50"), range_to=None)
    with pytest.raises(ValidationError):
        second_open.full_clean()


@pytest.mark.django_db
def test_quote_config_contiguous_three_range_set_passes():
    _quote_config(range_from=Decimal("0"), range_to=Decimal("50")).save()
    _quote_config(range_from=Decimal("50"), range_to=Decimal("200")).save()
    third = _quote_config(range_from=Decimal("200"), range_to=None)
    third.full_clean()  # must not raise
    third.save()
    assert QuoteConfig.objects.filter(currency="PLN").count() == 3


@pytest.mark.django_db
def test_quote_config_different_currency_does_not_conflict():
    _quote_config(currency="PLN", range_from=Decimal("0"), range_to=Decimal("50")).save()
    other_currency = _quote_config(currency="USD", range_from=Decimal("0"), range_to=Decimal("15"))
    other_currency.full_clean()  # must not raise
    other_currency.save()


# ---------------------------------------------------------------------------
# Seed fixture sanity (entirius-test-package/fixtures/django_pricefighter.cfg.yaml)
# ---------------------------------------------------------------------------

_SEED_FIXTURE = os.environ.get("PRICEFIGHTER_SEED_FIXTURE", "")


@pytest.mark.skipif(
    not _SEED_FIXTURE or not os.path.exists(_SEED_FIXTURE),
    reason="seed fixture path not provided (PRICEFIGHTER_SEED_FIXTURE)",
)
@pytest.mark.django_db
def test_seed_fixture_rows_pass_full_clean():
    """loaddata bypasses Model.clean() — prove the seed values are actually valid."""
    from django_regional.models import Language

    # default_language=2 in the fixture points at the real seed's "en" Language row —
    # this module's own test DB has no regional seed data, so pre-create it at that pk.
    Language.objects.get_or_create(
        pk=2, defaults={"iso2": "en", "iso3": "eng", "name_en": "English", "name_pl": "angielski"}
    )

    call_command("loaddata", "--format=yaml", _SEED_FIXTURE, verbosity=0)

    assert Channel.objects.count() == 2
    assert QuoteConfig.objects.count() == 9
    assert PricingRule.objects.count() == 5

    for rule in PricingRule.objects.all():
        rule.full_clean()
    for qc in QuoteConfig.objects.all():
        qc.full_clean()
