# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.urls import path

from django_pricefighter.api.admin.views.apply_views import ApplyViewSet
from django_pricefighter.api.admin.views.bounds_views import BoundsViewSet
from django_pricefighter.api.admin.views.channel_views import ChannelViewSet
from django_pricefighter.api.admin.views.decision_views import DecisionViewSet
from django_pricefighter.api.admin.views.history_views import HistoryViewSet
from django_pricefighter.api.admin.views.rule_views import PricingRuleViewSet

urlpatterns = [
    path("channels/", ChannelViewSet.as_view({"get": "list"}), name="admin-channel-list"),
    path("channels/sync/", ChannelViewSet.as_view({"post": "sync"}), name="admin-channel-sync"),
    path("decisions/", DecisionViewSet.as_view({"get": "list"}), name="admin-decision-list"),
    path("decisions/<str:sku>/", DecisionViewSet.as_view({"get": "retrieve"}), name="admin-decision-detail"),
    path("bounds/", BoundsViewSet.as_view({"get": "list"}), name="admin-bounds"),
    path("history/", HistoryViewSet.as_view({"get": "list"}), name="admin-history-list"),
    path("apply/", ApplyViewSet.as_view({"post": "create"}), name="admin-apply"),
    path("rules/", PricingRuleViewSet.as_view({"get": "list", "post": "create"}), name="admin-rule-list"),
    path(
        "rules/<int:pk>/",
        PricingRuleViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="admin-rule-detail",
    ),
]
