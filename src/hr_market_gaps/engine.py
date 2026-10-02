from __future__ import annotations

from decimal import Decimal
from math import ceil

from .models import AggregateScenario, CalculationBreakdown, CalculationTerm, ScenarioResult


D60 = Decimal("60")
ZERO = Decimal("0")


class DeterministicEngine:
    """Small generic v0.1 bridge engine.

    This intentionally implements only aggregate equations that are already
    unambiguous in the workpack. The full workbook semantics should be ported
    behind the same generic boundary before Python is declared canonical.
    """

    def run(self, s: AggregateScenario) -> ScenarioResult:
        activity_singular = s.activity_label[:-1] if s.activity_label.endswith("s") else s.activity_label
        monthly_visits = s.visits_per_day * s.days_per_month
        monthly_sales = monthly_visits * s.revenue_per_visit
        monthly_db1 = monthly_visits * s.db1_per_visit
        core_cash_result = monthly_db1 - s.fixed_overhead_monthly

        if s.db1_per_visit > ZERO:
            break_even = s.fixed_overhead_monthly / (s.db1_per_visit * s.days_per_month)
        else:
            break_even = None

        avg_orders_h = s.visits_per_day / s.opening_hours
        active_h = (
            s.visits_per_day * s.service_minutes_per_order / D60
            + s.background_active_hours_per_day
        )
        idle_min_h = max(ZERO, D60 - (active_h / s.opening_hours * D60))

        peak_service_minutes_h = (
            avg_orders_h * s.peak_multiplier * s.service_minutes_per_order
        )
        available_service_minutes_per_worker = D60 * s.comfort_utilisation
        peak_workers = (
            0
            if peak_service_minutes_h == ZERO
            else ceil(peak_service_minutes_h / available_service_minutes_per_worker)
        )

        return ScenarioResult(
            monthly_visits=monthly_visits,
            monthly_sales=monthly_sales,
            monthly_db1=monthly_db1,
            core_cash_result=core_cash_result,
            break_even_visits_per_day=break_even,
            average_orders_per_hour=avg_orders_h,
            active_labour_hours_per_day=active_h,
            average_idle_minutes_per_hour=idle_min_h,
            peak_comfort_workers=peak_workers,
            breakdowns={
                "monthly_sales": CalculationBreakdown(
                    label="Monthly gross sales",
                    formula=f"{s.activity_label}/day × operating days/month × revenue per {activity_singular}",
                    terms=[
                        CalculationTerm(label=f"{s.activity_label.title()}/day", value=s.visits_per_day, unit=s.activity_unit),
                        CalculationTerm(label="Operating days/month", value=s.days_per_month, unit="days/month"),
                        CalculationTerm(label=f"Revenue per {activity_singular}", value=s.revenue_per_visit, unit=s.currency),
                    ],
                    result=monthly_sales,
                    unit=s.currency,
                ),
                "monthly_db1": CalculationBreakdown(
                    label="Monthly contribution",
                    formula=f"{s.activity_label}/day × operating days/month × contribution per {activity_singular}",
                    terms=[
                        CalculationTerm(label=f"{s.activity_label.title()}/day", value=s.visits_per_day, unit=s.activity_unit),
                        CalculationTerm(label="Operating days/month", value=s.days_per_month, unit="days/month"),
                        CalculationTerm(label=f"Contribution per {activity_singular}", value=s.db1_per_visit, unit=s.currency),
                    ],
                    result=monthly_db1,
                    unit=s.currency,
                ),
                "core_cash_result": CalculationBreakdown(
                    label="Monthly core result",
                    formula="monthly contribution - fixed monthly overhead",
                    terms=[
                        CalculationTerm(label="Monthly contribution", value=monthly_db1, unit=s.currency),
                        CalculationTerm(label="Fixed monthly overhead", value=s.fixed_overhead_monthly, unit=s.currency),
                    ],
                    result=core_cash_result,
                    unit=s.currency,
                ),
                "break_even_visits_per_day": CalculationBreakdown(
                    label="Operating break-even",
                    formula=f"fixed monthly overhead ÷ contribution per {activity_singular} ÷ operating days/month",
                    terms=[
                        CalculationTerm(label="Fixed monthly overhead", value=s.fixed_overhead_monthly, unit=s.currency),
                        CalculationTerm(label=f"Contribution per {activity_singular}", value=s.db1_per_visit, unit=s.currency),
                        CalculationTerm(label="Operating days/month", value=s.days_per_month, unit="days/month"),
                    ],
                    result=break_even,
                    unit=s.activity_unit,
                ),
            },
        )
