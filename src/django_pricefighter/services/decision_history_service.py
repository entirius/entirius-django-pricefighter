# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Thin admin-API service: PriceDecision history queries. No serialization
here — the view maps rows to PriceDecisionResponse.
"""

from django.db.models import QuerySet

from django_pricefighter.models import PriceDecision


def query_decisions(
    *,
    sku: str | None = None,
    channel_idx: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    strategy: str | None = None,
) -> QuerySet[PriceDecision]:
    qs = PriceDecision.objects.select_related("representation", "channel", "applied_by").order_by("-created_at")
    if sku:
        qs = qs.filter(representation__sku__iexact=sku)
    if channel_idx:
        qs = qs.filter(channel__idx=channel_idx)
    if country:
        qs = qs.filter(country__iexact=country)
    if currency:
        qs = qs.filter(currency__iexact=currency)
    if strategy:
        qs = qs.filter(strategy=strategy)
    return qs
