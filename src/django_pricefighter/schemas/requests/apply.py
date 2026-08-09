# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic request schemas for apply. Single and batch share one contract —
single is just a 1-item batch."""

from decimal import Decimal

from pydantic import BaseModel, Field


class MarketRequest(BaseModel):
    channel: str = Field(description="PriceFighter channel idx", examples=["default-local"])
    country: str = Field(description="Market country ISO2 code", examples=["DE"])
    currency: str = Field(description="Market currency ISO3 code", examples=["USD"])


class ApplyItemRequest(BaseModel):
    sku: str = Field(description="Product SKU", examples=["ENT-D003"])
    market: MarketRequest = Field(
        description="Exact market to write", examples=[{"channel": "default-local", "country": "DE", "currency": "USD"}]
    )
    expected_new_price: Decimal = Field(
        description="Suggested price the operator saw in preview — apply recomputes and rejects "
        "as 'stale' on any mismatch.",
        examples=["94.00"],
    )


class ApplyBatchRequest(BaseModel):
    items: list[ApplyItemRequest] = Field(
        min_length=1,
        max_length=1000,
        description="Apply items — a single apply is a 1-item list",
        examples=[
            [
                {
                    "sku": "ENT-D003",
                    "market": {"channel": "default-local", "country": "DE", "currency": "USD"},
                    "expected_new_price": "94.00",
                }
            ]
        ],
    )
