# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django_utils.models.base_model import BaseModel


class QuoteConfig(BaseModel):
    class Rounding(models.TextChoices):
        NONE = "none", "None"
        P99 = ".99", ".99"
        P95 = ".95", ".95"
        INT = "int", "Integer"

    ROUNDING_GRAIN = {
        Rounding.NONE: Decimal("0"),
        Rounding.P99: Decimal("1"),
        Rounding.P95: Decimal("1"),
        Rounding.INT: Decimal("1"),
    }

    currency = models.CharField(max_length=3)
    range_from = models.DecimalField(max_digits=10, decimal_places=2)
    range_to = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    band_dn = models.DecimalField(max_digits=10, decimal_places=2)
    band_up = models.DecimalField(max_digits=10, decimal_places=2)
    undercut = models.DecimalField(max_digits=10, decimal_places=2)
    headroom = models.DecimalField(max_digits=10, decimal_places=2)
    max_step = models.DecimalField(max_digits=10, decimal_places=2)
    rounding = models.CharField(max_length=10, choices=Rounding.choices, default=Rounding.NONE)

    class Meta:
        ordering = ["currency", "range_from"]
        verbose_name = "Quote Config"
        verbose_name_plural = "Quote Configs"

    def clean(self):
        errors = {}
        if self.band_dn is not None and self.undercut is not None and self.band_dn <= self.undercut:
            errors["band_dn"] = "band_dn must be greater than undercut."
        if self.band_up is not None and self.undercut is not None and self.band_up <= self.undercut:
            errors["band_up"] = "band_up must be greater than undercut."
        if self.undercut is not None:
            grain = self.ROUNDING_GRAIN.get(self.rounding, Decimal("0"))
            if grain > self.undercut:
                errors["rounding"] = f"rounding grain ({grain}) must not exceed undercut ({self.undercut})."
        if errors:
            raise ValidationError(errors)
        self._validate_range_contiguity()

    def _validate_range_contiguity(self) -> None:
        if self.currency is None or self.range_from is None:
            return
        siblings = list(QuoteConfig.objects.filter(currency=self.currency).exclude(pk=self.pk))
        rows = sorted([*siblings, self], key=lambda r: r.range_from)

        open_ended = [r for r in rows if r.range_to is None]
        if len(open_ended) > 1:
            raise ValidationError(f"Currency {self.currency}: only one open-ended range (range_to=None) allowed.")

        for prev, nxt in zip(rows, rows[1:]):  # noqa: B905 — deliberately unequal-length pairwise iteration
            if prev.range_to is None:
                raise ValidationError(f"Currency {self.currency}: an open-ended range must be the last one.")
            if nxt.range_from != prev.range_to:
                raise ValidationError(
                    f"Currency {self.currency}: gap/overlap between "
                    f"{prev.range_from}-{prev.range_to} and {nxt.range_from}-{nxt.range_to}."
                )

    def __str__(self) -> str:
        upper = self.range_to if self.range_to is not None else "∞"
        return f"{self.currency} {self.range_from}-{upper}"
