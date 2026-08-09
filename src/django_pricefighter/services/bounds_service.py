# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Thin admin-API service: resolve a market by idx/iso2 and delegate to
pricemanager's get_price_bounds(). The view layer must not import pricemanager models
directly (module-structure rule) — this is the resolve seam, same pattern as
apply_service._resolve_market_objects.
"""

from django_pricemanager.models import Channel as PmChannel
from django_pricemanager.services.price_bounds_service import get_price_bounds
from django_regional.models import Country


def get_bounds(sku: str, channel_idx: str, country: str) -> dict:
    """floor/ceiling/baseline for one (sku, channel, country). Raises ValueError for an
    unknown channel/country, propagates ProductRepresentation.DoesNotExist (pricemanager's)
    for an unknown sku — the view maps these to 400/404 respectively."""
    pm_channel = PmChannel.objects.filter(idx=channel_idx).first()
    country_obj = Country.objects.filter(iso2=country).first()
    if pm_channel is None or country_obj is None:
        raise ValueError(f"Unknown market: channel={channel_idx!r} country={country!r}")
    return get_price_bounds(sku, pm_channel, country_obj)
