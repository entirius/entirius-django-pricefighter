# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic response schemas for pricefighter channels."""

from pydantic import BaseModel, ConfigDict, Field


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Primary key", examples=[1])
    idx: str = Field(description="Channel identifier", examples=["default-europe"])
    name: str = Field(description="Channel display name", examples=["Default Europe"])
    default_language_iso2: str | None = Field(None, description="Default language ISO2 code", examples=["en"])
    language_codes: list[str] = Field(
        default_factory=list, description="Available language ISO2 codes", examples=[["en", "de", "pl"]]
    )


class ChannelListResponse(BaseModel):
    count: int = Field(description="Total number of channels", examples=[2])
    next: str | None = Field(
        None,
        description="URL of next page",
        examples=["http://localhost:8000/api/pricefighter/v2/admin/channels/?page=2"],
    )
    previous: str | None = Field(None, description="URL of previous page", examples=[None])
    results: list[ChannelResponse] = Field(
        description="List of channels",
        examples=[
            [
                {
                    "id": 1,
                    "idx": "default-europe",
                    "name": "Default Europe",
                    "default_language_iso2": "en",
                    "language_codes": ["en"],
                }
            ]
        ],
    )
