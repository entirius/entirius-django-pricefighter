# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.conf import settings
from django.db import models
from django_utils.models.base_model import BaseModel


class PriceDecision(BaseModel):
    """Decision log — TWO logs, two purposes: PriceDecision (this model, own pricefighter)
    is the decision-level audit (strategy, snapshot of every input that produced it);
    PriceHistory (pricemanager) is the write-level audit of the resulting CurrentPrice row.
    A row is written ONLY at an explicit apply action (single or batch) — never at render.
    """

    class Strategy(models.TextChoices):
        COMPETE = "compete", "Compete"
        RAISE = "raise", "Raise"
        REVERT_BASELINE = "revert_baseline", "Revert to baseline"
        HOLD_AT_FLOOR = "hold_at_floor", "Hold at floor (price war)"

    representation = models.ForeignKey(
        "ProductRepresentation", on_delete=models.CASCADE, related_name="price_decisions"
    )
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="price_decisions")
    country = models.CharField(max_length=2)
    currency = models.CharField(max_length=3)

    old_price = models.DecimalField(max_digits=10, decimal_places=2)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)

    strategy = models.CharField(max_length=20, choices=Strategy.choices)
    mode = models.CharField(max_length=20)

    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=["representation"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["channel", "country", "currency"]),
        ]

    def __str__(self) -> str:
        return f"{self.representation.sku} {self.old_price}->{self.new_price} ({self.strategy})"
