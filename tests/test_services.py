# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Service-layer tests for django-pricefighter."""

import sys
from unittest.mock import patch

import pytest

from django_pricefighter.models import Channel, PricingRule, ProductRepresentation
from django_pricefighter.services import channel_sync_service, representation_sync_service, rule_resolver

# ---------------------------------------------------------------------------
# channel_sync_service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_channels_from_pim_creates_and_updates(pim_channel_factory, language):
    pim_channel = pim_channel_factory("default-europe", name="Default Europe")
    pim_channel.languages.add(language)

    count = channel_sync_service.sync_channels_from_pim()
    assert count == 1

    channel = Channel.objects.get(idx="default-europe")
    assert channel.name == "Default Europe"
    assert channel.default_language.iso2 == "en"
    assert list(channel.languages.values_list("iso2", flat=True)) == ["en"]

    pim_channel.name = "Renamed"
    pim_channel.save(update_fields=["name"])

    count = channel_sync_service.sync_channels_from_pim()
    assert count == 1
    channel.refresh_from_db()
    assert channel.name == "Renamed"
    assert Channel.objects.count() == 1


@pytest.mark.django_db
def test_sync_channels_from_pim_noop_without_pim():
    with patch.dict(sys.modules, {"django_pim": None, "django_pim.models": None}):
        count = channel_sync_service.sync_channels_from_pim()
    assert count == 0
    assert Channel.objects.count() == 0


# ---------------------------------------------------------------------------
# representation_sync_service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_pair_creates_representation_with_denorm(
    pim_channel_factory, pf_channel_factory, pim_product_factory, language
):
    pim_channel = pim_channel_factory("default-europe")
    pf_channel = pf_channel_factory("default-europe", default_language=language)
    product = pim_product_factory("ENT-S001", pim_channel)

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")

    assert result is not None
    assert result.sku == "ENT-S001"
    assert result.channel == pf_channel
    assert result.is_active is True
    assert result.name == product.real_product.sku  # no name attribute set -> falls back to sku


@pytest.mark.django_db
def test_sync_pair_idempotent(pim_channel_factory, pf_channel_factory, pim_product_factory, language):
    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    pim_product_factory("ENT-S001", pim_channel)

    representation_sync_service.sync_pair("ENT-S001", "default-europe")
    representation_sync_service.sync_pair("ENT-S001", "default-europe")

    assert ProductRepresentation.objects.filter(sku="ENT-S001").count() == 1


@pytest.mark.django_db
def test_sync_pair_deactivates_deleted_product(pim_channel_factory, pf_channel_factory, pim_product_factory, language):
    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    product = pim_product_factory("ENT-S001", pim_channel)

    representation_sync_service.sync_pair("ENT-S001", "default-europe")
    product.delete()

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")

    assert result is not None
    assert result.is_active is False


@pytest.mark.django_db
def test_sync_pair_noop_without_pim(pf_channel_factory, language):
    pf_channel_factory("default-europe", default_language=language)

    with patch.dict(sys.modules, {"django_pim": None, "django_pim.models": None}):
        result = representation_sync_service.sync_pair("ENT-S001", "default-europe")

    assert result is None
    assert ProductRepresentation.objects.count() == 0


@pytest.mark.django_db
def test_sync_pair_denorm_name_uses_channel_language(pim_channel_factory, pf_channel_factory, pim_product_factory):
    from django_pim.models import Feature, FeatureScopeEnum, FeatureTypeEnum, ProductAttribute
    from django_regional.models.language import Language

    lang_pl, _ = Language.objects.get_or_create(
        iso2="pl", defaults={"iso3": "pol", "name_en": "Polish", "name_pl": "polski"}
    )
    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=lang_pl)
    product = pim_product_factory("ENT-S001", pim_channel)
    name_feature = Feature.objects.create(
        idx="name", scope=FeatureScopeEnum.SYSTEM, feature_type=FeatureTypeEnum.VARCHAR255_T9N
    )
    ProductAttribute.objects.create(
        product=product, feature=name_feature, value_txt_t9n={"en": "Sofa Deluxe", "pl": "Kanapa Deluxe"}
    )

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")

    assert result.name == "Kanapa Deluxe"


@pytest.mark.django_db
def test_sync_pair_denorm_category(
    pim_channel_factory, pf_channel_factory, pim_product_factory, pim_category_factory, language
):
    from django_pim.models.product_in_category import ProductInCategory

    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    product = pim_product_factory("ENT-S001", pim_channel)
    category = pim_category_factory(pim_channel, "sofas")
    ProductInCategory.objects.create(product=product, category=category, position=0)

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")
    assert result.category == "sofas"


@pytest.mark.django_db
def test_sync_pair_denorm_category_picks_lowest_position(
    pim_channel_factory, pf_channel_factory, pim_product_factory, pim_category_factory, language
):
    from django_pim.models.product_in_category import ProductInCategory

    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    product = pim_product_factory("ENT-S001", pim_channel)
    sofas = pim_category_factory(pim_channel, "sofas")
    living_room = pim_category_factory(pim_channel, "living-room")
    ProductInCategory.objects.create(product=product, category=living_room, position=1)
    ProductInCategory.objects.create(product=product, category=sofas, position=0)

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")
    assert result.category == "sofas"


@pytest.mark.django_db
def test_sync_pair_unknown_local_channel_skips(pim_channel_factory, pim_product_factory):
    pim_channel = pim_channel_factory("default-europe")
    pim_product_factory("ENT-S001", pim_channel)

    result = representation_sync_service.sync_pair("ENT-S001", "default-europe")
    assert result is None
    assert ProductRepresentation.objects.count() == 0


@pytest.mark.django_db
def test_full_sync_upserts_and_deactivates_stale(
    pim_channel_factory, pf_channel_factory, pim_product_factory, language
):
    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    pim_product_factory("ENT-S001", pim_channel)
    pim_product_factory("ENT-S002", pim_channel)

    result = representation_sync_service.full_sync()
    assert result["synced"] == 2
    assert ProductRepresentation.objects.filter(is_active=True).count() == 2

    ProductRepresentation.objects.filter(sku="ENT-S002").first()
    from django_pim.models.product import Product

    Product.objects.filter(real_product__sku="ENT-S002").delete()

    result = representation_sync_service.full_sync()
    assert result["synced"] == 1
    assert result["deactivated"] == 1
    stale = ProductRepresentation.objects.get(sku="ENT-S002")
    assert stale.is_active is False


@pytest.mark.django_db
def test_full_sync_noop_without_pim():
    with patch.dict(sys.modules, {"django_pim": None, "django_pim.models": None}):
        result = representation_sync_service.full_sync()

    assert result == {"synced": 0, "deactivated": 0, "failed": 0}


@pytest.mark.django_db
def test_full_sync_failed_product_does_not_abort_or_deactivate(
    pim_channel_factory, pf_channel_factory, pim_product_factory, language
):
    """A product that raises during upsert is skipped (not aborting the reconcile) and is
    still treated as "seen" so it is not wrongly deactivated by the same run."""
    pim_channel = pim_channel_factory("default-europe")
    pf_channel_factory("default-europe", default_language=language)
    pim_product_factory("ENT-S001", pim_channel)
    pim_product_factory("ENT-S002", pim_channel)

    original_upsert = representation_sync_service._upsert_representation

    def _flaky_upsert(sku, channel, product):
        if sku == "ENT-S001":
            raise RuntimeError("boom")
        return original_upsert(sku, channel, product)

    with patch("django_pricefighter.services.representation_sync_service._upsert_representation", _flaky_upsert):
        result = representation_sync_service.full_sync()

    assert result["synced"] == 1
    assert result["failed"] == 1
    assert result["deactivated"] == 0
    assert ProductRepresentation.objects.filter(sku="ENT-S002", is_active=True).exists()
    assert not ProductRepresentation.objects.filter(sku="ENT-S001").exists()


# ---------------------------------------------------------------------------
# rule_resolver
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_resolve_default_when_no_rule():
    channel = Channel.objects.create(idx="default-europe")
    result = rule_resolver.resolve("ENT-S001", "sofas", channel)
    assert result == rule_resolver.DEFAULT_RESOLVED_RULE
    assert result.strategy == PricingRule.Strategy.HOLD
    assert result.mode == PricingRule.Mode.SUGGESTION
    assert result.price_war is False
    assert result.rule_id is None


@pytest.mark.django_db
def test_resolve_channel_scope():
    channel = Channel.objects.create(idx="default-europe")
    rule = PricingRule.objects.create(channel=channel, strategy=PricingRule.Strategy.COMPETE)
    result = rule_resolver.resolve("ENT-S001", "sofas", channel)
    assert result.strategy == PricingRule.Strategy.COMPETE
    assert result.rule_id == rule.pk


@pytest.mark.django_db
def test_resolve_category_beats_channel():
    channel = Channel.objects.create(idx="default-europe")
    PricingRule.objects.create(channel=channel, strategy=PricingRule.Strategy.COMPETE)
    category_rule = PricingRule.objects.create(category_idx="sofas", strategy=PricingRule.Strategy.HOLD)

    result = rule_resolver.resolve("ENT-S001", "sofas", channel)
    assert result.strategy == PricingRule.Strategy.HOLD
    assert result.rule_id == category_rule.pk


@pytest.mark.django_db
def test_resolve_sku_beats_category_and_channel():
    channel = Channel.objects.create(idx="default-europe")
    PricingRule.objects.create(channel=channel, strategy=PricingRule.Strategy.COMPETE)
    PricingRule.objects.create(category_idx="sofas", strategy=PricingRule.Strategy.HOLD)
    sku_rule = PricingRule.objects.create(sku="ENT-S002", strategy=PricingRule.Strategy.RAISE)

    result = rule_resolver.resolve("ENT-S002", "sofas", channel)
    assert result.strategy == PricingRule.Strategy.RAISE
    assert result.rule_id == sku_rule.pk


@pytest.mark.django_db
def test_resolve_sku_lookup_is_case_insensitive():
    rule = PricingRule.objects.create(sku="ENT-S002", strategy=PricingRule.Strategy.RAISE)
    result = rule_resolver.resolve("ent-s002", None, None)
    assert result.rule_id == rule.pk


@pytest.mark.django_db
def test_resolve_tie_break_deterministic_by_pk():
    first = PricingRule.objects.create(category_idx="sofas", strategy=PricingRule.Strategy.HOLD)
    PricingRule.objects.create(category_idx="sofas", strategy=PricingRule.Strategy.RAISE)

    result = rule_resolver.resolve(None, "sofas", None)
    assert result.rule_id == first.pk
    assert result.strategy == PricingRule.Strategy.HOLD


@pytest.mark.django_db
def test_resolve_tie_break_deterministic_by_pk_sku_scope():
    first = PricingRule.objects.create(sku="ENT-S002", strategy=PricingRule.Strategy.HOLD)
    PricingRule.objects.create(sku="ENT-S002", strategy=PricingRule.Strategy.RAISE)

    result = rule_resolver.resolve("ENT-S002", None, None)
    assert result.rule_id == first.pk
    assert result.strategy == PricingRule.Strategy.HOLD


@pytest.mark.django_db
def test_resolve_tie_break_deterministic_by_pk_channel_scope():
    channel = Channel.objects.create(idx="default-europe")
    first = PricingRule.objects.create(channel=channel, strategy=PricingRule.Strategy.HOLD)
    PricingRule.objects.create(channel=channel, strategy=PricingRule.Strategy.RAISE)

    result = rule_resolver.resolve(None, None, channel)
    assert result.rule_id == first.pk
    assert result.strategy == PricingRule.Strategy.HOLD


@pytest.mark.django_db
def test_resolve_price_war_flag_propagates():
    rule = PricingRule.objects.create(sku="ENT-D001", strategy=PricingRule.Strategy.COMPETE, price_war=True)
    result = rule_resolver.resolve("ENT-D001", None, None)
    assert result.price_war is True
    assert result.rule_id == rule.pk
