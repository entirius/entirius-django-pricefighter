# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schema for PricingRule CRUD."""

from pydantic import BaseModel, Field


class PricingRuleResponse(BaseModel):
    id: int = Field(description="Primary key", examples=[1])
    strategy: str = Field(description="hold | compete | raise", examples=["compete"])
    mode: str = Field(description="suggestion | authoritative", examples=["suggestion"])
    price_war: bool = Field(description="True holds at floor instead of competing further down", examples=[False])
    sku: str | None = Field(None, description="Scope: sku, null unless this is the active scope", examples=["ENT-D003"])
    category_idx: str | None = Field(
        None, description="Scope: category idx, null unless this is the active scope", examples=[None]
    )
    channel: str | None = Field(
        None, description="Scope: channel idx, null unless this is the active scope", examples=[None]
    )


class PricingRuleListResponse(BaseModel):
    count: int = Field(description="Total number of rules", examples=[3])
    next: str | None = Field(None, description="URL of next page", examples=[None])
    previous: str | None = Field(None, description="URL of previous page", examples=[None])
    results: list[PricingRuleResponse] = Field(description="Page of pricing rules", examples=[[]])
