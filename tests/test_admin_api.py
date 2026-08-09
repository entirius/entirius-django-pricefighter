# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API tests for django-pricefighter channels."""

import pytest

from django_pricefighter.models import Channel

CHANNELS_URL = "/api/pricefighter/v2/admin/channels/"
CHANNELS_SYNC_URL = "/api/pricefighter/v2/admin/channels/sync/"


@pytest.mark.django_db
def test_list_channels_requires_auth(api_client):
    response = api_client.get(CHANNELS_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_channels_forbidden_for_regular_user(regular_client):
    response = regular_client.get(CHANNELS_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_channels_ok_for_admin(admin_client):
    Channel.objects.create(idx="default-local", name="Default Local")
    Channel.objects.create(idx="default-europe", name="Default Europe")

    response = admin_client.get(CHANNELS_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    idxs = {row["idx"] for row in body["results"]}
    assert idxs == {"default-local", "default-europe"}


@pytest.mark.django_db
def test_list_channels_pagination_shape(admin_client):
    Channel.objects.create(idx="default-local", name="Default Local")
    Channel.objects.create(idx="default-europe", name="Default Europe")

    response = admin_client.get(CHANNELS_URL, {"page_size": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["next"] is not None
    assert body["previous"] is None

    second_page = admin_client.get(body["next"].replace("http://testserver", ""))
    assert second_page.status_code == 200
    assert second_page.json()["previous"] is not None


@pytest.mark.django_db
def test_sync_channels_requires_auth(api_client):
    response = api_client.post(CHANNELS_SYNC_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_sync_channels_forbidden_for_regular_user(regular_client):
    response = regular_client.post(CHANNELS_SYNC_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_sync_channels_ok_for_admin_without_pim_data(admin_client):
    response = admin_client.post(CHANNELS_SYNC_URL)
    assert response.status_code == 200
    assert response.json() == {"synced": 0}


@pytest.mark.django_db
def test_sync_channels_idempotent(admin_client, pim_channel_factory):
    pim_channel_factory("default-europe")

    first = admin_client.post(CHANNELS_SYNC_URL)
    second = admin_client.post(CHANNELS_SYNC_URL)

    assert first.json() == {"synced": 1}
    assert second.json() == {"synced": 1}
    assert Channel.objects.count() == 1
