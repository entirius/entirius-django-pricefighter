# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Celery tasks — consumer side of the pim:pricefighter:* signal tor + cron full-sync."""

import logging
import time
from datetime import timedelta

from celery import shared_task
from django.core.cache import caches
from django.utils import timezone

from django_pricefighter import settings as pf_settings
from django_pricefighter.services import representation_sync_service

logger = logging.getLogger(__name__)

PENDING_KEY = "pim:pricefighter:pending"
LOCK_KEY = "pim:pricefighter:flush_scheduled"


@shared_task(name="pricefighter.flush_pending_sync", bind=True, max_retries=3)
def flush_pending_sync(self):
    """Drain the Redis debounce set and sync each pending sku×channel pair.

    A pair that fails to sync is re-enqueued into the pending set instead of being dropped —
    the pending set is already drained by the time the loop runs, so a lost failure here would
    only be caught by the next day's cron full_sync.
    """
    try:
        redis_client = caches["default"].client.get_client()
    except Exception as exc:
        logger.warning("Redis unavailable during flush: %s", exc)
        raise self.retry(exc=exc) from exc

    pipe = redis_client.pipeline()
    pipe.zrangebyscore(PENDING_KEY, "-inf", "+inf")
    pipe.delete(PENDING_KEY)
    results = pipe.execute()
    members = results[0]

    redis_client.delete(LOCK_KEY)
    redis_client.set("pim:pricefighter:last_flush", str(time.time()), ex=86400)

    if not members:
        return {"success": True, "flushed": 0, "failed": 0}

    flushed = 0
    failed = 0
    for member in members:
        if isinstance(member, bytes):
            member = member.decode("utf-8")
        parts = member.rsplit(":", 1)
        if len(parts) != 2:
            continue
        sku, channel_idx = parts
        try:
            representation_sync_service.sync_pair(sku, channel_idx)
            flushed += 1
        except Exception:
            failed += 1
            logger.exception("Failed to sync sku=%s channel=%s, re-enqueuing", sku, channel_idx)
            redis_client.zadd(PENDING_KEY, {member: time.time()})
            redis_client.expire(PENDING_KEY, 300)

    return {"success": True, "flushed": flushed, "failed": failed}


@shared_task(name="pricefighter.full_sync")
def full_sync():
    """Full reconcile of all channels/products — cron safeguard against signal drift."""
    return representation_sync_service.full_sync()


@shared_task(name="pricefighter.prune_decisions")
def prune_decisions() -> int:
    """Purge-only retention for PriceDecision — audit log, not the price itself (that stays
    in pricemanager's PriceHistory). Returns the number of rows deleted."""
    from django_pricefighter.models import PriceDecision

    cutoff = timezone.now() - timedelta(days=pf_settings.PRICEFIGHTER_DECISION_RETENTION_DAYS)
    deleted, _ = PriceDecision.objects.filter(created_at__lt=cutoff).delete()
    return deleted
