# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bulk-fetch every input the quote engine needs for a batch of (sku x market) pairs.

Constant query count regardless of how many skus are in the batch — every downstream call is
either one bulk query for the whole batch, or one per distinct channel (small, bounded set).
Cross-module ORM stays here; quote_engine.py itself never touches the database.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.db.models.functions import Lower
from django_atlas.enums import SourceKind
from django_atlas.services.observation_service import get_observations_bulk
from django_pricemanager.models import Channel as PmChannel
from django_pricemanager.services.price_bounds_service import (
    get_current_prices_bulk,
    get_price_bounds_bulk,
    get_purchase_costs_bulk,
)
from django_regional.models import Country, Currency

from django_pricefighter.models import Channel as PfChannel
from django_pricefighter.models import ProductRepresentation, QuoteConfig
from django_pricefighter.services.market_service import Market
from django_pricefighter.services.quote_engine import EngineInput, ObservationInput, QuoteConfigRow
from django_pricefighter.services.rule_resolver import DEFAULT_RESOLVED_RULE, resolve_bulk


def _quote_config_rows_by_currency() -> dict[str, list[QuoteConfigRow]]:
    rows = defaultdict(list)
    for cfg in QuoteConfig.objects.all().order_by("currency", "range_from"):
        rows[cfg.currency].append(
            QuoteConfigRow(
                range_from=cfg.range_from,
                range_to=cfg.range_to,
                band_dn=cfg.band_dn,
                band_up=cfg.band_up,
                undercut=cfg.undercut,
                headroom=cfg.headroom,
                max_step=cfg.max_step,
                rounding=cfg.rounding,
            )
        )
    return rows


def _category_by_sku_channel(skus: list[str], pf_channels: dict[str, PfChannel]) -> dict[tuple[str, int], str]:
    if not pf_channels:
        return {}
    skus_lower = [s.lower() for s in skus]
    rows = (
        ProductRepresentation.objects.annotate(sku_lower=Lower("sku"))
        .filter(sku_lower__in=skus_lower, channel_id__in=[c.pk for c in pf_channels.values()])
        .values_list("sku_lower", "channel_id", "category")
    )
    return {(sku_lower, channel_id): category for sku_lower, channel_id, category in rows}


def _observation_inputs_by_sku(skus: list[str]) -> dict[str, list[ObservationInput]]:
    raw = get_observations_bulk(skus, SourceKind.MONITORING.value)
    country_ids = {o["source"].country_id for entries in raw.values() for o in entries if o["source"].country_id}
    country_iso_by_id = (
        dict(Country.objects.filter(pk__in=country_ids).values_list("pk", "iso2")) if country_ids else {}
    )

    result: dict[str, list[ObservationInput]] = {}
    for sku, entries in raw.items():
        parsed = []
        for entry in entries:
            source = entry["source"]
            value = entry["value"]
            price = value.get("price")
            if price is None:
                continue
            parsed.append(
                ObservationInput(
                    source_idx=source.idx,
                    price=Decimal(str(price)),
                    currency=value.get("currency"),
                    stock=value.get("stock"),
                    ts=entry["ts"],
                    is_trusted=source.is_trusted,
                    source_country=country_iso_by_id.get(source.country_id),
                )
            )
        result[sku] = parsed
    return result


def build_engine_inputs(
    skus: list[str], markets: list[Market], *, now: datetime, staleness_days: int, estimator: str
) -> list[EngineInput]:
    if not skus or not markets:
        return []

    channel_idxs = {m.channel_idx for m in markets}
    country_isos = {m.country for m in markets}
    currency_isos = {m.currency for m in markets}

    pm_channels = {c.idx: c for c in PmChannel.objects.filter(idx__in=channel_idxs)}
    pf_channels = {c.idx: c for c in PfChannel.objects.filter(idx__in=channel_idxs)}
    countries = {c.iso2: c for c in Country.objects.filter(iso2__in=country_isos)}
    currencies = {c.iso3: c for c in Currency.objects.filter(iso3__in=currency_isos)}

    usable_markets = [
        m for m in markets if m.channel_idx in pm_channels and m.country in countries and m.currency in currencies
    ]

    price_pairs = [
        (sku, pm_channels[m.channel_idx], countries[m.country], currencies[m.currency])
        for sku in skus
        for m in usable_markets
    ]
    current_prices = get_current_prices_bulk(price_pairs)

    bounds_pairs = [(sku, pm_channels[m.channel_idx], countries[m.country]) for sku in skus for m in usable_markets]
    bounds = get_price_bounds_bulk(bounds_pairs)

    purchase_costs_by_channel = {
        channel_idx: get_purchase_costs_bulk(skus, pm_channels[channel_idx])
        for channel_idx in {m.channel_idx for m in usable_markets}
    }

    observations_by_sku = _observation_inputs_by_sku(skus)
    quote_config_rows = _quote_config_rows_by_currency()
    category_by_sku_channel = _category_by_sku_channel(skus, pf_channels)

    resolve_items = [
        (sku, category_by_sku_channel.get((sku.lower(), pf_channels[m.channel_idx].pk), ""), pf_channels[m.channel_idx])
        for sku in skus
        for m in usable_markets
        if m.channel_idx in pf_channels
    ]
    resolutions = resolve_bulk(resolve_items)

    inputs = []
    for sku in skus:
        for m in usable_markets:
            cp = current_prices.get((sku, m.channel_idx, m.country, m.currency))
            if cp is None:
                continue
            pf_channel = pf_channels.get(m.channel_idx)
            resolved = resolutions.get((sku.lower(), pf_channel.pk if pf_channel else None), DEFAULT_RESOLVED_RULE)
            row_bounds = bounds.get((sku, m.channel_idx, m.country), {})
            cost_row = purchase_costs_by_channel.get(m.channel_idx, {}).get(sku)

            inputs.append(
                EngineInput(
                    sku=sku,
                    channel_idx=m.channel_idx,
                    country=m.country,
                    currency=m.currency,
                    current_price=cp.gross_value,
                    current_price_net=cp.net_value,
                    current_price_source=cp.source,
                    cost=cost_row.net_cost if cost_row else None,
                    floor=row_bounds.get("floor"),
                    baseline=row_bounds.get("baseline"),
                    observations=observations_by_sku.get(sku, []),
                    quote_config_rows=quote_config_rows.get(m.currency, []),
                    strategy=resolved.strategy,
                    mode=resolved.mode,
                    price_war=resolved.price_war,
                    now=now,
                    staleness_days=staleness_days,
                    estimator=estimator,
                )
            )
    return inputs
