# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for PricingRule CRUD. Thin — whitelist + validation live
in pricing_rule_service.
"""

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema, extend_schema_view
from pydantic import BaseModel, ValidationError
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_pricefighter.api.admin.pagination import AdminPageNumberPagination
from django_pricefighter.api.admin.permissions import IsAdminUser
from django_pricefighter.schemas.requests.pricing_rule import PricingRuleCreateRequest, PricingRuleUpdateRequest
from django_pricefighter.schemas.responses.pricing_rule import PricingRuleListResponse, PricingRuleResponse
from django_pricefighter.services import pricing_rule_service


def _to_response(rule) -> PricingRuleResponse:
    return PricingRuleResponse(
        id=rule.pk,
        strategy=rule.strategy,
        mode=rule.mode,
        price_war=rule.price_war,
        sku=rule.sku,
        category_idx=rule.category_idx,
        channel=rule.channel.idx if rule.channel_id else None,
    )


def _parse(model_cls: type[BaseModel], data: dict) -> BaseModel:
    try:
        return model_cls(**data)
    except ValidationError as exc:
        from django_utils.api.v2_errors import raise_pydantic_as_drf

        raise_pydantic_as_drf(exc)


def _get_rule_or_404(pk: str | None):
    try:
        return pricing_rule_service.get_rule(int(pk))
    except (ObjectDoesNotExist, ValueError, TypeError):
        raise NotFound(f"PricingRule {pk} not found.") from None


@extend_schema_view(
    list=extend_schema(operation_id="pricefighter_rule_list", tags=["PriceFighter Rules"]),
    retrieve=extend_schema(operation_id="pricefighter_rule_retrieve", tags=["PriceFighter Rules"]),
    create=extend_schema(operation_id="pricefighter_rule_create", tags=["PriceFighter Rules"]),
    partial_update=extend_schema(operation_id="pricefighter_rule_update", tags=["PriceFighter Rules"]),
    destroy=extend_schema(operation_id="pricefighter_rule_destroy", tags=["PriceFighter Rules"]),
)
class PricingRuleViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List pricing rules",
        responses={
            200: PricingRuleListResponse,
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
    )
    def list(self, request: Request) -> Response:
        qs = pricing_rule_service.list_rules()
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [_to_response(r).model_dump() for r in page]
        return paginator.get_paginated_response(results)

    @extend_schema(
        summary="Retrieve a pricing rule", responses={200: PricingRuleResponse, 404: {"description": "Not found"}}
    )
    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return Response(_to_response(_get_rule_or_404(pk)).model_dump())

    @extend_schema(
        summary="Create a pricing rule",
        request=PricingRuleCreateRequest,
        responses={
            201: PricingRuleResponse,
            400: {"description": "Validation error (exactly-one-scope, unknown channel)"},
        },
    )
    def create(self, request: Request) -> Response:
        data = _parse(PricingRuleCreateRequest, request.data)
        try:
            rule = pricing_rule_service.create_rule(data.model_dump())
        except ValueError as exc:
            raise DRFValidationError({"detail": str(exc)}) from exc
        return Response(_to_response(rule).model_dump(), status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update a pricing rule",
        request=PricingRuleUpdateRequest,
        responses={
            200: PricingRuleResponse,
            400: {"description": "Validation error (exactly-one-scope, unknown channel)"},
            404: {"description": "Not found"},
        },
    )
    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        rule = _get_rule_or_404(pk)
        data = _parse(PricingRuleUpdateRequest, request.data)
        try:
            rule = pricing_rule_service.update_rule(rule=rule, updates=data.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise DRFValidationError({"detail": str(exc)}) from exc
        return Response(_to_response(rule).model_dump())

    @extend_schema(
        summary="Delete a pricing rule", responses={204: {"description": "Deleted"}, 404: {"description": "Not found"}}
    )
    def destroy(self, request: Request, pk: str | None = None) -> Response:
        rule = _get_rule_or_404(pk)
        pricing_rule_service.delete_rule(rule)
        return Response(status=status.HTTP_204_NO_CONTENT)
