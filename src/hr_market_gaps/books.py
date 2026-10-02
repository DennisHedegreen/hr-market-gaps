from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from .costs import FixedCostSet
from .contracts import RentComparisonScenario
from .models import AggregateScenario
from .product import CoreIncomeMode, ProductCatalog, ProductMixEngine, ProductMixResult
from .revenue import (
    RevenueAdapterEngine,
    RevenueAdapterSet,
    RevenueStreamResult,
    validate_adapter_owners,
)

ZERO = Decimal("0")


class BookLineKind(StrEnum):
    CORE_CONTRIBUTION = "core_contribution"
    ADAPTER_CONTRIBUTION = "adapter_contribution"
    EXTERNAL_COST = "external_cost"
    INTERNAL_TRANSFER_OUT = "internal_transfer_out"
    INTERNAL_TRANSFER_IN = "internal_transfer_in"


class EntityBookLine(BaseModel):
    line_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    kind: BookLineKind
    amount_monthly: Decimal
    counterparty_entity_id: str | None = None
    source_cost_id: str | None = None


class EntityBookSummary(BaseModel):
    entity_id: str = Field(min_length=1)
    inflows_monthly: Decimal = ZERO
    outflows_monthly: Decimal = ZERO
    result_monthly: Decimal = ZERO
    lines: list[EntityBookLine] = Field(default_factory=list)


class InternalTransferResult(BaseModel):
    cost_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    payer_entity_id: str = Field(min_length=1)
    recipient_entity_id: str = Field(min_length=1)
    amount_monthly: Decimal = Field(ge=0)


class SiteBooksResult(BaseModel):
    entity_books: list[EntityBookSummary]
    consolidated_result_monthly: Decimal
    external_costs_monthly: Decimal = Field(ge=0)
    internal_transfers_monthly: Decimal = Field(ge=0)
    transfers: list[InternalTransferResult] = Field(default_factory=list)
    unresolved_cost_ids: list[str] = Field(default_factory=list)
    unresolved_income_fields: list[str] = Field(default_factory=list)
    product_mix_result: ProductMixResult | None = None
    adapter_results: list[RevenueStreamResult] = Field(default_factory=list)
    adapter_contribution_monthly: Decimal = ZERO

    def book_for(self, entity_id: str) -> EntityBookSummary:
        return next(book for book in self.entity_books if book.entity_id == entity_id)


class EntityBooksEngine:
    """Build separate entity books and eliminate internal site transfers."""

    def run(
        self,
        scenario: AggregateScenario,
        costs: FixedCostSet,
        revenue_adapters: RevenueAdapterSet | None = None,
        product_catalog: ProductCatalog | None = None,
    ) -> SiteBooksResult:
        entity_ids = set(scenario.entity_ids)
        lines: dict[str, list[EntityBookLine]] = defaultdict(list)
        unresolved: list[str] = []
        unresolved_income: list[str] = []
        transfers: list[InternalTransferResult] = []
        external_costs = ZERO
        internal_transfers = ZERO

        product_mix_result: ProductMixResult | None = None
        income_owner = scenario.core_entity_id
        income_line_id = "legacy_grill_mix"
        income_label = "Legacy grill mix contribution"
        monthly_contribution = (
            scenario.visits_per_day * scenario.days_per_month * scenario.db1_per_visit
        )
        if (
            product_catalog is not None
            and product_catalog.income_mode == CoreIncomeMode.PRODUCT_MIX
        ):
            if product_catalog.entity_id not in entity_ids:
                raise ValueError(
                    f"Unknown product mix owner entity_id: {product_catalog.entity_id}"
                )
            product_mix_result = ProductMixEngine().run(product_catalog)
            unresolved_income = product_mix_result.unresolved_fields
            monthly_contribution = (
                product_mix_result.contribution_monthly
                if product_mix_result.complete
                else ZERO
            )
            income_owner = product_catalog.entity_id
            income_line_id = f"adapter:{product_catalog.adapter_id}"
            income_label = "Product mix contribution"

        lines[income_owner].append(
            EntityBookLine(
                line_id=income_line_id,
                label=income_label,
                entity_id=income_owner,
                kind=BookLineKind.CORE_CONTRIBUTION,
                amount_monthly=monthly_contribution,
            )
        )

        adapter_results: list[RevenueStreamResult] = []
        adapter_contribution = ZERO
        if revenue_adapters is not None:
            validate_adapter_owners(revenue_adapters.adapters, entity_ids)
            adapter_results = RevenueAdapterEngine().run_many(revenue_adapters.adapters)
            for adapter_result in adapter_results:
                if adapter_result.included_in_core:
                    continue
                amount = adapter_result.contribution_monthly
                adapter_contribution += amount
                if amount != ZERO:
                    lines[adapter_result.entity_id].append(
                        EntityBookLine(
                            line_id=f"adapter:{adapter_result.adapter_id}",
                            label=adapter_result.label,
                            entity_id=adapter_result.entity_id,
                            kind=BookLineKind.ADAPTER_CONTRIBUTION,
                            amount_monthly=amount,
                        )
                    )

        for cost in costs.cost_objects:
            if not cost.active:
                continue
            if cost.owner_entity_id not in entity_ids:
                raise ValueError(f"Unknown cost owner entity_id: {cost.owner_entity_id}")
            if cost.payer_entity_id not in entity_ids:
                raise ValueError(f"Unknown cost payer entity_id: {cost.payer_entity_id}")

            amount = cost.effective_monthly_amount(scenario.visits_per_day)
            if amount is None:
                unresolved.append(cost.cost_id)
                continue
            if amount == ZERO:
                continue
            recipient_is_internal = cost.recipient_entity_id in entity_ids
            if recipient_is_internal and cost.recipient_entity_id == cost.payer_entity_id:
                raise ValueError("An internal transfer cannot have the same payer and recipient")

            out_kind = (
                BookLineKind.INTERNAL_TRANSFER_OUT
                if recipient_is_internal
                else BookLineKind.EXTERNAL_COST
            )
            lines[cost.payer_entity_id].append(
                EntityBookLine(
                    line_id=f"cost:{cost.cost_id}:out",
                    label=cost.label,
                    entity_id=cost.payer_entity_id,
                    kind=out_kind,
                    amount_monthly=-amount,
                    counterparty_entity_id=cost.recipient_entity_id,
                    source_cost_id=cost.cost_id,
                )
            )

            if recipient_is_internal:
                assert cost.recipient_entity_id is not None
                lines[cost.recipient_entity_id].append(
                    EntityBookLine(
                        line_id=f"cost:{cost.cost_id}:in",
                        label=cost.label,
                        entity_id=cost.recipient_entity_id,
                        kind=BookLineKind.INTERNAL_TRANSFER_IN,
                        amount_monthly=amount,
                        counterparty_entity_id=cost.payer_entity_id,
                        source_cost_id=cost.cost_id,
                    )
                )
                internal_transfers += amount
                transfers.append(
                    InternalTransferResult(
                        cost_id=cost.cost_id,
                        label=cost.label,
                        payer_entity_id=cost.payer_entity_id,
                        recipient_entity_id=cost.recipient_entity_id,
                        amount_monthly=amount,
                    )
                )
            else:
                external_costs += amount

        books = []
        for entity_id in scenario.entity_ids:
            entity_lines = lines[entity_id]
            inflows = sum(
                (line.amount_monthly for line in entity_lines if line.amount_monthly > ZERO),
                ZERO,
            )
            outflows = -sum(
                (line.amount_monthly for line in entity_lines if line.amount_monthly < ZERO),
                ZERO,
            )
            books.append(
                EntityBookSummary(
                    entity_id=entity_id,
                    inflows_monthly=inflows,
                    outflows_monthly=outflows,
                    result_monthly=inflows - outflows,
                    lines=entity_lines,
                )
            )

        consolidated = monthly_contribution + adapter_contribution - external_costs
        if sum((book.result_monthly for book in books), ZERO) != consolidated:
            raise ValueError("Entity books do not reconcile to the consolidated site result")

        return SiteBooksResult(
            entity_books=books,
            consolidated_result_monthly=consolidated,
            external_costs_monthly=external_costs,
            internal_transfers_monthly=internal_transfers,
            transfers=transfers,
            unresolved_cost_ids=unresolved,
            unresolved_income_fields=unresolved_income,
            product_mix_result=product_mix_result,
            adapter_results=adapter_results,
            adapter_contribution_monthly=adapter_contribution,
        )


class RentComparisonResult(BaseModel):
    scenario_id: str
    label: str
    kind: str
    revenue_share_rate: Decimal | None = None
    property_service_credit_monthly: Decimal | None = None
    recipient_total_value_monthly: Decimal | None = None
    effective_rent_monthly: Decimal = Field(ge=0)
    operator_result_monthly: Decimal
    recipient_result_monthly: Decimal
    consolidated_result_monthly: Decimal
    operator_break_even_visits_per_day: Decimal | None
    status: str
    note: str | None = None
    unresolved_cost_ids: list[str] = Field(default_factory=list)


class RentComparisonEngine:
    """Compare rent structures without mutating the active case package."""

    def run_many(
        self,
        scenario: AggregateScenario,
        costs: FixedCostSet,
        comparisons: list[RentComparisonScenario],
        rent_cost_id: str = "site_rent",
        revenue_adapters: RevenueAdapterSet | None = None,
    ) -> list[RentComparisonResult]:
        return [
            self.run(scenario, costs, item, rent_cost_id, revenue_adapters)
            for item in comparisons
        ]

    def run(
        self,
        scenario: AggregateScenario,
        costs: FixedCostSet,
        comparison: RentComparisonScenario,
        rent_cost_id: str = "site_rent",
        revenue_adapters: RevenueAdapterSet | None = None,
    ) -> RentComparisonResult:
        working = costs.model_copy(deep=True)
        rent_cost = next(
            (cost for cost in working.cost_objects if cost.cost_id == rent_cost_id),
            None,
        )
        if rent_cost is None:
            raise ValueError(f"Unknown rent cost object: {rent_cost_id}")
        if comparison.payer_entity_id not in scenario.entity_ids:
            raise ValueError(f"Unknown rent payer: {comparison.payer_entity_id}")
        if comparison.recipient_entity_id not in scenario.entity_ids:
            raise ValueError(f"Unknown rent recipient: {comparison.recipient_entity_id}")

        rent_cost.active = True
        rent_cost.payer_entity_id = comparison.payer_entity_id
        rent_cost.recipient_entity_id = comparison.recipient_entity_id
        monthly_core_sales = (
            scenario.visits_per_day
            * scenario.days_per_month
            * scenario.revenue_per_visit
        )
        rent_cost.monthly_amount = comparison.effective_rent(
            scenario.visits_per_day,
            monthly_core_sales,
        )
        books = EntityBooksEngine().run(scenario, working, revenue_adapters)

        other_operator_costs = sum(
            (
                amount
                for cost in working.cost_objects
                if cost.active
                and cost.cost_id != rent_cost_id
                and cost.payer_entity_id == comparison.payer_entity_id
                and (
                    amount := cost.effective_monthly_amount(scenario.visits_per_day)
                ) is not None
            ),
            ZERO,
        )
        operator_adapter_contribution = sum(
            (
                result.contribution_monthly
                for result in books.adapter_results
                if result.entity_id == comparison.payer_entity_id
                and not result.included_in_core
            ),
            ZERO,
        )
        if scenario.db1_per_visit == ZERO:
            break_even = None
        else:
            divisor = scenario.db1_per_visit * scenario.days_per_month
            low_need = max(
                ZERO,
                other_operator_costs
                + comparison.base_rent_monthly
                - operator_adapter_contribution,
            )
            low_break_even = low_need / divisor
            if comparison.kind == "stepped" and comparison.stepped_rent_monthly is not None:
                high_need = max(
                    ZERO,
                    other_operator_costs
                    + comparison.stepped_rent_monthly
                    - operator_adapter_contribution,
                )
                high_break_even = high_need / divisor
                break_even = max(low_break_even, high_break_even)
            elif comparison.kind in {"turnover_share", "hybrid"}:
                assert comparison.revenue_share_rate is not None
                contribution_after_share = (
                    scenario.db1_per_visit
                    - scenario.revenue_per_visit * comparison.revenue_share_rate
                )
                if comparison.kind == "hybrid":
                    if contribution_after_share <= ZERO:
                        break_even = None
                    else:
                        break_even = low_need / (
                            contribution_after_share * scenario.days_per_month
                        )
                elif comparison.revenue_share_rate == ZERO:
                    break_even = low_break_even
                else:
                    share_threshold = comparison.base_rent_monthly / (
                        scenario.days_per_month
                        * scenario.revenue_per_visit
                        * comparison.revenue_share_rate
                    )
                    if low_break_even <= share_threshold:
                        break_even = low_break_even
                    elif contribution_after_share <= ZERO:
                        break_even = None
                    else:
                        share_need = max(
                            ZERO,
                            other_operator_costs - operator_adapter_contribution,
                        )
                        break_even = share_need / (
                            contribution_after_share * scenario.days_per_month
                        )
            else:
                break_even = low_break_even

        recipient_result = books.book_for(
            comparison.recipient_entity_id
        ).result_monthly
        recipient_total_value = (
            None
            if (
                comparison.kind == "service_credit"
                and comparison.property_service_credit_monthly is None
            )
            else (
                recipient_result
                + (comparison.property_service_credit_monthly or ZERO)
            )
        )
        return RentComparisonResult(
            scenario_id=comparison.scenario_id,
            label=comparison.label,
            kind=comparison.kind,
            revenue_share_rate=comparison.revenue_share_rate,
            property_service_credit_monthly=(
                comparison.property_service_credit_monthly
            ),
            recipient_total_value_monthly=recipient_total_value,
            effective_rent_monthly=rent_cost.monthly_amount,
            operator_result_monthly=books.book_for(comparison.payer_entity_id).result_monthly,
            recipient_result_monthly=recipient_result,
            consolidated_result_monthly=books.consolidated_result_monthly,
            operator_break_even_visits_per_day=break_even,
            status=comparison.status,
            note=comparison.note,
            unresolved_cost_ids=books.unresolved_cost_ids,
        )
