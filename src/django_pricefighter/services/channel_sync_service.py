# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Channel management and sync service."""

import logging

from django.db.models import QuerySet

from django_pricefighter.models import Channel

logger = logging.getLogger(__name__)


def list_channels() -> QuerySet[Channel]:
    """Return all pricefighter channels."""
    return Channel.objects.select_related("default_language").prefetch_related("languages").all()


def serialize_channel(channel: Channel) -> dict:
    """Build a plain dict of a Channel's response fields (no schema import — avoids API->service coupling)."""
    return {
        "id": channel.pk,
        "idx": channel.idx,
        "name": channel.name,
        "default_language_iso2": (channel.default_language.iso2 if channel.default_language else None),
        "language_codes": [lang.iso2 for lang in channel.languages.all()],
    }


def sync_channels_from_pim() -> int:
    """Sync pricefighter Channels from PIM Channel model.

    Creates or updates local channels keyed by idx.
    Returns count of synced channels.
    """
    try:
        from django_pim.models import Channel as PimChannel
    except ImportError:
        logger.info("django_pim not installed, skipping channel sync")
        return 0

    from django_regional.models import Language

    count = 0
    for pim_channel in PimChannel.objects.prefetch_related("languages").all():
        local_lang = None
        if pim_channel.default_language:
            local_lang = Language.objects.filter(iso2__iexact=pim_channel.default_language.iso2).first()

        pf_channel, _ = Channel.objects.update_or_create(
            idx=pim_channel.idx, defaults={"name": pim_channel.name, "default_language": local_lang}
        )

        pim_lang_iso2s = list(pim_channel.languages.values_list("iso2", flat=True))
        local_langs = Language.objects.filter(iso2__in=pim_lang_iso2s)
        pf_channel.languages.set(local_langs)

        count += 1

    return count
