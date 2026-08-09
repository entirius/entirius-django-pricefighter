# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view for apply. One endpoint — single apply is just a 1-item
batch. Thin — the write flow lives entirely in apply_service.apply_batch().
"""

from drf_spectacular.utils import extend_schema
from pydantic import ValidationError
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.api.admin.throttling import ApplyThrottle
from django_pricefighter.schemas.requests.apply import ApplyBatchRequest
from django_pricefighter.schemas.responses.apply import ApplyReportResponse, ApplyResultItemResponse
from django_pricefighter.services import apply_service
from django_pricefighter.services.apply_service import ApplyItem, ApplyResult


def _to_response_item(result: ApplyResult) -> ApplyResultItemResponse:
    item = result.item
    return ApplyResultItemResponse(
        sku=item.sku,
        channel=item.channel_idx,
        country=item.country,
        currency=item.currency,
        expected_new_price=str(item.expected_new_price),
        reason=result.reason,
    )


class ApplyViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    throttle_classes = [ApplyThrottle]

    @extend_schema(
        operation_id="pricefighter_apply_create",
        tags=["PriceFighter Apply"],
        summary="Apply priced decisions (single = 1-item batch)",
        description=(
            "Recomputes each item's decision live, rejects a mismatch against expected_new_price "
            "as 'stale', and writes through pricemanager's edit_price(). Best-effort — every item "
            "resolves independently into exactly one bucket (applied/clamped/skipped/failed/stale)."
        ),
        request=ApplyBatchRequest,
        responses={
            200: ApplyReportResponse,
            400: {"description": "Validation error (cap 1000 items, missing fields)"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            429: {"description": "Throttled"},
        },
    )
    def create(self, request: Request) -> Response:
        try:
            data = ApplyBatchRequest(**request.data)
        except ValidationError as exc:
            from django_utils.api.v2_errors import raise_pydantic_as_drf

            raise_pydantic_as_drf(exc)

        items = [
            ApplyItem(
                sku=i.sku,
                channel_idx=i.market.channel,
                country=i.market.country,
                currency=i.market.currency,
                expected_new_price=i.expected_new_price,
            )
            for i in data.items
        ]
        report = apply_service.apply_batch(items, user=request.user)
        response = ApplyReportResponse(
            **{bucket: [_to_response_item(r) for r in results] for bucket, results in report.items()}
        )
        return Response(response.model_dump())
