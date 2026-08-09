# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django_utils.models.base_model import BaseModel


class PricingRule(BaseModel):
    class Strategy(models.TextChoices):
        HOLD = "hold", "Hold"
        COMPETE = "compete", "Compete"
        RAISE = "raise", "Raise"

    class Mode(models.TextChoices):
        SUGGESTION = "suggestion", "Suggestion"
        AUTHORITATIVE = "authoritative", "Authoritative"

    strategy = models.CharField(max_length=10, choices=Strategy.choices, default=Strategy.HOLD)
    price_war = models.BooleanField(default=False)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.SUGGESTION)

    # Scope — exactly one of the three must be set (most-specific-wins: sku > category > channel).
    # NULL (not "") on purpose: the CheckConstraint below needs a real tri-state per scope field.
    sku = models.CharField(max_length=128, null=True, blank=True, default=None)  # noqa: DJ001
    category_idx = models.CharField(max_length=128, null=True, blank=True, default=None)  # noqa: DJ001
    channel = models.ForeignKey(
        "Channel", on_delete=models.CASCADE, null=True, blank=True, related_name="pricing_rules"
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(sku__isnull=False) & Q(category_idx__isnull=True) & Q(channel__isnull=True))
                    | (Q(sku__isnull=True) & Q(category_idx__isnull=False) & Q(channel__isnull=True))
                    | (Q(sku__isnull=True) & Q(category_idx__isnull=True) & Q(channel__isnull=False))
                ),
                name="pricefighter_pricingrule_exactly_one_scope",
            )
        ]

    def clean(self):
        self.sku = self.sku or None
        self.category_idx = self.category_idx or None
        scopes_set = sum(1 for v in (self.sku, self.category_idx, self.channel_id) if v)
        if scopes_set != 1:
            raise ValidationError("Exactly one of sku, category_idx, channel must be set.")

    def __str__(self) -> str:
        scope = self.sku or self.category_idx or (self.channel.idx if self.channel_id else "?")
        return f"{scope} → {self.strategy}"
