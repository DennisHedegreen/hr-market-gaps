from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import EvidenceState


class OperatingMode(StrEnum):
    DISCOVERY_PILOT = "discovery_pilot"
    SINGLE_OPERATOR = "single_operator"
    TIME_SLICED = "time_sliced"
    NETWORK_MARKET = "network_market"


class SiteDefinition(BaseModel):
    """A physical demand surface / productive asset.

    A site is deliberately not a business concept. Traffic, access, parking,
    building capacity and location-specific evidence belong here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    site_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    note: str | None = None


class ConceptDefinition(BaseModel):
    """A commercial concept that may be tested on one or more sites."""

    model_config = ConfigDict(str_strip_whitespace=True)

    concept_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    note: str | None = None


class OperatingModelDefinition(BaseModel):
    """How a concept/site is operated; may itself be a discovery instrument."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operating_model_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    mode: OperatingMode
    opening_hours_per_day: float | None = Field(default=None, ge=0, le=24)
    horizon_days: int | None = Field(default=None, ge=1)
    evidence_state: EvidenceState = EvidenceState.DESIGN_TARGET
    purpose: str | None = None
    note: str | None = None


class CaseComposition(BaseModel):
    """Explicit composition boundary: site != concept != operating model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    composition_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    concept_id: str = Field(min_length=1)
    operating_model_id: str = Field(min_length=1)
    revenue_layer_ids: list[str] = Field(default_factory=list)
    note: str | None = None
