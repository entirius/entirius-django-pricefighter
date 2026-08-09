# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ProductRepresentation sync service — mirrors PIM products per channel.

Soft dependency on django_pim: every PIM access is wrapped so the module degrades
gracefully (no-op) when django_pim is not installed.
"""

import logging

from django.db.models.functions import Lower

from django_pricefighter.models import Channel, ProductRepresentation

logger = logging.getLogger(__name__)


def _find_representation(sku: str, channel: Channel) -> ProductRepresentation | None:
    # sku__iexact does not hit the UniqueConstraint(Lower("sku"), "channel") functional index —
    # annotate+filter on Lower("sku") does, avoiding a seq scan on every sync.
    return (
        ProductRepresentation.objects.annotate(sku_lower=Lower("sku")).filter(sku_lower=sku.lower(), channel=channel)
    ).first()


def _resolve_category_idx(product) -> str:
    first = product.product_in_category.select_related("category").order_by("position").first()
    return first.category.idx if first else ""


def _resolve_name(product, channel: Channel) -> str:
    lang_iso2 = channel.default_language.iso2 if channel.default_language else ""
    name = product.name_lang(lang_iso2) if lang_iso2 else product.real_product.sku
    return name or product.real_product.sku


def _deactivate(sku: str, channel: Channel) -> ProductRepresentation | None:
    deactivated = _find_representation(sku, channel)
    if deactivated and deactivated.is_active:
        deactivated.is_active = False
        deactivated.save(update_fields=["is_active"])
    return deactivated


def _upsert_representation(sku: str, channel: Channel, product) -> ProductRepresentation:
    name = _resolve_name(product, channel)
    category = _resolve_category_idx(product)

    existing = _find_representation(sku, channel)
    if existing is not None:
        existing.sku = sku
        existing.name = name
        existing.category = category
        existing.is_active = True
        existing.save(update_fields=["sku", "name", "category", "is_active"])
        return existing

    return ProductRepresentation.objects.create(sku=sku, channel=channel, name=name, category=category, is_active=True)


def sync_pair(sku: str, channel_idx: str) -> ProductRepresentation | None:
    """Upsert (or deactivate) the ProductRepresentation for a single sku×channel pair."""
    channel = Channel.objects.filter(idx=channel_idx).first()
    if channel is None:
        logger.info("No local Channel for idx=%s, skipping sync for sku=%s", channel_idx, sku)
        return None

    try:
        from django_pim.models import Product as PimProduct
        from django_pim.services import product_service
    except ImportError:
        logger.info("django_pim not installed, skipping representation sync")
        return None

    try:
        product = product_service.get_product_by_sku(channel_idx, sku)
    except PimProduct.DoesNotExist:
        return _deactivate(sku, channel)

    return _upsert_representation(sku, channel, product)


def full_sync() -> dict:
    """Full reconcile: upsert every PIM product per local channel, deactivate the rest.

    A product that fails to sync (bad denorm data, transient DB error, ...) is logged and
    skipped rather than aborting the whole reconcile — the remaining products and channels
    still get synced. A failed sku is still counted as "seen" so it is not wrongly deactivated.
    """
    try:
        from django_pim.services import product_service
    except ImportError:
        logger.info("django_pim not installed, skipping full sync")
        return {"synced": 0, "deactivated": 0, "failed": 0}

    synced = 0
    deactivated = 0
    failed = 0
    for channel in Channel.objects.all():
        seen_skus: set[str] = set()
        for product in product_service.list_products(channel.idx):
            sku = product.real_product.sku
            seen_skus.add(sku)
            try:
                _upsert_representation(sku, channel, product)
                synced += 1
            except Exception:
                failed += 1
                logger.exception("Failed to sync sku=%s channel=%s during full_sync", sku, channel.idx)

        stale = ProductRepresentation.objects.filter(channel=channel, is_active=True).exclude(sku__in=seen_skus)
        deactivated += stale.update(is_active=False)

    return {"synced": synced, "deactivated": deactivated, "failed": failed}
