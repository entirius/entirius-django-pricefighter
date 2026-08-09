# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schema for the apply report. Mirrors
apply_service.apply_batch()'s bucket dict 1:1 — the API never reinterprets it."""

from pydantic import BaseModel, Field


class ApplyResultItemResponse(BaseModel):
    sku: str = Field(description="Product SKU", examples=["ENT-D003"])
    channel: str = Field(description="PriceFighter channel idx", examples=["default-local"])
    country: str = Field(description="Market country ISO2 code", examples=["DE"])
    currency: str = Field(description="Market currency ISO3 code", examples=["USD"])
    expected_new_price: str = Field(description="Price the operator submitted", examples=["94.00"])
    reason: str = Field(description="Bucket reason code", examples=["ok"])


class ApplyReportResponse(BaseModel):
    applied: list[ApplyResultItemResponse] = Field(
        default_factory=list, description="Items written cleanly", examples=[[]]
    )
    clamped: list[ApplyResultItemResponse] = Field(
        default_factory=list, description="Items written but clamped by pricemanager's bounds guard", examples=[[]]
    )
    skipped: list[ApplyResultItemResponse] = Field(
        default_factory=list, description="Items not written — not actionable or rejected by precedence", examples=[[]]
    )
    failed: list[ApplyResultItemResponse] = Field(
        default_factory=list, description="Items not written — unknown sku/market or internal error", examples=[[]]
    )
    stale: list[ApplyResultItemResponse] = Field(
        default_factory=list,
        description="Items not written — expected_new_price no longer matches the recomputed decision",
        examples=[[]],
    )
