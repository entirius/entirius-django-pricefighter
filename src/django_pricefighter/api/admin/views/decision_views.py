# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for the decision view. Thin — orchestration lives in
decision_view_service; this module only parses query params, validates filters against
known values, and serializes DecisionRow -> response schemas.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.pagination import AdminPageNumberPagination
from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.schemas.responses.decision_view import (
    DecisionDetailResponse,
    DecisionListItemResponse,
    DecisionListResponse,
    DecisionObservationResponse,
)
from django_pricefighter.services import decision_view_service, market_service
from django_pricefighter.services.decision_view_service import DecisionRow
from django_pricefighter.services.quote_engine import Recommendation

_SORT_FIELD_MAP = {
    "gap": "gap_baseline",
    "sku": "sku",
    "name": "name",
    "current_price": "current_price",
    "competitor_price": "reference_price",
    "margin": "margin",
}

_RECOMMENDATION_VALUES = frozenset(
    {
        Recommendation.COMPETE,
        Recommendation.RAISE,
        Recommendation.HOLD,
        Recommendation.REVERT_BASELINE,
        Recommendation.HOLD_AT_FLOOR,
        Recommendation.NO_RECOMMENDATION,
    }
)


def _parse_sort(raw: str | None) -> str:
    raw = raw or "-gap"
    descending = raw.startswith("-")
    field = raw[1:] if descending else raw
    mapped = _SORT_FIELD_MAP.get(field)
    if mapped is None:
        raise DRFValidationError({"sort": [f"Unsupported sort field {field!r}. Allowed: {sorted(_SORT_FIELD_MAP)}"]})
    return f"-{mapped}" if descending else mapped


def _row_to_list_item(row: DecisionRow) -> DecisionListItemResponse:
    d = row.decision
    return DecisionListItemResponse(
        sku=d.sku,
        name=row.name,
        channel_idx=d.channel_idx,
        country=d.country,
        currency=d.currency,
        current_price=str(d.current_price),
        current_price_net=str(d.current_price_net),
        cost=str(d.cost) if d.cost is not None else None,
        floor=str(d.floor) if d.floor is not None else None,
        baseline=str(d.baseline) if d.baseline is not None else None,
        reference_price=str(d.reference_price) if d.reference_price is not None else None,
        estimator=d.estimator,
        gap_baseline=str(d.gap_baseline) if d.gap_baseline is not None else None,
        gap_current=str(d.gap_current) if d.gap_current is not None else None,
        margin=str(row.margin) if row.margin is not None else None,
        recommendation=d.recommendation,
        suggested_price=str(d.suggested_price) if d.suggested_price is not None else None,
        reason=d.reason,
        strategy=d.strategy,
        mode=d.mode,
        price_war=d.price_war,
        clamped_floor=d.clamped_floor,
        clamped_step=d.clamped_step,
    )


def _row_to_detail(row: DecisionRow) -> DecisionDetailResponse:
    item = _row_to_list_item(row)
    observations = [
        DecisionObservationResponse(
            source_idx=o.source_idx,
            price=str(o.price),
            currency=o.currency,
            stock=o.stock,
            ts=o.ts.isoformat(),
            is_trusted=o.is_trusted,
            flag=o.flag,
        )
        for o in row.decision.observations
    ]
    return DecisionDetailResponse(**item.model_dump(), observations=observations)


class DecisionViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        operation_id="pricefighter_decision_list",
        tags=["PriceFighter Decisions"],
        summary="List decision view rows",
        description=(
            "Gap/recommendation/suggested-price rows for sku x market. Defaults to skus with "
            "a valid competitor observation (competitor_only=true) — pass competitor_only=false "
            "to scan the full catalog (expensive at 10-30k skus)."
        ),
        parameters=[
            OpenApiParameter(name="channel", description="Filter by PriceFighter channel idx", required=False),
            OpenApiParameter(
                name="recommendation",
                description="Filter by recommendation: compete|raise|hold|revert_baseline|hold_at_floor|no_recommendation",
                required=False,
            ),
            OpenApiParameter(
                name="competitor_only", description="Default true — false scans the full catalog", required=False
            ),
            OpenApiParameter(
                name="sort",
                description="gap|sku|name|current_price|competitor_price|margin, prefix '-' for descending. Default: -gap",
                required=False,
            ),
            OpenApiParameter(name="page", description="Page number", required=False),
            OpenApiParameter(name="page_size", description="Items per page (max 100)", required=False),
        ],
        responses={
            200: DecisionListResponse,
            400: {"description": "Unknown sort field / channel / recommendation"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
    )
    def list(self, request: Request) -> Response:
        sort_token = _parse_sort(request.query_params.get("sort"))
        competitor_only = request.query_params.get("competitor_only", "true").lower() != "false"
        skus = None if competitor_only else sorted(market_service.get_all_skus())
        rows, _ = decision_view_service.build_decision_rows(skus=skus, sort=sort_token)

        channel_filter = request.query_params.get("channel")
        if channel_filter:
            known_channels = {m.channel_idx for m in market_service.get_markets()}
            if channel_filter not in known_channels:
                raise DRFValidationError({"channel": [f"Unknown channel {channel_filter!r}."]})
            rows = [r for r in rows if r.decision.channel_idx == channel_filter]

        recommendation_filter = request.query_params.get("recommendation")
        if recommendation_filter:
            if recommendation_filter not in _RECOMMENDATION_VALUES:
                raise DRFValidationError({"recommendation": [f"Unknown recommendation {recommendation_filter!r}."]})
            rows = [r for r in rows if r.decision.recommendation == recommendation_filter]

        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(rows, request)
        results = [_row_to_list_item(r).model_dump() for r in page]
        return paginator.get_paginated_response(results)

    @extend_schema(
        operation_id="pricefighter_decision_detail",
        tags=["PriceFighter Decisions"],
        summary="Retrieve a decision detail for sku x market",
        description="Full observation list (including filtered-out entries) for one sku x market.",
        parameters=[
            OpenApiParameter(name="sku", location=OpenApiParameter.PATH, description="Product SKU"),
            OpenApiParameter(name="channel", description="PriceFighter channel idx", required=True),
            OpenApiParameter(name="country", description="Market country ISO2 code", required=True),
            OpenApiParameter(name="currency", description="Market currency ISO3 code", required=True),
        ],
        responses={
            200: DecisionDetailResponse,
            400: {"description": "Missing channel/country/currency query params"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "No decision for this sku x market"},
        },
    )
    def retrieve(self, request: Request, sku: str | None = None) -> Response:
        channel_idx = request.query_params.get("channel")
        country = request.query_params.get("country")
        currency = request.query_params.get("currency")
        if not channel_idx or not country or not currency:
            raise DRFValidationError({"detail": "channel, country, currency query params are required."})

        rows, _ = decision_view_service.build_decision_rows(skus=[sku])
        match = next(
            (
                r
                for r in rows
                if r.decision.channel_idx == channel_idx
                and r.decision.country == country
                and r.decision.currency == currency
            ),
            None,
        )
        if match is None:
            raise NotFound(f"No decision for sku={sku!r} market=({channel_idx}, {country}, {currency}).")
        return Response(_row_to_detail(match).model_dump())
