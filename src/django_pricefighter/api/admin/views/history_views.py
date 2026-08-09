# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view for PriceDecision history. Thin — filtering lives in
decision_history_service.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.pagination import AdminPageNumberPagination
from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.schemas.responses.decision_history import PriceDecisionListResponse, PriceDecisionResponse
from django_pricefighter.services import decision_history_service


def _to_response(pd) -> PriceDecisionResponse:
    return PriceDecisionResponse(
        id=pd.pk,
        sku=pd.representation.sku,
        channel_idx=pd.channel.idx,
        country=pd.country,
        currency=pd.currency,
        old_price=str(pd.old_price),
        new_price=str(pd.new_price),
        strategy=pd.strategy,
        mode=pd.mode,
        applied_by=pd.applied_by.email if pd.applied_by else None,
        reason=pd.reason,
        created_at=pd.created_at.isoformat(),
    )


class HistoryViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        operation_id="pricefighter_history_list",
        tags=["PriceFighter Decisions"],
        summary="List price decision history",
        description="Paginated PriceDecision audit log, filterable by sku/channel/country/currency/strategy.",
        parameters=[
            OpenApiParameter(name="sku", description="Filter by product SKU", required=False),
            OpenApiParameter(name="channel", description="Filter by PriceFighter channel idx", required=False),
            OpenApiParameter(name="country", description="Filter by market country ISO2 code", required=False),
            OpenApiParameter(name="currency", description="Filter by market currency ISO3 code", required=False),
            OpenApiParameter(
                name="strategy",
                description="Filter by strategy: compete|raise|revert_baseline|hold_at_floor",
                required=False,
            ),
            OpenApiParameter(name="page", description="Page number", required=False),
            OpenApiParameter(name="page_size", description="Items per page (max 100)", required=False),
        ],
        responses={
            200: PriceDecisionListResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
    )
    def list(self, request: Request) -> Response:
        qs = decision_history_service.query_decisions(
            sku=request.query_params.get("sku"),
            channel_idx=request.query_params.get("channel"),
            country=request.query_params.get("country"),
            currency=request.query_params.get("currency"),
            strategy=request.query_params.get("strategy"),
        )
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [_to_response(pd).model_dump() for pd in page]
        return paginator.get_paginated_response(results)
