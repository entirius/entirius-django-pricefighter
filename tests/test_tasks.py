# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Celery task tests — flush_pending_sync consumer (Redis pipeline plumbing)."""

from unittest.mock import MagicMock, patch

import pytest

from django_pricefighter import tasks


def _make_redis_mock():
    redis_mock = MagicMock()
    redis_mock.set.return_value = True
    return redis_mock


def _setup_caches_mock(mock_caches, redis_mock):
    mock_caches.__getitem__.return_value.client.get_client.return_value = redis_mock


def _make_pipe_mock(redis_mock, members):
    pipe_mock = MagicMock()
    redis_mock.pipeline.return_value = pipe_mock
    pipe_mock.execute.return_value = [members, len(members)]
    return pipe_mock


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_reads_and_clears_pending_set(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"ENT-S001:default-europe"])

    tasks.flush_pending_sync()

    pipe_mock = redis_mock.pipeline.return_value
    pipe_mock.zrangebyscore.assert_called_once_with(tasks.PENDING_KEY, "-inf", "+inf")
    pipe_mock.delete.assert_called_once_with(tasks.PENDING_KEY)
    pipe_mock.execute.assert_called_once()


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_deletes_lock_key_after_flush(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"ENT-S001:default-europe"])

    tasks.flush_pending_sync()

    redis_mock.delete.assert_any_call(tasks.LOCK_KEY)


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_single_member_dispatches_sync_pair(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"ENT-S001:default-europe"])

    result = tasks.flush_pending_sync()

    mock_sync_service.sync_pair.assert_called_once_with("ENT-S001", "default-europe")
    assert result == {"success": True, "flushed": 1, "failed": 0}


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_multiple_members_dispatch_sync_pair_each(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"ENT-S001:default-europe", b"ENT-S002:default-local"])

    result = tasks.flush_pending_sync()

    assert mock_sync_service.sync_pair.call_count == 2
    mock_sync_service.sync_pair.assert_any_call("ENT-S001", "default-europe")
    mock_sync_service.sync_pair.assert_any_call("ENT-S002", "default-local")
    assert result["flushed"] == 2


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_empty_set_returns_zero_flushed_and_skips_sync(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [])

    result = tasks.flush_pending_sync()

    assert result == {"success": True, "flushed": 0, "failed": 0}
    mock_sync_service.sync_pair.assert_not_called()


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_malformed_member_without_colon_is_skipped(mock_caches, mock_sync_service):
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"INVALIDNOCOLON", b"ENT-S001:default-europe"])

    result = tasks.flush_pending_sync()

    mock_sync_service.sync_pair.assert_called_once_with("ENT-S001", "default-europe")
    assert result["flushed"] == 1


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_member_with_colon_in_sku_parsed_with_rsplit(mock_caches, mock_sync_service):
    """rsplit(':', 1) ensures only the last colon splits sku from channel_idx."""
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"BRAND:ENT-S001:default-europe"])

    tasks.flush_pending_sync()

    mock_sync_service.sync_pair.assert_called_once_with("BRAND:ENT-S001", "default-europe")


def test_retries_on_redis_unavailable():
    """self.retry() is called on Redis failure; outside a real Celery request it re-raises
    the original exception rather than a fresh Retry — either way, it must not pass silently."""
    with patch("django_pricefighter.tasks.caches") as mock_caches:
        mock_caches.__getitem__.side_effect = RuntimeError("Redis down")

        with pytest.raises(Exception):  # noqa: B017
            tasks.flush_pending_sync()


@pytest.mark.django_db
@patch("django_pricefighter.tasks.representation_sync_service")
@patch("django_pricefighter.tasks.caches")
def test_failed_pair_is_reenqueued_and_others_still_flush(mock_caches, mock_sync_service):
    """One bad pair must not lose the others, and must be re-enqueued for the next flush."""
    redis_mock = _make_redis_mock()
    _setup_caches_mock(mock_caches, redis_mock)
    _make_pipe_mock(redis_mock, [b"ENT-BAD:default-europe", b"ENT-S001:default-europe"])
    mock_sync_service.sync_pair.side_effect = [RuntimeError("boom"), None]

    result = tasks.flush_pending_sync()

    assert result == {"success": True, "flushed": 1, "failed": 1}
    redis_mock.zadd.assert_called_once()
    (pending_key, mapping), _ = redis_mock.zadd.call_args
    assert pending_key == tasks.PENDING_KEY
    assert "ENT-BAD:default-europe" in mapping


@pytest.mark.django_db
@patch("django_pricefighter.services.representation_sync_service.full_sync")
def test_full_sync_task_delegates_to_service(mock_full_sync):
    mock_full_sync.return_value = {"synced": 3, "deactivated": 1}

    result = tasks.full_sync()

    mock_full_sync.assert_called_once_with()
    assert result == {"synced": 3, "deactivated": 1}
