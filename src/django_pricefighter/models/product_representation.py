# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from django_utils.models.base_model import BaseModel


class ProductRepresentation(BaseModel):
    sku = models.CharField(max_length=128, db_index=True)
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=255, default="", blank=True)
    category = models.CharField(max_length=128, default="", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sku"]
        verbose_name_plural = "Product Representations"
        constraints = [UniqueConstraint(Lower("sku"), "channel", name="pricefighter_pr_sku_unique_in_channel")]

    def __str__(self) -> str:
        return self.sku
