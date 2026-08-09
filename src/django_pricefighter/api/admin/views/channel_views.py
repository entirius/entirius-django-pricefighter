# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for pricefighter channels."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.pagination import AdminPageNumberPagination
from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.schemas.responses.channel import ChannelListResponse, ChannelResponse
from django_pricefighter.services import channel_sync_service


@extend_schema_view(list=extend_schema(tags=["PriceFighter Channels"]))
class ChannelViewSet(viewsets.ViewSet):
    """Admin read-only access to pricefighter channels with sync action."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List pricefighter channels",
        description="Returns all pricefighter channels.",
        responses={
            200: ChannelListResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
    )
    def list(self, request: Request, **kwargs) -> Response:
        qs = channel_sync_service.list_channels()
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [ChannelResponse(**channel_sync_service.serialize_channel(ch)).model_dump() for ch in page]
        response = ChannelListResponse(
            count=paginator.page.paginator.count,
            next=paginator.get_next_link(),
            previous=paginator.get_previous_link(),
            results=results,
        )
        return Response(response.model_dump())

    @extend_schema(
        summary="Sync channels from PIM",
        description="Syncs pricefighter channels from PIM Channel model.",
        tags=["PriceFighter Channels"],
        responses={
            200: {"description": "Sync result"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
    )
    @action(detail=False, methods=["post"], url_path="sync")
    def sync(self, request: Request, **kwargs) -> Response:
        count = channel_sync_service.sync_channels_from_pim()
        return Response({"synced": count}, status=status.HTTP_200_OK)
