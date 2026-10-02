from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EvidenceState

ZERO = Decimal("0")


class RevenueAdapterKind(StrEnum):
    FIXED_MONTHLY = "fixed_monthly"
    PER_EVENT = "per_event"
    USAGE = "usage"
    REVENUE_SHARE = "revenue_share"


class RevenueAdapterBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    adapter_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    enabled: bool = True
    evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    note: str | None = None
    included_in_core: bool = False


class FixedMonthlyRevenueAdapter(RevenueAdapterBase):
    kind: Literal["fixed_monthly"] = "fixed_monthly"
    monthly_revenue: Decimal = Field(default=ZERO, ge=0)
    monthly_direct_cost: Decimal = Field(default=ZERO, ge=0)


class PerEventRevenueAdapter(RevenueAdapterBase):
    kind: Literal["per_event"] = "per_event"
    events_per_day: Decimal = Field(default=ZERO, ge=0)
    days_per_month: Decimal = Field(default=Decimal("30.4166667"), gt=0)
    revenue_per_event: Decimal = Field(default=ZERO, ge=0)
    direct_cost_per_event: Decimal = Field(default=ZERO, ge=0)


class UsageRevenueAdapter(RevenueAdapterBase):
    """Usage/event adapter for assets such as chargers, machines or kiosks."""

    kind: Literal["usage"] = "usage"
    events_per_day: Decimal = Field(default=ZERO, ge=0)
    days_per_month: Decimal = Field(default=Decimal("30.4166667"), gt=0)
    units_per_event: Decimal = Field(default=ZERO, ge=0)
    revenue_per_unit: Decimal = Field(default=ZERO, ge=0)
    direct_cost_per_unit: Decimal = Field(default=ZERO, ge=0)
    revenue_per_event: Decimal = Field(default=ZERO, ge=0)
    direct_cost_per_event: Decimal = Field(default=ZERO, ge=0)


class RevenueShareAdapter(RevenueAdapterBase):
    kind: Literal["revenue_share"] = "revenue_share"
    external_gross_revenue_monthly: Decimal = Field(default=ZERO, ge=0)
    share_rate: Decimal = Field(default=ZERO, ge=0, le=1)
    monthly_direct_cost: Decimal = Field(default=ZERO, ge=0)


RevenueAdapterConfig = Annotated[
    FixedMonthlyRevenueAdapter
    | PerEventRevenueAdapter
    | UsageRevenueAdapter
    | RevenueShareAdapter,
    Field(discriminator="kind"),
]


class RevenueAdapterSet(BaseModel):
    adapters: list[RevenueAdapterConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def adapter_ids_are_unique(self) -> "RevenueAdapterSet":
        ids = [adapter.adapter_id for adapter in self.adapters]
        duplicates = sorted({adapter_id for adapter_id in ids if ids.count(adapter_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate revenue adapter_id(s): {', '.join(duplicates)}")
        return self


class RevenueStreamResult(BaseModel):
    adapter_id: str
    label: str
    entity_id: str
    kind: RevenueAdapterKind
    evidence_state: EvidenceState
    enabled: bool
    gross_revenue_monthly: Decimal = Field(ge=0)
    direct_cost_monthly: Decimal = Field(ge=0)
    contribution_monthly: Decimal
    blocked: bool = False
    note: str | None = None
    included_in_core: bool = False


class RevenueEntitySummary(BaseModel):
    entity_id: str
    gross_revenue_monthly: Decimal = ZERO
    direct_cost_monthly: Decimal = ZERO
    contribution_monthly: Decimal = ZERO
    included_streams: int = 0
    blocked_streams: int = 0
    disabled_streams: int = 0


Handler = Callable[[RevenueAdapterConfig], RevenueStreamResult]


class RevenueAdapterEngine:
    """Pluggable revenue-layer engine with strict entity ownership.

    Adapters translate an operational driver or contract into an entity-owned
    revenue stream. They never mutate core business economics and summaries are
    kept per entity so separate books remain separate.
    """

    def __init__(self) -> None:
        self._handlers: dict[RevenueAdapterKind, Handler] = {
            RevenueAdapterKind.FIXED_MONTHLY: self._run_fixed_monthly,
            RevenueAdapterKind.PER_EVENT: self._run_per_event,
            RevenueAdapterKind.USAGE: self._run_usage,
            RevenueAdapterKind.REVENUE_SHARE: self._run_revenue_share,
        }

    def register(self, kind: RevenueAdapterKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    def run(self, adapter: RevenueAdapterConfig) -> RevenueStreamResult:
        kind = RevenueAdapterKind(adapter.kind)
        # Evidence state takes precedence over the UI enable switch. A blocked
        # item must remain visibly blocked even if it is temporarily disabled.
        if adapter.evidence_state == EvidenceState.BLOCKED:
            return self._zero(adapter, kind, blocked=True)
        if not adapter.enabled:
            return self._zero(adapter, kind, blocked=False)
        result = self._handlers[kind](adapter)
        if result.adapter_id != adapter.adapter_id:
            raise ValueError("Revenue adapter handler cannot change adapter_id")
        if result.label != adapter.label:
            raise ValueError("Revenue adapter handler cannot change adapter label")
        if result.entity_id != adapter.entity_id:
            raise ValueError("Revenue adapter handler cannot change entity_id / accounting owner")
        if result.kind != kind:
            raise ValueError("Revenue adapter handler cannot change adapter kind")
        if result.evidence_state != adapter.evidence_state:
            raise ValueError("Revenue adapter handler cannot change evidence_state")
        if result.enabled != adapter.enabled:
            raise ValueError("Revenue adapter handler cannot change enabled state")
        if result.included_in_core != adapter.included_in_core:
            raise ValueError("Revenue adapter handler cannot change included_in_core")
        if result.contribution_monthly != (
            result.gross_revenue_monthly - result.direct_cost_monthly
        ):
            raise ValueError("Revenue adapter contribution must equal gross revenue minus direct cost")
        if result.blocked and (
            result.gross_revenue_monthly != ZERO
            or result.direct_cost_monthly != ZERO
            or result.contribution_monthly != ZERO
        ):
            raise ValueError("Blocked revenue adapter results must be zero-valued")
        return result

    def run_many(self, adapters: list[RevenueAdapterConfig]) -> list[RevenueStreamResult]:
        return [self.run(adapter) for adapter in adapters]

    def summarize_by_entity(
        self, results: list[RevenueStreamResult]
    ) -> list[RevenueEntitySummary]:
        buckets: dict[str, dict[str, Decimal | int]] = defaultdict(
            lambda: {
                "gross": ZERO,
                "cost": ZERO,
                "contribution": ZERO,
                "included": 0,
                "blocked": 0,
                "disabled": 0,
            }
        )
        for result in results:
            bucket = buckets[result.entity_id]
            bucket["gross"] += result.gross_revenue_monthly
            bucket["cost"] += result.direct_cost_monthly
            bucket["contribution"] += result.contribution_monthly
            if result.blocked:
                bucket["blocked"] += 1
            elif not result.enabled:
                bucket["disabled"] += 1
            else:
                bucket["included"] += 1

        return [
            RevenueEntitySummary(
                entity_id=entity_id,
                gross_revenue_monthly=bucket["gross"],
                direct_cost_monthly=bucket["cost"],
                contribution_monthly=bucket["contribution"],
                included_streams=int(bucket["included"]),
                blocked_streams=int(bucket["blocked"]),
                disabled_streams=int(bucket["disabled"]),
            )
            for entity_id, bucket in sorted(buckets.items())
        ]

    @staticmethod
    def _zero(
        adapter: RevenueAdapterConfig, kind: RevenueAdapterKind, blocked: bool
    ) -> RevenueStreamResult:
        return RevenueStreamResult(
            adapter_id=adapter.adapter_id,
            label=adapter.label,
            entity_id=adapter.entity_id,
            kind=kind,
            evidence_state=adapter.evidence_state,
            enabled=adapter.enabled,
            gross_revenue_monthly=ZERO,
            direct_cost_monthly=ZERO,
            contribution_monthly=ZERO,
            blocked=blocked,
            note=adapter.note,
            included_in_core=adapter.included_in_core,
        )

    def _result(
        self,
        adapter: RevenueAdapterConfig,
        kind: RevenueAdapterKind,
        revenue: Decimal,
        direct_cost: Decimal,
    ) -> RevenueStreamResult:
        return RevenueStreamResult(
            adapter_id=adapter.adapter_id,
            label=adapter.label,
            entity_id=adapter.entity_id,
            kind=kind,
            evidence_state=adapter.evidence_state,
            enabled=adapter.enabled,
            gross_revenue_monthly=revenue,
            direct_cost_monthly=direct_cost,
            contribution_monthly=revenue - direct_cost,
            blocked=False,
            note=adapter.note,
            included_in_core=adapter.included_in_core,
        )

    def _run_fixed_monthly(self, adapter: RevenueAdapterConfig) -> RevenueStreamResult:
        assert isinstance(adapter, FixedMonthlyRevenueAdapter)
        return self._result(
            adapter,
            RevenueAdapterKind.FIXED_MONTHLY,
            adapter.monthly_revenue,
            adapter.monthly_direct_cost,
        )

    def _run_per_event(self, adapter: RevenueAdapterConfig) -> RevenueStreamResult:
        assert isinstance(adapter, PerEventRevenueAdapter)
        monthly_events = adapter.events_per_day * adapter.days_per_month
        return self._result(
            adapter,
            RevenueAdapterKind.PER_EVENT,
            monthly_events * adapter.revenue_per_event,
            monthly_events * adapter.direct_cost_per_event,
        )

    def _run_usage(self, adapter: RevenueAdapterConfig) -> RevenueStreamResult:
        assert isinstance(adapter, UsageRevenueAdapter)
        monthly_events = adapter.events_per_day * adapter.days_per_month
        revenue_per_event = (
            adapter.units_per_event * adapter.revenue_per_unit + adapter.revenue_per_event
        )
        cost_per_event = (
            adapter.units_per_event * adapter.direct_cost_per_unit
            + adapter.direct_cost_per_event
        )
        return self._result(
            adapter,
            RevenueAdapterKind.USAGE,
            monthly_events * revenue_per_event,
            monthly_events * cost_per_event,
        )

    def _run_revenue_share(self, adapter: RevenueAdapterConfig) -> RevenueStreamResult:
        assert isinstance(adapter, RevenueShareAdapter)
        return self._result(
            adapter,
            RevenueAdapterKind.REVENUE_SHARE,
            adapter.external_gross_revenue_monthly * adapter.share_rate,
            adapter.monthly_direct_cost,
        )


class CombinedEntityResult(BaseModel):
    entity_id: str
    core_cash_result_monthly: Decimal
    adapter_contribution_monthly: Decimal
    total_cash_result_monthly: Decimal


def combine_core_with_adapter_summaries(
    core_cash_result: Decimal,
    core_entity_id: str,
    summaries: list[RevenueEntitySummary],
) -> CombinedEntityResult:
    """Combine only the core entity's adapter layer with its core cash result.

    Other entities remain separate by construction.
    """
    own = next((s for s in summaries if s.entity_id == core_entity_id), None)
    adapter_contribution = own.contribution_monthly if own else ZERO
    return CombinedEntityResult(
        entity_id=core_entity_id,
        core_cash_result_monthly=core_cash_result,
        adapter_contribution_monthly=adapter_contribution,
        total_cash_result_monthly=core_cash_result + adapter_contribution,
    )


def validate_adapter_owners(
    adapters: list[RevenueAdapterConfig], allowed_entity_ids: set[str]
) -> None:
    """Reject adapter owners that are not registered in the case entity list."""
    unknown = sorted({
        adapter.entity_id
        for adapter in adapters
        if adapter.entity_id not in allowed_entity_ids
    })
    if unknown:
        raise ValueError(f"Unknown revenue adapter owner entity_id(s): {', '.join(unknown)}")
