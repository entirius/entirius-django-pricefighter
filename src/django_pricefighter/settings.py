# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.conf import settings

# Engine config — deployment tunes to its own feed cadence, dev ships placeholders.
# Estimator for the competitor reference price R from a batch of valid observations.
PRICEFIGHTER_REF_ESTIMATOR = getattr(settings, "PRICEFIGHTER_REF_ESTIMATOR", "min")  # min | second_best | median
# Observation max age (days) before it's dropped as stale — align with the feed's own interval.
PRICEFIGHTER_STALENESS_DAYS = getattr(settings, "PRICEFIGHTER_STALENESS_DAYS", 3)
# PriceDecision retention (days) — purge-only beat.
PRICEFIGHTER_DECISION_RETENTION_DAYS = getattr(settings, "PRICEFIGHTER_DECISION_RETENTION_DAYS", 365)
