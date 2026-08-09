# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API tests for the decision view / bounds / history / apply / rules endpoints."""

import pytest

from django_pricefighter.models import PriceDecision, PricingRule
from django_pricefighter.models import ProductRepresentation as PfRep
from django_pricefighter.services import pricing_rule_service
from django_pricefighter.services.decision_view_service import build_decision_rows

DECISIONS_URL = "/api/pricefighter/v2/admin/decisions/"
BOUNDS_URL = "/api/pricefighter/v2/admin/bounds/"
HISTORY_URL = "/api/pricefighter/v2/admin/history/"
APPLY_URL = "/api/pricefighter/v2/admin/apply/"
RULES_URL = "/api/pricefighter/v2/admin/rules/"


def _detail_url(sku: str) -> str:
    return f"{DECISIONS_URL}{sku}/"


# --- decisions: list ------------------------------------------------------------------


@pytest.mark.django_db
def test_list_decisions_requires_auth(api_client):
    response = api_client.get(DECISIONS_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_decisions_forbidden_for_regular_user(regular_client, decision_fixture):
    response = regular_client.get(DECISIONS_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_decisions_default_competitor_only(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL)
    assert response.status_code == 200
    body = response.json()
    skus = {row["sku"] for row in body["results"]}
    assert "SKU-A" in skus  # has a valid observation
    assert "SKU-B" not in skus  # no observation -> excluded by default pre-filter


@pytest.mark.django_db
def test_list_decisions_competitor_only_false_scans_full_catalog(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"competitor_only": "false"})
    assert response.status_code == 200
    skus = {row["sku"] for row in response.json()["results"]}
    assert {"SKU-A", "SKU-B"} <= skus


@pytest.mark.django_db
def test_list_decisions_row_shape(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL)
    row = next(r for r in response.json()["results"] if r["sku"] == "SKU-A")
    for field in (
        "sku",
        "name",
        "channel_idx",
        "country",
        "currency",
        "current_price",
        "current_price_net",
        "cost",
        "floor",
        "baseline",
        "reference_price",
        "estimator",
        "gap_baseline",
        "gap_current",
        "margin",
        "recommendation",
        "suggested_price",
        "reason",
        "strategy",
        "mode",
        "price_war",
        "clamped_floor",
        "clamped_step",
    ):
        assert field in row
    assert "observations" not in row  # list rows stay lean; observations only in detail


@pytest.mark.django_db
def test_list_decisions_unknown_sort_field_400(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"sort": "bogus"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_list_decisions_sort_margin(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"sort": "margin", "competitor_only": "false"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_list_decisions_sort_competitor_price(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"sort": "-competitor_price"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_list_decisions_unknown_channel_filter_400(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"channel": "does-not-exist"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_list_decisions_channel_filter(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"channel": "ch1"})
    assert response.status_code == 200
    assert all(row["channel_idx"] == "ch1" for row in response.json()["results"])


@pytest.mark.django_db
def test_list_decisions_unknown_recommendation_filter_400(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"recommendation": "bogus"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_list_decisions_recommendation_filter(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"recommendation": "hold", "competitor_only": "false"})
    assert response.status_code == 200
    assert all(row["recommendation"] == "hold" for row in response.json()["results"])


@pytest.mark.django_db
def test_list_decisions_pagination_shape(admin_client, decision_fixture):
    response = admin_client.get(DECISIONS_URL, {"page_size": 1, "competitor_only": "false"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert "count" in body and "next" in body and "previous" in body


@pytest.mark.django_db
def test_list_decisions_render_has_no_side_effects(admin_client, decision_fixture):
    admin_client.get(DECISIONS_URL, {"competitor_only": "false"})
    assert PriceDecision.objects.count() == 0


# --- decisions: detail -----------------------------------------------------------------


@pytest.mark.django_db
def test_retrieve_decision_requires_auth(api_client, decision_fixture):
    response = api_client.get(_detail_url("SKU-A"))
    assert response.status_code == 401


@pytest.mark.django_db
def test_retrieve_decision_forbidden_for_regular_user(regular_client, decision_fixture):
    response = regular_client.get(_detail_url("SKU-A"), {"channel": "ch1", "country": "DE", "currency": "USD"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_retrieve_decision_missing_market_params_400(admin_client, decision_fixture):
    response = admin_client.get(_detail_url("SKU-A"))
    assert response.status_code == 400


@pytest.mark.django_db
def test_retrieve_decision_unknown_market_404(admin_client, decision_fixture):
    response = admin_client.get(_detail_url("SKU-A"), {"channel": "ch1", "country": "FR", "currency": "USD"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_retrieve_decision_ok(admin_client, decision_fixture):
    response = admin_client.get(_detail_url("SKU-A"), {"channel": "ch1", "country": "DE", "currency": "USD"})
    assert response.status_code == 200
    body = response.json()
    assert body["sku"] == "SKU-A"
    assert body["observations"]
    assert body["observations"][0]["flag"] == "valid"


# --- bounds -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_bounds_requires_auth(api_client, decision_fixture):
    response = api_client.get(BOUNDS_URL, {"sku": "SKU-A", "channel": "ch1", "country": "DE"})
    assert response.status_code == 401


@pytest.mark.django_db
def test_bounds_forbidden_for_regular_user(regular_client, decision_fixture):
    response = regular_client.get(BOUNDS_URL, {"sku": "SKU-A", "channel": "ch1", "country": "DE"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_bounds_missing_params_400(admin_client, decision_fixture):
    response = admin_client.get(BOUNDS_URL, {"sku": "SKU-A"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_bounds_unknown_channel_400(admin_client, decision_fixture):
    response = admin_client.get(BOUNDS_URL, {"sku": "SKU-A", "channel": "does-not-exist", "country": "DE"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_bounds_unknown_sku_404(admin_client, decision_fixture):
    response = admin_client.get(BOUNDS_URL, {"sku": "NO-SUCH-SKU", "channel": "ch1", "country": "DE"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_bounds_ok(admin_client, decision_fixture):
    response = admin_client.get(BOUNDS_URL, {"sku": "SKU-A", "channel": "ch1", "country": "DE"})
    assert response.status_code == 200
    body = response.json()
    assert body["floor"] is not None
    assert body["baseline"] is not None


# --- history ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_history_requires_auth(api_client):
    response = api_client.get(HISTORY_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_history_forbidden_for_regular_user(regular_client, decision_fixture):
    response = regular_client.get(HISTORY_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_history_empty(admin_client, decision_fixture):
    response = admin_client.get(HISTORY_URL)
    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_history_lists_and_filters(admin_client, decision_fixture, admin_user):
    representation = PfRep.objects.get(sku="SKU-A", channel=decision_fixture.pf_channel)
    PriceDecision.objects.create(
        representation=representation,
        channel=decision_fixture.pf_channel,
        country="DE",
        currency="USD",
        old_price="100.00",
        new_price="94.00",
        strategy=PriceDecision.Strategy.COMPETE,
        mode="suggestion",
        applied_by=admin_user,
        reason={"foo": "bar"},
    )

    response = admin_client.get(HISTORY_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    row = body["results"][0]
    assert row["sku"] == "SKU-A"
    assert row["channel_idx"] == "ch1"
    assert row["applied_by"] == admin_user.email
    assert row["strategy"] == "compete"

    filtered = admin_client.get(HISTORY_URL, {"sku": "SKU-A"})
    assert filtered.json()["count"] == 1

    filtered_out = admin_client.get(HISTORY_URL, {"sku": "SKU-B"})
    assert filtered_out.json()["count"] == 0

    strategy_filtered = admin_client.get(HISTORY_URL, {"strategy": "raise"})
    assert strategy_filtered.json()["count"] == 0


# --- apply ------------------------------------------------------------------------------


def _dummy_item(i: int) -> dict:
    return {
        "sku": f"X-{i}",
        "market": {"channel": "ch1", "country": "DE", "currency": "USD"},
        "expected_new_price": "1.00",
    }


def _apply_payload(sku: str, *, channel="ch1", country="DE", currency="USD", price: str) -> dict:
    return {
        "items": [
            {
                "sku": sku,
                "market": {"channel": channel, "country": country, "currency": currency},
                "expected_new_price": price,
            }
        ]
    }


@pytest.mark.django_db
def test_apply_requires_auth(api_client):
    response = api_client.post(APPLY_URL, _apply_payload("SKU-A", price="1.00"), format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_apply_forbidden_for_regular_user(regular_client, decision_fixture):
    response = regular_client.post(APPLY_URL, _apply_payload("SKU-A", price="1.00"), format="json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_apply_missing_expected_new_price_400(admin_client, decision_fixture):
    payload = {"items": [{"sku": "SKU-A", "market": {"channel": "ch1", "country": "DE", "currency": "USD"}}]}
    response = admin_client.post(APPLY_URL, payload, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_apply_invalid_market_400(admin_client, decision_fixture):
    payload = {"items": [{"sku": "SKU-A", "market": {"channel": "ch1"}, "expected_new_price": "1.00"}]}
    response = admin_client.post(APPLY_URL, payload, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_apply_empty_items_400(admin_client, decision_fixture):
    response = admin_client.post(APPLY_URL, {"items": []}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_apply_cap_1000_items_accepted(admin_client, monkeypatch):
    monkeypatch.setattr(
        "django_pricefighter.api.admin.views.apply_views.apply_service.apply_batch",
        lambda items, user=None: {"applied": [], "clamped": [], "skipped": [], "failed": [], "stale": []},
    )
    items = [_dummy_item(i) for i in range(1000)]
    response = admin_client.post(APPLY_URL, {"items": items}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_apply_cap_1001_items_rejected(admin_client):
    items = [_dummy_item(i) for i in range(1001)]
    response = admin_client.post(APPLY_URL, {"items": items}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_apply_actionable_writes_price_and_decision(admin_client, decision_fixture, admin_user):
    PricingRule.objects.create(sku="SKU-A", strategy=PricingRule.Strategy.COMPETE)
    rows, _ = build_decision_rows(skus=["SKU-A"])
    row = next(r for r in rows if r.decision.channel_idx == "ch1" and r.decision.country == "DE")
    assert row.decision.recommendation == "compete"
    suggested = row.decision.suggested_price

    response = admin_client.post(APPLY_URL, _apply_payload("SKU-A", price=str(suggested)), format="json")
    assert response.status_code == 200
    report = response.json()
    assert not report["failed"]
    assert not report["stale"]
    assert len(report["applied"]) + len(report["clamped"]) == 1

    assert PriceDecision.objects.filter(representation__sku="SKU-A").count() == 1
    pd = PriceDecision.objects.get(representation__sku="SKU-A")
    assert pd.applied_by == admin_user
    assert pd.strategy == "compete"


@pytest.mark.django_db
def test_apply_stale_on_price_mismatch(admin_client, decision_fixture):
    PricingRule.objects.create(sku="SKU-A", strategy=PricingRule.Strategy.COMPETE)
    response = admin_client.post(APPLY_URL, _apply_payload("SKU-A", price="1.23"), format="json")
    assert response.status_code == 200
    report = response.json()
    assert len(report["stale"]) == 1
    assert PriceDecision.objects.filter(representation__sku="SKU-A").count() == 0


@pytest.mark.django_db
def test_apply_skipped_when_not_actionable(admin_client, decision_fixture):
    # SKU-B has no observation -> NO_COMP/hold, source=csv_import -> not actionable -> skipped.
    response = admin_client.post(APPLY_URL, _apply_payload("SKU-B", price="1.00"), format="json")
    assert response.status_code == 200
    report = response.json()
    assert len(report["skipped"]) == 1


@pytest.mark.django_db
def test_apply_throttled_after_30_requests(admin_client, decision_fixture):
    payload = _apply_payload("SKU-B", price="1.00")
    for _ in range(30):
        response = admin_client.post(APPLY_URL, payload, format="json")
        assert response.status_code == 200
    response = admin_client.post(APPLY_URL, payload, format="json")
    assert response.status_code == 429


# --- pricing rules ------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_rules_requires_auth(api_client):
    response = api_client.get(RULES_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_rules_forbidden_for_regular_user(regular_client):
    response = regular_client.get(RULES_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_rules_ok(admin_client):
    PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = admin_client.get(RULES_URL)
    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.django_db
def test_create_rule_requires_auth(api_client):
    response = api_client.post(RULES_URL, {"strategy": "compete", "sku": "ENT-1"}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_rule_forbidden_for_regular_user(regular_client):
    response = regular_client.post(RULES_URL, {"strategy": "compete", "sku": "ENT-1"}, format="json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_create_rule_sku_scope_ok(admin_client):
    response = admin_client.post(RULES_URL, {"strategy": "compete", "sku": "ENT-1"}, format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "ENT-1"
    assert body["mode"] == "suggestion"
    assert PricingRule.objects.filter(sku="ENT-1").count() == 1


@pytest.mark.django_db
def test_create_rule_channel_scope_ok(admin_client, decision_fixture):
    response = admin_client.post(RULES_URL, {"strategy": "raise", "channel": "ch1"}, format="json")
    assert response.status_code == 201
    assert response.json()["channel"] == "ch1"


@pytest.mark.django_db
def test_create_rule_exactly_one_scope_violation_400(admin_client, decision_fixture):
    response = admin_client.post(RULES_URL, {"strategy": "compete", "sku": "ENT-1", "channel": "ch1"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_create_rule_no_scope_violation_400(admin_client):
    response = admin_client.post(RULES_URL, {"strategy": "compete"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_create_rule_unknown_channel_400(admin_client):
    response = admin_client.post(RULES_URL, {"strategy": "compete", "channel": "no-such-channel"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_retrieve_rule_requires_auth(api_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = api_client.get(f"{RULES_URL}{rule.pk}/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_retrieve_rule_forbidden_for_regular_user(regular_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = regular_client.get(f"{RULES_URL}{rule.pk}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_retrieve_rule_not_found_404(admin_client):
    response = admin_client.get(f"{RULES_URL}999999/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_update_rule_requires_auth(api_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = api_client.patch(f"{RULES_URL}{rule.pk}/", {"strategy": "raise"}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_update_rule_forbidden_for_regular_user(regular_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = regular_client.patch(f"{RULES_URL}{rule.pk}/", {"strategy": "raise"}, format="json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_update_rule_ok(admin_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = admin_client.patch(f"{RULES_URL}{rule.pk}/", {"strategy": "raise", "price_war": True}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "raise"
    assert body["price_war"] is True


@pytest.mark.django_db
def test_update_rule_not_found_404(admin_client):
    response = admin_client.patch(f"{RULES_URL}999999/", {"strategy": "raise"}, format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_rule_requires_auth(api_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = api_client.delete(f"{RULES_URL}{rule.pk}/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_delete_rule_forbidden_for_regular_user(regular_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = regular_client.delete(f"{RULES_URL}{rule.pk}/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_rule_ok(admin_client):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    response = admin_client.delete(f"{RULES_URL}{rule.pk}/")
    assert response.status_code == 204
    assert admin_client.get(f"{RULES_URL}{rule.pk}/").status_code == 404


@pytest.mark.django_db
def test_delete_rule_not_found_404(admin_client):
    response = admin_client.delete(f"{RULES_URL}999999/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_pricing_rule_service_whitelist_rejects_unknown_field(db):
    rule = PricingRule.objects.create(sku="ENT-1", strategy="compete")
    with pytest.raises(ValueError, match="not editable"):
        pricing_rule_service.update_rule(rule=rule, updates={"applied_by": "someone"})
    with pytest.raises(ValueError, match="not editable"):
        pricing_rule_service.create_rule({"sku": "ENT-2", "strategy": "compete", "applied_by": "someone"})
