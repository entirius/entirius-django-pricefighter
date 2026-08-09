# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Instrument enumeration for the decision view: markets x candidate skus.

A market without a CurrentPrice row does not exist (pricemanager.get_markets() contract) —
and by default we only quote skus with at least one non-stale competitor observation, since
there is nothing to compare against otherwise (NO_COMP rows are reachable explicitly, not by
default scan).
"""

from dataclasses import dataclass
from datetime import timedelta

from django_atlas.enums import SourceKind
from django_atlas.services.observation_service import get_skus_with_valid_observations
from django_pricemanager.services.price_bounds_service import get_markets as _pm_get_markets

from django_pricefighter import settings as pf_settings
from django_pricefighter.models import ProductRepresentation


@dataclass(frozen=True)
class Market:
    channel_idx: str
    country: str
    currency: str


def get_markets() -> list[Market]:
    return [
        Market(channel_idx=row["channel_idx"], country=row["country"], currency=row["currency"])
        for row in _pm_get_markets()
    ]


def get_candidate_skus() -> set[str]:
    max_age = timedelta(days=pf_settings.PRICEFIGHTER_STALENESS_DAYS)
    return get_skus_with_valid_observations(SourceKind.MONITORING.value, max_age)


def get_all_skus() -> list[str]:
    """Every active sku across all channels — the "full catalog" switch for the decision
    view (default is candidate-only; explicit opt-in given the 10-30k sku scale)."""
    return list(ProductRepresentation.objects.filter(is_active=True).values_list("sku", flat=True).distinct())
