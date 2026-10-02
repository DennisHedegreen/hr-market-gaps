from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EvidenceState, GateState

ZERO = Decimal("0")
ONE = Decimal("1")


class BoundedJointProductScenario(BaseModel):
    """Generic bounded-sales + joint-product economic model.

    The model is intentionally domain-neutral. A source unit may be an animal,
    log, batch, harvest lot or any other shared input that yields both a primary
    saleable unit and secondary output that must find a real channel.

    `calibrated_other_weekly_costs` is an explicit bridge field for cases whose
    public surface exposes a break-even envelope but not yet the full cost
    decomposition. If volume moves away from `calibration_reference_sales_week`,
    results remain calculable but are flagged out-of-domain until the full cost
    model is ported.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    currency: str = Field(default="DKK", min_length=1, max_length=12)
    evidence_maturity: str = Field(default="UNSPECIFIED", min_length=1)

    sales_cap_per_open_day: Decimal = Field(gt=0)
    planned_sales_per_open_day: Decimal = Field(ge=0)
    opening_days_per_week: Decimal = Field(gt=0, le=7)
    sale_price_gross: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=ZERO, ge=0, lt=ONE)
    non_primary_cost_per_sale: Decimal = Field(default=ZERO, ge=0)

    saleable_primary_units_per_source_unit: Decimal = Field(gt=0)
    secondary_output_units_per_source_unit: Decimal = Field(ge=0)
    secondary_output_unit_label: str = Field(default="unit", min_length=1)
    secondary_net_contribution_per_unit: Decimal = Field(default=ZERO)
    secondary_channel_evidence_state: EvidenceState = EvidenceState.HYPOTHESIS

    calibrated_other_weekly_costs: Decimal = Field(default=ZERO, ge=0)
    calibration_reference_sales_week: Decimal = Field(gt=0)
    calibration_reference_required_secondary_per_unit: Decimal | None = Field(
        default=None, ge=0
    )
    calibration_evidence_state: EvidenceState = EvidenceState.FORMULA

    supplier_reference_payment_per_source_unit: Decimal = Field(default=ZERO, ge=0)
    supplier_payment_per_source_unit: Decimal = Field(default=ZERO, ge=0)
    supplier_incremental_obligation_cost_per_source_unit: Decimal | None = Field(
        default=None, ge=0
    )
    supplier_obligation_evidence_state: EvidenceState = EvidenceState.BLOCKED

    operator_count: int = Field(default=1, ge=1)
    human_time_target_hours_per_person_week: Decimal | None = Field(default=None, gt=0)
    observed_total_human_hours_week: Decimal | None = Field(default=None, ge=0)
    human_time_evidence_state: EvidenceState = EvidenceState.BLOCKED

    peak_throughput_target_per_hour: Decimal | None = Field(default=None, gt=0)
    observed_peak_throughput_per_hour: Decimal | None = Field(default=None, ge=0)
    throughput_evidence_state: EvidenceState = EvidenceState.DESIGN_TARGET

    coordination_failure_threshold_minutes_week: Decimal | None = Field(
        default=None, ge=0
    )
    observed_coordination_minutes_week: Decimal | None = Field(default=None, ge=0)
    coordination_evidence_state: EvidenceState = EvidenceState.BLOCKED

    source_url: str | None = None
    source_version: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "BoundedJointProductScenario":
        if self.planned_sales_per_open_day > self.sales_cap_per_open_day:
            raise ValueError("planned_sales_per_open_day cannot exceed the sales cap")
        return self


class JointProductResult(BaseModel):
    weekly_sales: Decimal
    utilisation_of_sales_cap: Decimal
    gross_menu_revenue_weekly: Decimal
    net_menu_revenue_weekly: Decimal
    non_primary_cost_weekly: Decimal
    source_units_required_weekly: Decimal
    secondary_output_weekly: Decimal
    secondary_contribution_weekly: Decimal
    total_economic_cost_weekly: Decimal
    economic_surplus_weekly: Decimal
    required_secondary_contribution_per_unit: Decimal | None
    supplier_gross_uplift_per_source_unit: Decimal
    supplier_gross_uplift_weekly: Decimal
    supplier_net_benefit_per_source_unit: Decimal | None
    supplier_uplift_offset_per_secondary_unit: Decimal | None
    calibration_in_domain: bool
    average_human_hours_per_operator_week: Decimal | None


class MarketGapGateResult(BaseModel):
    gate_id: str
    label: str
    state: GateState
    modeled_condition: bool | None = None
    note: str


class JointProductEngine:
    def run(self, s: BoundedJointProductScenario) -> JointProductResult:
        weekly_sales = s.planned_sales_per_open_day * s.opening_days_per_week
        max_weekly_sales = s.sales_cap_per_open_day * s.opening_days_per_week
        utilisation = weekly_sales / max_weekly_sales if max_weekly_sales > ZERO else ZERO

        gross_menu_revenue = weekly_sales * s.sale_price_gross
        # sale_price_gross is tax-inclusive; remove tax by dividing by (1 + rate).
        net_menu_revenue = gross_menu_revenue / (ONE + s.tax_rate)
        non_primary_cost = weekly_sales * s.non_primary_cost_per_sale

        source_units = weekly_sales / s.saleable_primary_units_per_source_unit
        secondary_output = source_units * s.secondary_output_units_per_source_unit
        secondary_contribution = (
            secondary_output * s.secondary_net_contribution_per_unit
        )

        total_cost = s.calibrated_other_weekly_costs + non_primary_cost
        surplus = net_menu_revenue + secondary_contribution - total_cost

        if secondary_output > ZERO:
            required_secondary = max(ZERO, total_cost - net_menu_revenue) / secondary_output
        else:
            required_secondary = None

        supplier_uplift_per_source = (
            s.supplier_payment_per_source_unit
            - s.supplier_reference_payment_per_source_unit
        )
        supplier_uplift_week = supplier_uplift_per_source * source_units

        if s.supplier_incremental_obligation_cost_per_source_unit is None:
            supplier_net_benefit = None
        else:
            supplier_net_benefit = (
                supplier_uplift_per_source
                - s.supplier_incremental_obligation_cost_per_source_unit
            )

        if secondary_output > ZERO:
            supplier_uplift_offset = supplier_uplift_week / secondary_output
        else:
            supplier_uplift_offset = None

        average_human_hours = None
        if s.observed_total_human_hours_week is not None:
            average_human_hours = (
                s.observed_total_human_hours_week / Decimal(s.operator_count)
            )

        return JointProductResult(
            weekly_sales=weekly_sales,
            utilisation_of_sales_cap=utilisation,
            gross_menu_revenue_weekly=gross_menu_revenue,
            net_menu_revenue_weekly=net_menu_revenue,
            non_primary_cost_weekly=non_primary_cost,
            source_units_required_weekly=source_units,
            secondary_output_weekly=secondary_output,
            secondary_contribution_weekly=secondary_contribution,
            total_economic_cost_weekly=total_cost,
            economic_surplus_weekly=surplus,
            required_secondary_contribution_per_unit=required_secondary,
            supplier_gross_uplift_per_source_unit=supplier_uplift_per_source,
            supplier_gross_uplift_weekly=supplier_uplift_week,
            supplier_net_benefit_per_source_unit=supplier_net_benefit,
            supplier_uplift_offset_per_secondary_unit=supplier_uplift_offset,
            calibration_in_domain=(weekly_sales == s.calibration_reference_sales_week),
            average_human_hours_per_operator_week=average_human_hours,
        )


class MarketGapGateEngine:
    """Keep model arithmetic separate from evidence claims.

    A hypothetical input may make the arithmetic clear, but it cannot promote a
    public Market Gaps gate to PASS without evidence in the corresponding state.
    """

    _EVIDENCE_STATES = {EvidenceState.FACT, EvidenceState.OBSERVED}

    def evaluate(
        self, s: BoundedJointProductScenario, r: JointProductResult
    ) -> list[MarketGapGateResult]:
        gates: list[MarketGapGateResult] = []

        k1_modeled = r.economic_surplus_weekly >= ZERO
        calibration_evidenced = (
            s.calibration_evidence_state in self._EVIDENCE_STATES
            and r.calibration_in_domain
        )
        if (
            s.secondary_channel_evidence_state in self._EVIDENCE_STATES
            and calibration_evidenced
        ):
            k1_state = GateState.PASS if k1_modeled else GateState.FAIL
            k1_note = (
                "Economic condition evaluated with observed/factual secondary-channel "
                "and cost-calibration evidence."
            )
        else:
            k1_state = GateState.INSUFFICIENT_EVIDENCE
            k1_note = (
                "The arithmetic can be stressed, but economic viability is not evidence-passed "
                "until the secondary channel is observed/factual and the cost calibration is "
                "both evidence-backed and in-domain."
            )
        gates.append(
            MarketGapGateResult(
                gate_id="K1",
                label="Economic viability",
                state=k1_state,
                modeled_condition=k1_modeled,
                note=k1_note,
            )
        )

        required = r.required_secondary_contribution_per_unit
        k2_modeled = (
            None
            if required is None
            else s.secondary_net_contribution_per_unit >= required
        )
        if k2_modeled is None:
            k2_state = GateState.BLOCKED
            k2_note = "No secondary output exists in the current scenario."
        elif (
            s.secondary_channel_evidence_state in self._EVIDENCE_STATES
            and calibration_evidenced
        ):
            k2_state = GateState.PASS if k2_modeled else GateState.FAIL
            k2_note = (
                "Secondary-channel contribution and the break-even calibration are both "
                "backed by observed/factual evidence."
            )
        else:
            k2_state = GateState.INSUFFICIENT_EVIDENCE
            k2_note = (
                "A modeled contribution is not proof that the secondary output can actually be "
                "sold at the required level; the channel and break-even calibration must both "
                "be evidence-backed and in-domain."
            )
        gates.append(
            MarketGapGateResult(
                gate_id="K2",
                label="Secondary absorption",
                state=k2_state,
                modeled_condition=k2_modeled,
                note=k2_note,
            )
        )

        k3_modeled = None
        if r.supplier_net_benefit_per_source_unit is not None:
            k3_modeled = r.supplier_net_benefit_per_source_unit > ZERO
        if (
            s.supplier_obligation_evidence_state in self._EVIDENCE_STATES
            and k3_modeled is not None
        ):
            k3_state = GateState.PASS if k3_modeled else GateState.FAIL
            k3_note = "Supplier incremental obligations are observed/factual."
        else:
            k3_state = GateState.INSUFFICIENT_EVIDENCE
            k3_note = "Gross supplier uplift is visible, but incremental supplier obligations are not yet evidenced."
        gates.append(
            MarketGapGateResult(
                gate_id="K3",
                label="Supplier net benefit",
                state=k3_state,
                modeled_condition=k3_modeled,
                note=k3_note,
            )
        )

        k4_modeled = None
        if (
            r.average_human_hours_per_operator_week is not None
            and s.human_time_target_hours_per_person_week is not None
        ):
            k4_modeled = (
                r.average_human_hours_per_operator_week
                <= s.human_time_target_hours_per_person_week
            )
        if s.human_time_evidence_state in self._EVIDENCE_STATES and k4_modeled is not None:
            k4_state = GateState.PASS if k4_modeled else GateState.FAIL
            k4_note = "Human time is backed by observed/factual work-hour evidence."
        else:
            k4_state = GateState.INSUFFICIENT_EVIDENCE
            k4_note = "No observed full workweek yet; prep, receiving, close, cleaning, admin and exceptions must count."
        gates.append(
            MarketGapGateResult(
                gate_id="K4",
                label="Human time",
                state=k4_state,
                modeled_condition=k4_modeled,
                note=k4_note,
            )
        )

        k5_modeled = None
        if (
            s.peak_throughput_target_per_hour is not None
            and s.observed_peak_throughput_per_hour is not None
        ):
            k5_modeled = (
                s.observed_peak_throughput_per_hour
                >= s.peak_throughput_target_per_hour
            )
        if s.throughput_evidence_state in self._EVIDENCE_STATES and k5_modeled is not None:
            k5_state = GateState.PASS if k5_modeled else GateState.FAIL
            k5_note = "Peak throughput is observed."
        else:
            k5_state = GateState.INSUFFICIENT_EVIDENCE
            k5_note = "Peak throughput is still a design/test target rather than observed service performance."
        gates.append(
            MarketGapGateResult(
                gate_id="K5",
                label="Quality / throughput",
                state=k5_state,
                modeled_condition=k5_modeled,
                note=k5_note,
            )
        )

        k6_modeled = None
        if (
            s.coordination_failure_threshold_minutes_week is not None
            and s.observed_coordination_minutes_week is not None
        ):
            k6_modeled = (
                s.observed_coordination_minutes_week
                <= s.coordination_failure_threshold_minutes_week
            )
        if s.coordination_evidence_state in self._EVIDENCE_STATES and k6_modeled is not None:
            k6_state = GateState.PASS if k6_modeled else GateState.FAIL
            k6_note = "Routine coordination load is observed."
        else:
            k6_state = GateState.INSUFFICIENT_EVIDENCE
            k6_note = "Routine owner coordination has not been observed in a live operating network."
        gates.append(
            MarketGapGateResult(
                gate_id="K6",
                label="Coordination",
                state=k6_state,
                modeled_condition=k6_modeled,
                note=k6_note,
            )
        )

        return gates
