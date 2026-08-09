# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schemas for the decision view.

Serializes decision_view_service.DecisionRow / quote_engine.EngineDecision. Decimals are
serialized as `str` (never a raw JSON float) — matches pricemanager's response convention.
"""

from pydantic import BaseModel, ConfigDict, Field


class DecisionObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_idx: str = Field(description="Monitoring source identifier", examples=["mon-1"])
    price: str = Field(description="Observed price", examples=["79.99"])
    currency: str | None = Field(None, description="Observed currency ISO3 code", examples=["USD"])
    stock: int | None = Field(None, description="Observed stock, null if the feed didn't report it", examples=[5])
    ts: str = Field(description="Observation timestamp (ISO 8601)", examples=["2026-07-18T10:00:00Z"])
    is_trusted: bool = Field(description="Whether the source is marked trusted", examples=[True])
    flag: str = Field(
        description="Filter outcome: valid | stale | untrusted | oos | currency_mismatch", examples=["valid"]
    )


class DecisionListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str = Field(description="Product SKU", examples=["ENT-D003"])
    name: str = Field(description="Product name (denormalized)", examples=["Widget D003"])
    channel_idx: str = Field(description="PriceFighter channel identifier", examples=["default-local"])
    country: str = Field(description="Market country ISO2 code", examples=["DE"])
    currency: str = Field(description="Market currency ISO3 code", examples=["USD"])
    current_price: str = Field(description="Current gross price (P)", examples=["99.99"])
    current_price_net: str = Field(description="Current net price", examples=["84.03"])
    cost: str | None = Field(None, description="Purchase cost, null if unset", examples=["60.00"])
    floor: str | None = Field(None, description="Price floor (F)", examples=["75.00"])
    baseline: str | None = Field(None, description="Baseline reference price (B)", examples=["100.00"])
    reference_price: str | None = Field(None, description="Competitor reference price (R)", examples=["95.00"])
    estimator: str = Field(description="Estimator used for R: min | second_best | median", examples=["min"])
    gap_baseline: str | None = Field(None, description="R - baseline", examples=["-5.00"])
    gap_current: str | None = Field(None, description="R - current price (informational)", examples=["-4.99"])
    margin: str | None = Field(None, description="Net margin percent vs cost", examples=["28.57"])
    recommendation: str = Field(
        description="compete | raise | hold | revert_baseline | hold_at_floor | no_recommendation", examples=["compete"]
    )
    suggested_price: str | None = Field(None, description="Suggested target price (T)", examples=["94.00"])
    reason: str = Field(description="Machine-readable reason code", examples=["ok"])
    strategy: str = Field(description="Resolved PricingRule strategy", examples=["compete"])
    mode: str = Field(description="Resolved PricingRule mode", examples=["suggestion"])
    price_war: bool = Field(description="Resolved PricingRule price_war flag", examples=[False])
    clamped_floor: bool = Field(False, description="True if suggested_price was clamped to floor", examples=[False])
    clamped_step: bool = Field(False, description="True if suggested_price was clamped by max_step", examples=[False])


class DecisionDetailResponse(DecisionListItemResponse):
    observations: list[DecisionObservationResponse] = Field(
        default_factory=list, description="Full observation list, including filtered-out entries", examples=[[]]
    )


class DecisionListResponse(BaseModel):
    count: int = Field(description="Total number of decision rows", examples=[42])
    next: str | None = Field(None, description="URL of next page", examples=[None])
    previous: str | None = Field(None, description="URL of previous page", examples=[None])
    results: list[DecisionListItemResponse] = Field(description="Page of decision rows", examples=[[]])
