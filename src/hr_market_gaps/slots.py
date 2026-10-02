from __future__ import annotations

from collections import defaultdict
from datetime import time
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EvidenceState

ZERO = Decimal("0")
D60 = Decimal("60")
MINUTES_PER_DAY = 24 * 60
DAYS_PER_MONTH_FROM_WEEKS = Decimal("52") / Decimal("12")


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


WEEKDAY_ORDER = [
    Weekday.MON,
    Weekday.TUE,
    Weekday.WED,
    Weekday.THU,
    Weekday.FRI,
    Weekday.SAT,
    Weekday.SUN,
]
WEEKDAY_INDEX = {day: index for index, day in enumerate(WEEKDAY_ORDER)}


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


def _duration_minutes(start: time, end: time) -> int:
    start_minute = _minute_of_day(start)
    end_minute = _minute_of_day(end)
    if start_minute == end_minute:
        raise ValueError("start_time and end_time cannot be identical; split a 24h slot")
    if end_minute > start_minute:
        return end_minute - start_minute
    return MINUTES_PER_DAY - start_minute + end_minute


class OperatingSlot(BaseModel):
    """A recurring right to operate one shared productive asset in time.

    `monthly_site_payment` is intentionally generic: it can represent rent,
    a cooperative infrastructure fee, or another payment from the operator to
    the site entity. Unknown commercial terms remain BLOCKED and are excluded
    from financial concentration calculations.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    slot_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    operator_entity_id: str = Field(min_length=1)
    weekdays: list[Weekday] = Field(min_length=1)
    start_time: time
    end_time: time
    enabled: bool = True
    evidence_state: EvidenceState = EvidenceState.HYPOTHESIS
    minimum_staff_on_duty: int = Field(default=1, ge=0)
    team_size: int = Field(default=1, ge=1)
    prep_minutes_per_operating_day: Decimal = Field(default=ZERO, ge=0)
    handover_minutes_per_operating_day: Decimal = Field(default=ZERO, ge=0)
    monthly_site_payment: Decimal = Field(default=ZERO, ge=0)
    payment_evidence_state: EvidenceState = EvidenceState.BLOCKED
    note: str | None = None

    @model_validator(mode="after")
    def validate_slot(self) -> "OperatingSlot":
        if len(self.weekdays) != len(set(self.weekdays)):
            raise ValueError(f"slot {self.slot_id}: weekdays must be unique")
        for field_name, value in (("start_time", self.start_time), ("end_time", self.end_time)):
            if value.second != 0 or value.microsecond != 0:
                raise ValueError(
                    f"slot {self.slot_id}: {field_name} must use minute precision; "
                    "seconds would otherwise be silently discarded"
                )
        _duration_minutes(self.start_time, self.end_time)
        return self

    @property
    def duration_hours(self) -> Decimal:
        return Decimal(_duration_minutes(self.start_time, self.end_time)) / D60

    @property
    def operating_days_per_week(self) -> int:
        return len(self.weekdays)


class OperatingSchedule(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    site_entity_id: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    capacity_hours_per_week: Decimal = Field(default=Decimal("168"), gt=0, le=168)
    shared_site_cost_monthly: Decimal = Field(default=ZERO, ge=0)
    shared_site_cost_evidence_state: EvidenceState = EvidenceState.BLOCKED
    slots: list[OperatingSlot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_schedule(self) -> "OperatingSchedule":
        slot_ids = [slot.slot_id for slot in self.slots]
        duplicates = sorted({slot_id for slot_id in slot_ids if slot_ids.count(slot_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate operating slot_id(s): {', '.join(duplicates)}")

        if not self.entity_ids:
            self.entity_ids = sorted(
                {self.site_entity_id, *(slot.operator_entity_id for slot in self.slots)}
            )
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("entity_ids must be unique")
        if self.site_entity_id not in self.entity_ids:
            raise ValueError("site_entity_id must be present in entity_ids")

        unknown_operators = sorted(
            {
                slot.operator_entity_id
                for slot in self.slots
                if slot.operator_entity_id not in self.entity_ids
            }
        )
        if unknown_operators:
            raise ValueError(
                "Unknown slot operator entity_id(s): " + ", ".join(unknown_operators)
            )

        foreign_assets = sorted(
            {slot.asset_id for slot in self.slots if slot.asset_id != self.asset_id}
        )
        if foreign_assets:
            raise ValueError(
                "All slots in one schedule must target asset_id "
                f"{self.asset_id}; found: {', '.join(foreign_assets)}"
            )

        self._validate_no_overlaps()
        return self

    def _validate_no_overlaps(self) -> None:
        intervals: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
        for slot in self.slots:
            if not slot.enabled or slot.evidence_state == EvidenceState.BLOCKED:
                continue
            start = _minute_of_day(slot.start_time)
            end = _minute_of_day(slot.end_time)
            for weekday in slot.weekdays:
                day_index = WEEKDAY_INDEX[weekday]
                if end > start:
                    intervals[day_index].append((start, end, slot.slot_id))
                else:
                    intervals[day_index].append((start, MINUTES_PER_DAY, slot.slot_id))
                    if end > 0:
                        intervals[(day_index + 1) % 7].append((0, end, slot.slot_id))

        for day_index, day_intervals in intervals.items():
            day_intervals.sort(key=lambda item: (item[0], item[1], item[2]))
            max_end = -1
            active_slot: str | None = None
            for current in day_intervals:
                if current[0] < max_end:
                    day = WEEKDAY_ORDER[day_index].value
                    raise ValueError(
                        "Operating slot overlap on "
                        f"{day}: {active_slot} overlaps {current[2]}"
                    )
                if current[1] > max_end:
                    max_end = current[1]
                    active_slot = current[2]


class SlotResult(BaseModel):
    slot_id: str
    label: str
    operator_entity_id: str
    enabled: bool
    evidence_state: EvidenceState
    schedule_blocked: bool
    hours_per_week: Decimal
    required_person_hours_per_week: Decimal
    average_required_hours_per_team_member_week: Decimal
    staffing_feasible: bool
    monthly_site_payment_known: Decimal
    payment_blocked: bool


class OperatorSlotSummary(BaseModel):
    operator_entity_id: str
    slot_count: int
    hours_per_week: Decimal
    occupied_time_share: Decimal
    required_person_hours_per_week: Decimal
    known_site_payments_monthly: Decimal
    blocked_payment_slots: int


class SitePortfolioResult(BaseModel):
    schedule_id: str
    asset_id: str
    site_entity_id: str
    capacity_hours_per_week: Decimal
    occupied_hours_per_week: Decimal
    occupancy_rate: Decimal
    operator_count: int
    largest_operator_time_share: Decimal
    time_concentration_hhi: Decimal
    effective_operator_count_by_time: Decimal | None
    surviving_occupied_share_if_largest_operator_lost: Decimal
    surviving_capacity_occupancy_if_largest_operator_lost: Decimal
    known_site_payments_monthly: Decimal
    payment_concentration_hhi: Decimal | None
    largest_operator_payment_share: Decimal | None
    effective_operator_count_by_payment: Decimal | None
    blocked_payment_slots: int
    site_cash_result_monthly: Decimal | None
    site_cash_result_blocked: bool
    slot_results: list[SlotResult]
    operator_summaries: list[OperatorSlotSummary]


class OperatingSlotEngine:
    """Deterministic shared-asset/time-slot engine.

    It models the productive asset separately from each operator. Time-based
    concentration can be calculated without inventing commercial terms;
    owner-side financial concentration is only calculated when every enabled
    slot payment and the shared site cost are evidenced rather than BLOCKED.
    """

    def run(self, schedule: OperatingSchedule) -> SitePortfolioResult:
        slot_results: list[SlotResult] = []
        operator_hours: dict[str, Decimal] = defaultdict(lambda: ZERO)
        operator_person_hours: dict[str, Decimal] = defaultdict(lambda: ZERO)
        operator_payments: dict[str, Decimal] = defaultdict(lambda: ZERO)
        operator_slot_counts: dict[str, int] = defaultdict(int)
        operator_blocked_payments: dict[str, int] = defaultdict(int)

        for slot in schedule.slots:
            schedule_blocked = slot.evidence_state == EvidenceState.BLOCKED
            if not slot.enabled or schedule_blocked:
                slot_results.append(
                    SlotResult(
                        slot_id=slot.slot_id,
                        label=slot.label,
                        operator_entity_id=slot.operator_entity_id,
                        enabled=slot.enabled,
                        evidence_state=slot.evidence_state,
                        schedule_blocked=schedule_blocked,
                        hours_per_week=ZERO,
                        required_person_hours_per_week=ZERO,
                        average_required_hours_per_team_member_week=ZERO,
                        staffing_feasible=slot.team_size >= slot.minimum_staff_on_duty,
                        monthly_site_payment_known=ZERO,
                        payment_blocked=slot.payment_evidence_state == EvidenceState.BLOCKED,
                    )
                )
                continue

            hours_per_week = slot.duration_hours * Decimal(slot.operating_days_per_week)
            service_person_hours = hours_per_week * Decimal(slot.minimum_staff_on_duty)
            support_minutes_per_week = (
                slot.prep_minutes_per_operating_day
                + slot.handover_minutes_per_operating_day
            ) * Decimal(slot.operating_days_per_week)
            required_person_hours = service_person_hours + support_minutes_per_week / D60
            hours_per_team_member = required_person_hours / Decimal(slot.team_size)
            payment_blocked = slot.payment_evidence_state == EvidenceState.BLOCKED
            known_payment = ZERO if payment_blocked else slot.monthly_site_payment

            slot_results.append(
                SlotResult(
                    slot_id=slot.slot_id,
                    label=slot.label,
                    operator_entity_id=slot.operator_entity_id,
                    enabled=True,
                    evidence_state=slot.evidence_state,
                    schedule_blocked=False,
                    hours_per_week=hours_per_week,
                    required_person_hours_per_week=required_person_hours,
                    average_required_hours_per_team_member_week=hours_per_team_member,
                    staffing_feasible=slot.team_size >= slot.minimum_staff_on_duty,
                    monthly_site_payment_known=known_payment,
                    payment_blocked=payment_blocked,
                )
            )

            operator_slot_counts[slot.operator_entity_id] += 1
            operator_hours[slot.operator_entity_id] += hours_per_week
            operator_person_hours[slot.operator_entity_id] += required_person_hours
            operator_payments[slot.operator_entity_id] += known_payment
            if payment_blocked:
                operator_blocked_payments[slot.operator_entity_id] += 1

        occupied_hours = sum(operator_hours.values(), ZERO)
        if occupied_hours > schedule.capacity_hours_per_week:
            raise ValueError(
                "Occupied hours exceed schedule capacity; check capacity_hours_per_week"
            )
        occupancy_rate = occupied_hours / schedule.capacity_hours_per_week

        if occupied_hours > ZERO:
            time_shares = {
                operator: hours / occupied_hours for operator, hours in operator_hours.items()
            }
            largest_time_share = max(time_shares.values())
            time_hhi = sum((share * share for share in time_shares.values()), ZERO)
            effective_by_time = (Decimal("1") / time_hhi) if time_hhi > ZERO else None
        else:
            time_shares = {}
            largest_time_share = ZERO
            time_hhi = ZERO
            effective_by_time = None

        surviving_occupied_share = (
            Decimal("1") - largest_time_share if occupied_hours > ZERO else ZERO
        )
        largest_operator_hours = (
            max(operator_hours.values()) if operator_hours else ZERO
        )
        surviving_capacity_occupancy = (
            occupied_hours - largest_operator_hours
        ) / schedule.capacity_hours_per_week

        blocked_payment_slots = sum(operator_blocked_payments.values())
        known_site_payments = sum(operator_payments.values(), ZERO)
        financials_complete = (
            blocked_payment_slots == 0
            and schedule.shared_site_cost_evidence_state != EvidenceState.BLOCKED
        )

        if financials_complete and known_site_payments > ZERO:
            payment_shares = {
                operator: payment / known_site_payments
                for operator, payment in operator_payments.items()
                if payment > ZERO
            }
            largest_payment_share = max(payment_shares.values()) if payment_shares else ZERO
            payment_hhi = sum((share * share for share in payment_shares.values()), ZERO)
            effective_by_payment = (
                Decimal("1") / payment_hhi if payment_hhi > ZERO else None
            )
        elif financials_complete:
            largest_payment_share = ZERO
            payment_hhi = ZERO
            effective_by_payment = None
        else:
            largest_payment_share = None
            payment_hhi = None
            effective_by_payment = None

        site_cash_result = (
            known_site_payments - schedule.shared_site_cost_monthly
            if financials_complete
            else None
        )

        operator_summaries = [
            OperatorSlotSummary(
                operator_entity_id=operator,
                slot_count=operator_slot_counts[operator],
                hours_per_week=hours,
                occupied_time_share=(hours / occupied_hours if occupied_hours > ZERO else ZERO),
                required_person_hours_per_week=operator_person_hours[operator],
                known_site_payments_monthly=operator_payments[operator],
                blocked_payment_slots=operator_blocked_payments[operator],
            )
            for operator, hours in sorted(operator_hours.items())
        ]

        return SitePortfolioResult(
            schedule_id=schedule.schedule_id,
            asset_id=schedule.asset_id,
            site_entity_id=schedule.site_entity_id,
            capacity_hours_per_week=schedule.capacity_hours_per_week,
            occupied_hours_per_week=occupied_hours,
            occupancy_rate=occupancy_rate,
            operator_count=len(operator_hours),
            largest_operator_time_share=largest_time_share,
            time_concentration_hhi=time_hhi,
            effective_operator_count_by_time=effective_by_time,
            surviving_occupied_share_if_largest_operator_lost=surviving_occupied_share,
            surviving_capacity_occupancy_if_largest_operator_lost=surviving_capacity_occupancy,
            known_site_payments_monthly=known_site_payments,
            payment_concentration_hhi=payment_hhi,
            largest_operator_payment_share=largest_payment_share,
            effective_operator_count_by_payment=effective_by_payment,
            blocked_payment_slots=blocked_payment_slots,
            site_cash_result_monthly=site_cash_result,
            site_cash_result_blocked=not financials_complete,
            slot_results=slot_results,
            operator_summaries=operator_summaries,
        )
