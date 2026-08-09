# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schemas for PriceDecision history."""

from pydantic import BaseModel, ConfigDict, Field


class PriceDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Primary key", examples=[1])
    sku: str = Field(description="Product SKU", examples=["ENT-D003"])
    channel_idx: str = Field(description="PriceFighter channel identifier", examples=["default-local"])
    country: str = Field(description="Market country ISO2 code", examples=["DE"])
    currency: str = Field(description="Market currency ISO3 code", examples=["USD"])
    old_price: str = Field(description="Price before this decision", examples=["99.99"])
    new_price: str = Field(description="Price after this decision", examples=["94.00"])
    strategy: str = Field(description="compete | raise | revert_baseline | hold_at_floor", examples=["compete"])
    mode: str = Field(description="Resolved PricingRule mode at apply time", examples=["suggestion"])
    applied_by: str | None = Field(
        None, description="Email of the applying admin, null if unset", examples=["admin@test.local"]
    )
    reason: dict = Field(
        description="Full input snapshot (R, B, floor, P, gaps, estimator, observations)",
        examples=[{"reference_price": "95.00", "no_action_reason": "ok"}],
    )
    created_at: str = Field(description="Decision timestamp (ISO 8601)", examples=["2026-07-18T10:00:00Z"])


class PriceDecisionListResponse(BaseModel):
    count: int = Field(description="Total number of decisions", examples=[12])
    next: str | None = Field(None, description="URL of next page", examples=[None])
    previous: str | None = Field(None, description="URL of previous page", examples=[None])
    results: list[PriceDecisionResponse] = Field(description="Page of price decisions", examples=[[]])
