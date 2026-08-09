# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view for price bounds. Thin — resolution lives in bounds_service."""

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.schemas.responses.bounds import BoundsResponse
from django_pricefighter.services import bounds_service


class BoundsViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        operation_id="pricefighter_bounds_retrieve",
        tags=["PriceFighter Decisions"],
        summary="Retrieve price bounds for sku x market",
        parameters=[
            OpenApiParameter(name="sku", description="Product SKU", required=True),
            OpenApiParameter(name="channel", description="PriceFighter channel idx", required=True),
            OpenApiParameter(name="country", description="Market country ISO2 code", required=True),
        ],
        responses={
            200: BoundsResponse,
            400: {"description": "Missing query params or unknown channel/country"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
            404: {"description": "Unknown sku"},
        },
    )
    def list(self, request: Request) -> Response:
        sku = request.query_params.get("sku")
        channel_idx = request.query_params.get("channel")
        country = request.query_params.get("country")
        if not sku or not channel_idx or not country:
            raise DRFValidationError({"detail": "sku, channel, country query params are required."})

        try:
            bounds = bounds_service.get_bounds(sku, channel_idx, country)
        except ValueError as exc:
            raise DRFValidationError({"detail": str(exc)}) from exc
        except ObjectDoesNotExist:
            raise NotFound(f"Unknown sku: {sku}") from None

        response = BoundsResponse(
            sku=sku,
            channel_idx=channel_idx,
            country=country,
            floor=str(bounds["floor"]) if bounds["floor"] is not None else None,
            ceiling=str(bounds["ceiling"]) if bounds["ceiling"] is not None else None,
            baseline=str(bounds["baseline"]) if bounds["baseline"] is not None else None,
        )
        return Response(response.model_dump())
