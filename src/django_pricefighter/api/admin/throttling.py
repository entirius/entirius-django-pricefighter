# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Throttling for the apply endpoint. Apply is expensive (recomputes the full
decision + writes through pricemanager) and admin-authenticated, so this keys per-user
(UserRateThrottle), not per-IP.
"""

from django.core.exceptions import ImproperlyConfigured
from rest_framework.throttling import UserRateThrottle


class ApplyThrottle(UserRateThrottle):
    """Configure via ``DEFAULT_THROTTLE_RATES["pricefighter_apply"]``. NOT a class-level
    ``rate`` — DRF's ``SimpleRateThrottle.__init__`` skips ``get_rate()`` entirely when
    ``rate`` is set, which would make the settings override dead. ``fallback_rate`` is a
    30/hour safety net so this endpoint is never left unthrottled by a missing setting.
    """

    scope = "pricefighter_apply"
    fallback_rate = "30/hour"

    def __init__(self) -> None:
        self.rate = self.get_rate()
        super().__init__()

    def get_rate(self) -> str:
        try:
            rate = super().get_rate()
        except ImproperlyConfigured:  # scope missing from DEFAULT_THROTTLE_RATES
            return self.fallback_rate
        if not rate or "/" not in rate:  # malformed rate must not disable throttling
            return self.fallback_rate
        return rate
