# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schema for price bounds."""

from pydantic import BaseModel, Field


class BoundsResponse(BaseModel):
    sku: str = Field(description="Product SKU", examples=["ENT-D003"])
    channel_idx: str = Field(description="PriceFighter channel identifier", examples=["default-local"])
    country: str = Field(description="Market country ISO2 code", examples=["DE"])
    floor: str | None = Field(None, description="Price floor (max of MAP and cost-based floor)", examples=["75.00"])
    ceiling: str | None = Field(None, description="Price ceiling (always null in v1)", examples=[None])
    baseline: str | None = Field(None, description="Baseline reference price (cost x markup)", examples=["100.00"])
