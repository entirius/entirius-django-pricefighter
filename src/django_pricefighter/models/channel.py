# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from django_utils.models.base_model import BaseModel


class Channel(BaseModel):
    idx = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=128, default="", blank=True)
    default_language = models.ForeignKey(
        "django_regional.Language",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pricefighter_default_channels",
    )
    languages = models.ManyToManyField("django_regional.Language", blank=True, related_name="pricefighter_channels")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.idx
