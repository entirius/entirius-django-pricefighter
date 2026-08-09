# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django_regional.models.currency import Currency
from django_regional.models.language import Language
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(username="admin", email="admin@test.local", password="admin-pass")


@pytest.fixture
def regular_user(db) -> User:
    return User.objects.create_user(username="user", email="user@test.local", password="user-pass")


@pytest.fixture
def admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def regular_client(regular_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def language(db) -> Language:
    obj, _ = Language.objects.get_or_create(
        iso2="en", defaults={"iso3": "eng", "name_en": "English", "name_pl": "angielski"}
    )
    return obj


@pytest.fixture
def currency(db) -> Currency:
    obj, _ = Currency.objects.get_or_create(
        iso3="EUR", defaults={"name_en": "Euro", "name_pl": "Euro", "symbol": "EUR"}
    )
    return obj


@pytest.fixture
def pim_channel_factory(db, language, currency):
    """Factory callable returning a PIM Channel by idx."""
    from django_pim.models.channel import Channel

    def _make(idx: str, name: str | None = None):
        obj, _ = Channel.objects.get_or_create(
            idx=idx,
            defaults={"name": name or f"Channel {idx}", "default_language": language, "default_currency": currency},
        )
        return obj

    return _make


@pytest.fixture
def pf_channel_factory(db):
    """Factory callable returning a local pricefighter Channel by idx."""
    from django_pricefighter.models import Channel

    def _make(idx: str, name: str | None = None, default_language=None):
        obj, _ = Channel.objects.get_or_create(
            idx=idx, defaults={"name": name or f"Channel {idx}", "default_language": default_language}
        )
        return obj

    return _make


@pytest.fixture
def pim_product_factory(db):
    """Factory callable creating a full PIM Product (RealProduct + FeatureSet + Product)."""
    from django_pim.models.feature_set import FeatureSet
    from django_pim.models.product import Product
    from django_pim.models.real_product import RealProduct

    def _make(sku: str, channel):
        real_product, _ = RealProduct.objects.get_or_create(sku=sku)
        feature_set, _ = FeatureSet.objects.get_or_create(idx="pf-test-fs", defaults={"name": "PF Test FeatureSet"})
        return Product.objects.create(real_product=real_product, shop=channel, feature_set=feature_set)

    return _make


@pytest.fixture
def pim_category_factory(db):
    """Factory callable creating a PIM ProductCategory in a given channel."""
    from django_pim.models.product_category import ProductCategory

    def _make(channel, idx: str):
        obj, _ = ProductCategory.objects.get_or_create(
            shop=channel, idx=idx, defaults={"tree_deep": 0, "is_active": True}
        )
        return obj

    return _make


def _create_country(iso2, iso3, name_en, name_pl):
    """Bypass Country.save() guard (mirrors pricemanager's test helper)."""
    from django_regional.models import Country

    existing = Country.objects.filter(iso2=iso2).first()
    if existing:
        return existing
    country = Country(iso2=iso2, iso3=iso3, name_en=name_en, name_pl=name_pl, prefix="")
    Country.objects.bulk_create([country])
    return Country.objects.get(iso2=iso2)


@pytest.fixture
def decision_fixture(db, language, currency):
    """Cross-module graph for the decision-view/apply engine: one market
    (ch1/DE/USD), SKU-A with a valid monitoring observation, SKU-B with none."""
    from django_atlas.models import Source
    from django_atlas.services.observation_service import record_observation
    from django_pricemanager.models import Channel as PmChannel
    from django_pricemanager.models import CurrentPrice, PurchaseCost, TaxClass, TaxRate
    from django_pricemanager.models import ProductRepresentation as PmRep
    from django_pricemanager.models.baseline_config import BaselineConfig
    from django_pricemanager.models.price_bounds import PriceBoundsConfig
    from django_regional.models import Currency

    from django_pricefighter.models import Channel as PfChannel
    from django_pricefighter.models import ProductRepresentation as PfRep
    from django_pricefighter.models import QuoteConfig

    de = _create_country("DE", "DEU", "Germany", "Niemcy")
    usd, _ = Currency.objects.get_or_create(
        iso3="USD", defaults={"name_en": "US Dollar", "name_pl": "Dolar", "symbol": "$"}
    )

    pm_channel = PmChannel.objects.create(idx="ch1", name="Channel 1")
    pm_channel.calculate_countries.set([de])

    tax_class = TaxClass.objects.create(idx="standard", name="Standard")
    tax_rate = TaxRate.objects.create(tax_class=tax_class, country=de, rate=Decimal("0.1900"))
    BaselineConfig.objects.create(channel=pm_channel, markup_percent=Decimal("0.20"), rounding="none")
    PriceBoundsConfig.objects.create(product=None, channel=None, min_margin_percent=Decimal("0.05"))

    pf_channel = PfChannel.objects.create(idx="ch1", name="Channel 1")

    def _make_sku(
        sku: str, *, gross=Decimal("100.00"), net=Decimal("84.03"), cost=Decimal("60.00"), source="csv_import"
    ):
        pm_rep = PmRep.objects.create(sku=sku, tax_class=tax_class)
        PurchaseCost.objects.create(product=pm_rep, channel=pm_channel, country=de, currency=usd, net_cost=cost)
        CurrentPrice.objects.create(
            product=pm_rep,
            channel=pm_channel,
            country=de,
            currency=usd,
            tax_rate=tax_rate,
            net_value=net,
            gross_value=gross,
            source=source,
        )
        PfRep.objects.get_or_create(sku=sku, channel=pf_channel, defaults={"name": f"Product {sku}", "category": ""})
        return pm_rep

    sku_a = _make_sku("SKU-A")
    sku_b = _make_sku("SKU-B")

    QuoteConfig.objects.create(
        currency="USD",
        range_from=Decimal("0"),
        range_to=None,
        band_dn=Decimal("3.00"),
        band_up=Decimal("3.00"),
        undercut=Decimal("1.00"),
        headroom=Decimal("1.00"),
        max_step=Decimal("40.00"),
        rounding="none",
    )

    source = Source.objects.create(
        idx="mon-1",
        name="Monitor",
        kind="monitoring",
        default_language=language,
        default_currency=currency,
        is_trusted=True,
    )
    record_observation(source=source, sku="SKU-A", value={"price": "80.00", "currency": "USD"})

    return SimpleNamespace(
        de=de,
        usd=usd,
        tax_class=tax_class,
        tax_rate=tax_rate,
        pm_channel=pm_channel,
        pf_channel=pf_channel,
        sku_a=sku_a,
        sku_b=sku_b,
        source=source,
        make_sku=_make_sku,
    )
