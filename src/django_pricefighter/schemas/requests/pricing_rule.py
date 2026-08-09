# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic request schemas for PricingRule CRUD."""

from pydantic import BaseModel, Field


class PricingRuleCreateRequest(BaseModel):
    strategy: str = Field(description="hold | compete | raise", examples=["compete"])
    mode: str = Field("suggestion", description="suggestion | authoritative", examples=["suggestion"])
    price_war: bool = Field(
        False, description="True holds at floor instead of competing further down", examples=[False]
    )
    sku: str | None = Field(None, description="Scope: exactly one of sku/category_idx/channel", examples=["ENT-D003"])
    category_idx: str | None = Field(None, description="Scope: PIM category idx", examples=["cat-electronics"])
    channel: str | None = Field(None, description="Scope: PriceFighter channel idx", examples=["default-local"])


class PricingRuleUpdateRequest(BaseModel):
    strategy: str | None = Field(None, description="hold | compete | raise", examples=["compete"])
    mode: str | None = Field(None, description="suggestion | authoritative", examples=["suggestion"])
    price_war: bool | None = Field(
        None, description="True holds at floor instead of competing further down", examples=[False]
    )
    sku: str | None = Field(None, description="Scope: exactly one of sku/category_idx/channel", examples=["ENT-D003"])
    category_idx: str | None = Field(None, description="Scope: PIM category idx", examples=["cat-electronics"])
    channel: str | None = Field(None, description="Scope: PriceFighter channel idx", examples=["default-local"])
