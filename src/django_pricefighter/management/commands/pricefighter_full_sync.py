# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.management.base import BaseCommand

from django_pricefighter.services import representation_sync_service


class Command(BaseCommand):
    help = "Full reconcile of ProductRepresentation from PIM for all pricefighter channels."

    def handle(self, *args, **options):
        result = representation_sync_service.full_sync()
        self.stdout.write(
            self.style.SUCCESS(f"Synced {result['synced']}, deactivated {result['deactivated']} products.")
        )
