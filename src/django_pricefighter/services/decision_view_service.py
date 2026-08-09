# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Orchestrates the decision view: enumerate -> fetch -> engine -> sort -> paginate.

Side-effect-free by construction — rendering never writes a PriceDecision, only
apply_service does.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models.functions import Lower
from django.utils import timezone

from django_pricefighter import settings as pf_settings
from django_pricefighter.models import ProductRepresentation
from django_pricefighter.services import engine_inputs, market_service
from django_pricefighter.services.quote_engine import EngineDecision, compute_decision

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class DecisionRow:
    decision: EngineDecision
    name: str
    margin: Decimal | None


def _margin(decision: EngineDecision) -> Decimal | None:
    if decision.cost is None or not decision.current_price_net:
        return None
    return ((decision.current_price_net - decision.cost) / decision.current_price_net * 100).quantize(CENTS)


def _names_by_sku_channel(skus: list[str], channel_idxs: set[str]) -> dict[tuple[str, str], str]:
    if not skus or not channel_idxs:
        return {}
    rows = (
        ProductRepresentation.objects.annotate(sku_lower=Lower("sku"))
        .filter(sku_lower__in=[s.lower() for s in skus], channel__idx__in=channel_idxs)
        .values_list("sku_lower", "channel__idx", "name")
    )
    return {(sku_lower, channel_idx): name for sku_lower, channel_idx, name in rows}


def _sort_value(row: DecisionRow, field: str):
    if field == "margin":
        return row.margin
    if field == "name":
        return row.name
    return getattr(row.decision, field, None)


def _sort_rows(rows: list[DecisionRow], field: str, descending: bool) -> list[DecisionRow]:
    have_value = [r for r in rows if _sort_value(r, field) is not None]
    missing_value = [r for r in rows if _sort_value(r, field) is None]
    have_value.sort(key=lambda r: _sort_value(r, field), reverse=descending)
    return have_value + missing_value


def build_decision_rows(
    skus: list[str] | None = None, *, sort: str = "-gap_baseline", offset: int = 0, limit: int | None = None
) -> tuple[list[DecisionRow], int]:
    """Render the decision view. `skus` defaults to market_service.get_candidate_skus()
    (only skus with a valid competitor observation) — pass explicit skus to bypass the
    pre-filter (e.g. a harness verifying a known scenario sku that itself has no observations).
    `sort` is a field name on EngineDecision or "margin", optionally prefixed with "-" for
    descending; rows with a None sort value always sort last.
    """
    if skus is None:
        skus = sorted(market_service.get_candidate_skus())
    markets = market_service.get_markets()

    now = timezone.now()
    inputs = engine_inputs.build_engine_inputs(
        skus,
        markets,
        now=now,
        staleness_days=pf_settings.PRICEFIGHTER_STALENESS_DAYS,
        estimator=pf_settings.PRICEFIGHTER_REF_ESTIMATOR,
    )
    decisions = [compute_decision(i) for i in inputs]

    channel_idxs = {d.channel_idx for d in decisions}
    names = _names_by_sku_channel(skus, channel_idxs)
    rows = [
        DecisionRow(decision=d, name=names.get((d.sku.lower(), d.channel_idx), ""), margin=_margin(d))
        for d in decisions
    ]

    descending = sort.startswith("-")
    rows = _sort_rows(rows, sort.lstrip("-"), descending)
    total = len(rows)
    rows = rows[offset : offset + limit] if limit is not None else rows[offset:]
    return rows, total
