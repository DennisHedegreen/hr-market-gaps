from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemandSource(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str = Field(min_length=1)


class FunnelStep(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    step_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str = Field(min_length=1)
    note: str = Field(min_length=1)


class DemandSurface(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    demand_surface_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    sources: list[DemandSource] = Field(min_length=1)
    funnel: list[FunnelStep] = Field(min_length=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "DemandSurface":
        source_ids = [source.source_id for source in self.sources]
        step_ids = [step.step_id for step in self.funnel]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        return self
