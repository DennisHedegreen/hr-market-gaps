from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FundingRequirement(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    requirement_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    status: str = Field(min_length=1)
    note: str | None = None


class FundingSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="SEK", min_length=1, max_length=12)
    provider_entity_id: str | None = None
    recipient_entity_id: str | None = None
    restricted: bool = False
    status: str = Field(min_length=1)
    note: str | None = None


class FundingRisk(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    risk_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str = Field(min_length=1)


class FundingStack(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    funding_stack_id: str = Field(min_length=1)
    requirements: list[FundingRequirement] = Field(default_factory=list)
    sources: list[FundingSource] = Field(default_factory=list)
    risks: list[FundingRisk] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "FundingStack":
        requirement_ids = [item.requirement_id for item in self.requirements]
        source_ids = [item.source_id for item in self.sources]
        risk_ids = [item.risk_id for item in self.risks]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("risk_id values must be unique")
        return self
