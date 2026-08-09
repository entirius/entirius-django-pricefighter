# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.management.base import BaseCommand

from django_pricefighter.services import channel_sync_service


class Command(BaseCommand):
    help = "Sync pricefighter Channels from PIM Channel model."

    def handle(self, *args, **options):
        count = channel_sync_service.sync_channels_from_pim()
        self.stdout.write(self.style.SUCCESS(f"Synced {count} channels from PIM."))
