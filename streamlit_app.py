from __future__ import annotations
from copy import deepcopy
import json
import re
import sys

from decimal import Decimal, InvalidOperation
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT / "src"))

import streamlit as st
from pydantic import ValidationError

from hr_market_gaps.case_package import (
    CasePackage,
    CasePackageError,
    dump_case_package_json,
    load_case_package_json,
)
from hr_market_gaps.case_package_v2 import (
    CaseCapability,
    CaseKind,
    CasePackageModules,
    CasePackageV2,
    CasePackageV2Error,
    CasePackageV2Metadata,
    dump_case_package_v2_json,
    load_case_package_v2_json,
)
from hr_market_gaps.assets import AssetDefinition, CapexPortfolioEngine
from hr_market_gaps.case_view import build_case_view
from hr_market_gaps.engine import DeterministicEngine
from hr_market_gaps.books import EntityBooksEngine, RentComparisonEngine
from hr_market_gaps.models import EvidenceState
from hr_market_gaps.costs import CostCalculationType, CostObject
from hr_market_gaps.contracts import (
    ContractScenario,
    ContractStructureKind,
    RentComparisonScenario,
)
from hr_market_gaps.product import (
    CoreIncomeMode,
    ProductItem,
    ProductMixEngine,
    ProductVolumeScenario,
)
from hr_market_gaps.composition import (
    CaseComposition,
    ConceptDefinition,
    OperatingMode,
    OperatingModelDefinition,
    SiteDefinition,
)
from hr_market_gaps.revenue import (
    FixedMonthlyRevenueAdapter,
    PerEventRevenueAdapter,
    RevenueShareAdapter,
    UsageRevenueAdapter,
)
from hr_market_gaps.tid_adapter import (
    TidAdapterError,
    build_public_case_packages,
)

PortablePackage = CasePackage | CasePackageV2



ROOT = APP_ROOT
TID_REGISTRY = ROOT / "public" / "market-gaps.json"
PACKAGE_STATE_KEY = "active_case_package"
PACKAGE_FILE_KEY = "active_case_filename"
PACKAGE_DIGEST_KEY = "active_case_digest"
PUBLIC_CASE_KEY = "active_public_case"


def money(value: Decimal, currency: str = "SEK") -> str:
    return f"{float(value):,.0f} {currency}"


def package_from_state() -> PortablePackage | None:
    raw = st.session_state.get(PACKAGE_STATE_KEY)
    if raw is None:
        return None
    if raw.get("schema_version") == 2:
        return CasePackageV2.model_validate(raw)
    return CasePackage.model_validate(raw)


def sync_package(package: PortablePackage) -> bool:
    try:
        model = CasePackageV2 if isinstance(package, CasePackageV2) else CasePackage
        validated = model.model_validate(package.model_dump(mode="json"))
    except ValidationError as exc:
        st.error(f"Case changes are not valid and were not saved: {exc.errors()[0]['msg']}")
        return False
    st.session_state[PACKAGE_STATE_KEY] = validated.model_dump(mode="json")
    return True


def case_module(package: PortablePackage, module_id: str):
    if isinstance(package, CasePackageV2):
        return getattr(package.modules, module_id)
    return getattr(package, module_id)


def optional_decimal(value: str, field_label: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"{field_label} must be a number or blank") from exc
    if parsed < 0:
        raise ValueError(f"{field_label} cannot be negative")
    return parsed


def safe_identifier(label: str, existing_ids: set[str], fallback: str) -> str:
    candidate = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or fallback
    if candidate not in existing_ids:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in existing_ids:
        suffix += 1
    return f"{candidate}_{suffix}"


def duplicate_identifier(identifier: str, existing_ids: set[str]) -> str:
    return safe_identifier(f"{identifier}_copy", existing_ids, "copy")


def import_package(uploaded_file) -> bool:
    payload = uploaded_file.getvalue()
    digest = f"{uploaded_file.name}:{len(payload)}:{hash(payload)}"
    if st.session_state.get(PACKAGE_DIGEST_KEY) == digest:
        return PACKAGE_STATE_KEY in st.session_state
    try:
        raw = json.loads(payload)
        if isinstance(raw, dict) and raw.get("schema_version") == 2:
            package = load_case_package_v2_json(payload)
        else:
            package = load_case_package_json(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        message = getattr(exc, "msg", str(exc))
        st.error(f"Case package is not valid JSON: {message}")
        return False
    except (
        CasePackageError,
        CasePackageV2Error,
    ) as exc:
        st.error(str(exc))
        return False
    if package.metadata.visibility.value == "PUBLIC":
        st.error(
            "Public packages open from the Market Gaps catalogue, not in the "
            "private editing workspace."
        )
        return False
    sync_package(package)
    st.session_state[PACKAGE_FILE_KEY] = uploaded_file.name
    st.session_state[PACKAGE_DIGEST_KEY] = digest
    return True


def render_import_control() -> None:
    uploaded = st.file_uploader(
        "Import case file",
        type=["json"],
        help="The file is processed in this hosted Streamlit session. It is not added to the public catalogue or source repository. Do not upload confidential data unless this hosting boundary is acceptable.",
        key="case-package-uploader",
    )
    if uploaded is not None and import_package(uploaded):
        package = package_from_state()
        assert package is not None
        st.success(f"Ready: {package.metadata.label}")
        if st.button("Open imported case", type="primary", width="stretch"):
            st.session_state["surface"] = "workspace"
            st.rerun()


def load_public_packages():
    try:
        return build_public_case_packages(ROOT, TID_REGISTRY)
    except TidAdapterError as exc:
        st.error(f"Public Market Gaps cases are unavailable: {exc}")
        return {}


def render_home() -> None:
    st.title("Hedegreen Research Market Gaps")
    st.caption("Interactive cases from the public Market Gaps register in TID.")

    left, right = st.columns([0.85, 1.15], gap="large")
    with left:
        st.subheader("Private workspace")
        render_import_control()
        st.divider()
        st.subheader("Create a case")
        st.write("Start a structured draft and add evidence as the case develops.")
        if st.button("New case", width="stretch"):
            st.session_state["surface"] = "new"
            st.rerun()
    with right:
        st.subheader("Public cases")
        packages = load_public_packages()
        for slug, package in packages.items():
            record = package.modules.public_record
            assert record is not None
            with st.container(border=True):
                st.markdown(f"**{record.title}**")
                status = record.status
                if record.maturity:
                    status = f"{record.maturity} · {status}"
                st.caption(status)
                st.write(record.summary)
                if st.button(
                    f"Open {record.title}",
                    key=f"open-public-{slug}",
                    width="stretch",
                ):
                    st.session_state[PUBLIC_CASE_KEY] = slug
                    st.session_state["surface"] = "public-case"
                    st.rerun()


def _metric_value(value: Decimal | None, unit: str) -> str:
    if value is None:
        return "Not available"
    formatted = f"{float(value):,.1f}"
    return f"{formatted} {unit}".strip()


def render_public_case() -> None:
    slug = st.session_state.get(PUBLIC_CASE_KEY)
    packages = load_public_packages()
    package = packages.get(slug)
    if package is None:
        st.session_state.pop(PUBLIC_CASE_KEY, None)
        st.session_state["surface"] = "home"
        st.rerun()
    assert package is not None

    if st.button("Back to Market Gaps"):
        st.session_state.pop(PUBLIC_CASE_KEY, None)
        st.session_state["surface"] = "home"
        st.rerun()

    view = build_case_view(package)
    st.title(view.title)
    state = view.status if view.maturity is None else f"{view.maturity} · {view.status}"
    st.caption(f"Public Market Gaps case · {state}")
    if view.summary:
        st.write(view.summary)

    for notice in view.notices:
        st.info(notice)

    if view.metrics:
        st.subheader("Model reading")
        columns = st.columns(min(4, len(view.metrics)))
        for index, metric in enumerate(view.metrics):
            columns[index % len(columns)].metric(
                metric.label,
                _metric_value(metric.value, metric.unit),
            )
        for metric in view.metrics:
            with st.expander(f"How calculated? {metric.label}"):
                st.write(metric.breakdown.formula)
                st.dataframe(
                    [
                        {
                            "Input": term.label,
                            "Value": float(term.value),
                            "Unit": term.unit,
                        }
                        for term in metric.breakdown.terms
                    ],
                    width="stretch",
                    hide_index=True,
                )
                st.caption(f"Evidence state: {metric.state}")

    if view.gates:
        st.subheader("Decision gates")
        st.dataframe(
            [
                {
                    "Gate": gate.label,
                    "State": gate.state.value,
                    "Reading": gate.note,
                }
                for gate in view.gates
            ],
            width="stretch",
            hide_index=True,
        )

    if package.modules.network_market_design is not None:
        st.subheader("Network architecture")
        st.write(package.modules.network_market_design.note)

    if view.boundaries:
        st.subheader("What publication does not claim")
        for boundary in view.boundaries:
            st.markdown(f"- {boundary}")

    if view.artifacts:
        st.subheader("Case material")
        for artifact in view.artifacts:
            st.markdown(f"[{artifact.label}]({artifact.href})")

    st.caption("Available modules: " + ", ".join(view.modules))



def render_new_case() -> None:
    if st.button("Back"):
        st.session_state["surface"] = "home"
        st.rerun()
    st.title("New private case")
    st.caption("Create a portable case package. Nothing is added to the public catalogue.")
    setup = st.radio("Setup", ["Start blank", "Guided setup"], horizontal=True)
    with st.form("new-case-draft"):
        label = st.text_input("Case name")
        question = st.text_area("Decision question")
        site_label = ""
        concept_label = ""
        operating_model_label = ""
        if setup == "Guided setup":
            site_label = st.text_input("Site or market")
            concept_label = st.text_input("Concept hypothesis")
            operating_model_label = st.text_input(
                "Operating model", value="To be agreed"
            )
        submitted = st.form_submit_button("Create case")
    if submitted:
        if not label.strip():
            st.error("Case name is required.")
            return
        case_id = "-".join(label.lower().split())
        modules = CasePackageModules()
        capabilities: list[CaseCapability] = []
        kind = CaseKind.GENERIC_BUSINESS
        if setup == "Guided setup":
            site_id = f"{case_id}-site"
            concept_id = f"{case_id}-concept"
            operating_model_id = f"{case_id}-operating-model"
            modules = CasePackageModules(
                site=SiteDefinition(site_id=site_id, label=site_label or "Site to define"),
                concept=ConceptDefinition(
                    concept_id=concept_id,
                    label=concept_label or "Concept to define",
                ),
                operating_model=OperatingModelDefinition(
                    operating_model_id=operating_model_id,
                    label=operating_model_label or "To be agreed",
                    mode=OperatingMode.SINGLE_OPERATOR,
                    purpose="Working assumption; not an agreed operating commitment.",
                ),
                composition=CaseComposition(
                    composition_id=f"{case_id}-composition",
                    site_id=site_id,
                    concept_id=concept_id,
                    operating_model_id=operating_model_id,
                ),
            )
            capabilities = [
                CaseCapability(module_id=module_id)
                for module_id in ("site", "concept", "operating_model", "composition")
            ]
            kind = CaseKind.SITE_BUSINESS
        package = CasePackageV2(
            metadata=CasePackageV2Metadata(
                case_id=case_id,
                label=label.strip(),
                kind=kind,
                description=question.strip() or None,
            ),
            capabilities=capabilities,
            modules=modules,
        )
        sync_package(package)
        st.session_state[PACKAGE_FILE_KEY] = "new private case"
        st.session_state.pop(PACKAGE_DIGEST_KEY, None)
        st.session_state["surface"] = "workspace"
        st.rerun()


def render_workspace_header(package: PortablePackage) -> None:
    top_left, top_right = st.columns([1, 0.35])
    with top_left:
        st.title(package.metadata.label)
        st.caption("Private session only · not published")
    with top_right:
        if st.button("Close case", width="stretch"):
            for key in (PACKAGE_STATE_KEY, PACKAGE_FILE_KEY, PACKAGE_DIGEST_KEY):
                st.session_state.pop(key, None)
            st.session_state["surface"] = "home"
            st.rerun()


def render_overview(package: PortablePackage) -> None:
    site = case_module(package, "site")
    concept = case_module(package, "concept")
    operating_model = case_module(package, "operating_model")
    scenario = case_module(package, "aggregate_scenario")
    economic_scenarios = case_module(package, "economic_scenarios")
    product_catalog = case_module(package, "product_catalog")
    fixed_costs = case_module(package, "fixed_costs")
    decision_plan = case_module(package, "decision_plan")

    st.subheader("What this case is testing")
    if site is not None and concept is not None:
        st.write(
            f"Can **{site.label}** become a productive roadside site, starting with "
            f"**{concept.label}**, and which combination of demand, operating costs "
            "and commercial terms would make it sustainable?"
        )
    else:
        st.write(package.metadata.description or "This case still needs a clear question.")

    if site is not None and concept is not None and operating_model is not None:
        a, b, c = st.columns(3)
        a.markdown(f"**Place**\n\n{site.label}")
        b.markdown(f"**Concept being tested**\n\n{concept.label}")
        c.markdown(f"**Operating structure**\n\n{operating_model.label}")
        st.caption(
            "The place, concept and operator agreement are separate decisions. "
            "Testing the grill concept does not commit the property to one permanent model."
        )
        if "agree" in operating_model.label.lower() or "unresolved" in operating_model.evidence_state.value.lower():
            st.warning(
                "No operating agreement is in place yet. Rent, responsibilities, "
                "investment and charging terms still need to be agreed with the property owner."
            )

    if scenario is not None and economic_scenarios is not None:
        st.subheader("What the model says right now")
        st.caption(
            "Choose a purchase-volume scenario. These are possible daily purchase counts, "
            "not measured traffic or a sales forecast."
        )
        product_mode = (
            product_catalog is not None
            and product_catalog.income_mode == CoreIncomeMode.PRODUCT_MIX
        )
        if product_mode:
            scenario_by_label = {
                item.label: item for item in product_catalog.volume_scenarios
            }
            selected_id = product_catalog.selected_volume_scenario_id
            selected_index = next(
                (
                    index
                    for index, item in enumerate(product_catalog.volume_scenarios)
                    if item.scenario_id == selected_id
                ),
                0,
            )
            selected_label = st.radio(
                "Product mix scenario",
                list(scenario_by_label),
                index=selected_index,
                horizontal=True,
            )
            selected = scenario_by_label[selected_label]
            product_catalog.selected_volume_scenario_id = selected.scenario_id
            mix_result = ProductMixEngine().run(product_catalog)
            if mix_result.complete:
                scenario, mix_result = ProductMixEngine().scenario_for_mix(
                    scenario, product_catalog
                )
                result = DeterministicEngine().run(scenario)
            else:
                result = None
        else:
            scenario_by_label = {
                item.label: item for item in economic_scenarios.scenarios
            }
            selected_id = economic_scenarios.selected_scenario_id
            selected_index = next(
                (
                    index
                    for index, item in enumerate(economic_scenarios.scenarios)
                    if item.scenario_id == selected_id
                ),
                0,
            )
            selected_label = st.radio(
                "Purchase visits per day",
                list(scenario_by_label),
                index=selected_index,
                horizontal=True,
            )
            selected = scenario_by_label[selected_label]
            economic_scenarios.selected_scenario_id = selected.scenario_id
            scenario.visits_per_day = selected.visits_per_day
            result = DeterministicEngine().run(scenario)

        overview_income_incomplete = result is None
        if result is None:
            scenario = scenario.model_copy(
                update={
                    "visits_per_day": mix_result.total_units_per_day,
                    "days_per_month": mix_result.operating_days_per_month,
                    "revenue_per_visit": Decimal("0"),
                    "db1_per_visit": Decimal("0"),
                    "activity_label": "product units",
                    "activity_unit": "product units/day",
                }
            )
            result = DeterministicEngine().run(scenario)
            st.error(
                "The selected product mix is incomplete: "
                + ", ".join(mix_result.unresolved_fields)
            )

        unresolved_operator_costs = []
        if fixed_costs is not None:
            unresolved_ids = fixed_costs.unresolved_active_cost_ids_at(
                scenario.visits_per_day
            )
            unresolved_operator_costs = [
                cost.label
                for cost in fixed_costs.cost_objects
                if cost.cost_id in unresolved_ids
                and cost.payer_entity_id == scenario.core_entity_id
            ]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Food sales / month" if product_mode else "Customer sales / month", "Incomplete" if overview_income_incomplete else money(result.monthly_sales, scenario.currency))
        m2.metric("Food contribution / month" if product_mode else "Contribution / month", "Incomplete" if overview_income_incomplete else money(result.monthly_db1, scenario.currency))
        m3.metric("Food operator result / month" if product_mode else "Base result / month", "Incomplete" if overview_income_incomplete else money(result.core_cash_result, scenario.currency))
        m4.metric(
            "Food break-even menu units/day" if product_mode else "Base break-even / day",
            "Incomplete"
            if overview_income_incomplete
            else "Not available"
            if result.break_even_visits_per_day is None
            else f"{float(result.break_even_visits_per_day):,.1f}",
        )

        if overview_income_incomplete:
            reading = (
                "The selected product quantities cannot yet produce a result because "
                "an active sold item is missing its price or direct cost."
            )
        else:
            activity_text = (
                "total menu units/day" if product_mode else "purchase visits/day"
            )
            reading = (
                f"At **{float(scenario.visits_per_day):,.0f} {activity_text}**, the current "
                f"assumptions produce **{money(result.core_cash_result, scenario.currency)} "
                "per month** after direct product costs and current overhead."
            )
        st.markdown(f"**Preliminary reading:** {reading}")
        if unresolved_operator_costs:
            st.warning(
                "This is not a complete operator result. The selected volume triggers "
                + ", ".join(unresolved_operator_costs)
                + ", but those staffing amounts are not priced yet. Rent, financing, "
                "owner pay and tax are also not conclusions from this base figure."
            )
        else:
            st.caption(
                "This is a model result, not a forecast. Rent, financing, owner pay and "
                "tax must still be added where relevant."
            )
        st.caption(
            f"Scenario status: {selected.status}. {selected.note or ''} "
            "Changing volume changes the calculation, not the evidence quality."
        )
        with st.expander("See the break-even calculation"):
            breakdown = result.breakdowns["break_even_visits_per_day"]
            st.write(breakdown.formula)
            st.dataframe(
                [
                    {
                        "Input": term.label,
                        "Value": float(term.value),
                        "Unit": term.unit,
                    }
                    for term in breakdown.terms
                ],
                width="stretch",
                hide_index=True,
            )

    st.subheader("Decision picture")
    known_col, assumed_col, open_col = st.columns(3)
    with known_col:
        st.markdown("**Documented or historically grounded**")
        if site is not None:
            st.markdown("- The site identity and roadside role are documented.")
        st.markdown("- A roadside grill previously operated at the location.")
        st.markdown("- The property is a real physical opportunity, not a fictional site.")
    with assumed_col:
        st.markdown("**What the current model assumes**")
        if scenario is not None:
            st.markdown(
                f"- {float(scenario.visits_per_day):,.0f} {scenario.activity_label} per day in the selected scenario."
            )
            st.markdown(
                f"- {money(scenario.db1_per_visit, scenario.currency)} effective contribution per {scenario.activity_label[:-1] if scenario.activity_label.endswith(chr(115)) else scenario.activity_label}."
            )
            st.markdown(
                f"- {money(scenario.fixed_overhead_monthly, scenario.currency)} monthly base overhead."
            )
        st.markdown("- Product mix, prices and most costs still need operating evidence.")
    with open_col:
        st.markdown("**What must be resolved with the property owner**")
        if decision_plan is not None:
            open_questions = [
                question
                for question in decision_plan.stakeholder_questions
                if question.status != "Answered"
            ]
            for question in open_questions[:5]:
                st.markdown(f"- {question.label}")
        else:
            st.markdown("- Commercial terms, responsibilities and timing.")

    if decision_plan is not None:
        open_questions = [
            question
            for question in decision_plan.stakeholder_questions
            if question.status != "Answered"
        ]
        st.subheader("Questions for the meeting")
        st.caption(
            "Answers to these questions change the case. They are not minor documentation gaps."
        )
        for index, question in enumerate(open_questions, start=1):
            st.markdown(f"**{index}. {question.label}**")
            st.write(question.note or "")

    asset_layer = case_module(package, "assets_revenue")
    if asset_layer is not None and asset_layer.revenue_streams:
        with st.expander("Additional site possibilities - not part of the base result"):
            owner_labels = {
                "property_owner": "Property owner",
                "food_operator": "Food operator",
            }
            for stream in asset_layer.revenue_streams:
                owner = owner_labels.get(stream.owner_entity_id, stream.owner_entity_id)
                st.markdown(f"**{stream.label}** - possible owner: {owner}")
                st.write(stream.note or "")
                st.caption(f"Current state: {stream.status}")

    experiments = case_module(package, "structural_experiments")
    if experiments is not None:
        for experiment in experiments.experiments:
            with st.expander(f"Possible way to test the site: {experiment.label}"):
                st.caption(experiment.status)
                st.write(experiment.summary)
                if experiment.coverage_caption:
                    st.caption(experiment.coverage_caption)

    with st.expander("Case details and administration"):
        package.metadata.status = st.text_input("Case status", package.metadata.status)
        package.metadata.description = st.text_area(
            "Description", package.metadata.description or "", height=90
        ) or None

    st.subheader("Notes from this meeting")
    package.workspace.meeting_notes = st.text_area(
        "Meeting notes", package.workspace.meeting_notes, height=180
    )


def render_demand(package: PortablePackage) -> None:
    demand = case_module(package, "demand_surface")
    decision_plan = case_module(package, "decision_plan")

    st.subheader("Where could the customers come from?")
    st.write(
        "The site may draw from local residents, passing road traffic, commuters, "
        "destination visits and future site services. The current model does not yet "
        "prove how many people will stop and buy."
    )
    st.warning(
        "The 60 / 100 / 150 / 350 figures are purchase-visit scenarios. "
        "They are not observed traffic counts."
    )

    documented = [
        source
        for source in demand.sources
        if "sourced" in source.status.lower() or "historical" in source.status.lower()
    ]
    estimated = [
        source
        for source in demand.sources
        if "estimated" in source.status.lower()
    ]
    unknown = [
        source
        for source in demand.sources
        if source not in documented and source not in estimated
    ]

    st.subheader("Demand picture")
    documented_col, estimated_col, unknown_col = st.columns(3)
    groups = (
        (documented_col, "Evidence exists, but may need updating", documented),
        (estimated_col, "Plausible, not measured", estimated),
        (unknown_col, "Unknown until the property owner or a test provides data", unknown),
    )
    for column, heading, sources in groups:
        with column:
            st.markdown(f"**{heading}**")
            for source in sources:
                st.markdown(f"**{source.label}**")
                st.write(source.note)
                st.caption(source.status)

    st.subheader("From potential traffic to a paying customer")
    st.caption(
        "Each step narrows the market. Missing conversion data must stay missing; "
        "passing the site is not the same as stopping, entering or buying."
    )
    for index, step in enumerate(demand.funnel, start=1):
        left, right = st.columns([0.18, 0.82])
        left.markdown(f"**Step {index}**")
        right.markdown(f"**{step.label}**")
        right.write(step.note)
        right.caption(f"Evidence: {step.status}")

    st.info(
        "The economics currently starts at purchase visits/day near the end of this "
        "funnel. The earlier stop and conversion rates still need current site evidence."
    )

    if decision_plan is not None and decision_plan.measurements:
        st.subheader("What would make the demand case stronger?")
        for measurement in decision_plan.measurements:
            st.markdown(f"**{measurement.label}** - {measurement.note}")
            st.caption(
                f"Before: {measurement.before_experiment_basis} | "
                f"During a test: {measurement.during_experiment_evidence}"
            )

    with st.expander("Evidence register and editing"):
        st.caption(
            "Editing a status records the current case judgement. It does not turn "
            "an estimate into observed evidence."
        )
        source_by_label = {source.label: source for source in demand.sources}
        selected_source_label = st.selectbox(
            "Demand source",
            list(source_by_label),
            key="demand-source-editor",
        )
        selected_source = source_by_label[selected_source_label]
        selected_source.status = st.text_input(
            "Evidence status",
            selected_source.status,
            key=f"demand-status-{selected_source.source_id}",
        )
        selected_source.note = st.text_area(
            "Demand source note",
            selected_source.note,
            key=f"demand-note-{selected_source.source_id}",
        )

        funnel_by_label = {step.label: step for step in demand.funnel}
        selected_step_label = st.selectbox(
            "Funnel step",
            list(funnel_by_label),
            key="demand-funnel-editor",
        )
        selected_step = funnel_by_label[selected_step_label]
        selected_step.status = st.text_input(
            "Funnel evidence status",
            selected_step.status,
            key=f"funnel-status-{selected_step.step_id}",
        )
        selected_step.note = st.text_area(
            "Funnel note",
            selected_step.note,
            key=f"funnel-note-{selected_step.step_id}",
        )


def render_product_mix_editor(package: PortablePackage, catalog, currency: str):
    st.markdown("**Core food and drink income**")
    st.caption(
        "Choose exactly one core income source. Product mix derives revenue and "
        "contribution from item quantities, prices and direct costs. The legacy "
        "bridge remains available only for workbook comparison."
    )
    mode_labels = {
        "Editable product mix": CoreIncomeMode.PRODUCT_MIX,
        "Legacy aggregate bridge": CoreIncomeMode.LEGACY_BRIDGE,
    }
    current_label = next(
        label for label, mode in mode_labels.items() if mode == catalog.income_mode
    )
    selected_label = st.radio(
        "Core income source",
        list(mode_labels),
        index=list(mode_labels).index(current_label),
        horizontal=True,
        key="core-income-source",
    )
    catalog.income_mode = mode_labels[selected_label]

    if catalog.income_mode == CoreIncomeMode.LEGACY_BRIDGE:
        st.info(
            "Legacy mode uses the aggregate revenue and contribution per visit "
            "from the old workbook bridge. Product rows do not enter profit in this mode."
        )
        return None

    if not catalog.volume_scenarios:
        product_ids = [product.product_id for product in catalog.products]
        catalog.volume_scenarios = [
            ProductVolumeScenario(
                scenario_id="working_mix",
                label="Working product mix",
                quantities_per_day={product_id: Decimal("0") for product_id in product_ids},
                note="New provisional scenario; no sales have been validated.",
            )
        ]
        catalog.selected_volume_scenario_id = "working_mix"

    scenario_labels = {item.label: item for item in catalog.volume_scenarios}
    selected_scenario = catalog.selected_volume_scenario
    selected_scenario_label = (
        selected_scenario.label
        if selected_scenario is not None
        else catalog.volume_scenarios[0].label
    )
    chosen_scenario_label = st.selectbox(
        "Product-volume scenario",
        list(scenario_labels),
        index=list(scenario_labels).index(selected_scenario_label),
        key="product-volume-scenario",
    )
    selected_scenario = scenario_labels[chosen_scenario_label]
    catalog.selected_volume_scenario_id = selected_scenario.scenario_id
    selected_scenario.operating_days_per_month = Decimal(
        str(
            st.number_input(
                "Product mix operating days/month",
                min_value=0.1,
                max_value=31.0,
                value=float(selected_scenario.operating_days_per_month),
                key="product-mix-days",
            )
        )
    )
    st.warning(
        f"{selected_scenario.status}: {selected_scenario.note or 'Editable scenario assumption.'} "
        "Changing a number does not validate it."
    )

    products_by_label = {product.label: product for product in catalog.products}
    selected_product_label = st.selectbox(
        "Edit menu item",
        list(products_by_label),
        key="product-editor",
    )
    product = products_by_label[selected_product_label]
    product.active = st.checkbox(
        "Include product in this concept",
        value=product.active,
        key=f"product-active-{product.product_id}",
    )
    p1, p2, p3 = st.columns(3)
    try:
        product.selling_price_gross = optional_decimal(
            p1.text_input(
                "Selling price/unit",
                "" if product.selling_price_gross is None else str(product.selling_price_gross),
                key=f"product-price-{product.product_id}",
            ),
            "Selling price/unit",
        )
        product.direct_cost_gross = optional_decimal(
            p2.text_input(
                "Direct cost/unit",
                "" if product.direct_cost_gross is None else str(product.direct_cost_gross),
                key=f"product-cost-{product.product_id}",
            ),
            "Direct cost/unit",
        )
    except ValueError as exc:
        st.error(str(exc))
    selected_scenario.quantities_per_day[product.product_id] = Decimal(
        str(
            p3.number_input(
                "Expected units/day",
                min_value=0.0,
                value=float(
                    selected_scenario.quantities_per_day.get(product.product_id, Decimal("0"))
                ),
                key=f"product-units-{product.product_id}-{selected_scenario.scenario_id}",
            )
        )
    )
    product.waste_rate = Decimal(
        str(
            st.number_input(
                "Waste/extra direct-cost rate (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(product.waste_rate * Decimal("100")),
                key=f"product-waste-{product.product_id}",
            )
        )
    ) / Decimal("100")

    evidence_values = [state.value for state in EvidenceState]
    e1, e2, e3 = st.columns(3)
    product.price_evidence_state = EvidenceState(
        e1.selectbox(
            "Price evidence",
            evidence_values,
            index=evidence_values.index(product.price_evidence_state.value),
            key=f"product-price-evidence-{product.product_id}",
        )
    )
    product.direct_cost_evidence_state = EvidenceState(
        e2.selectbox(
            "Cost evidence",
            evidence_values,
            index=evidence_values.index(product.direct_cost_evidence_state.value),
            key=f"product-cost-evidence-{product.product_id}",
        )
    )
    product.volume_evidence_state = EvidenceState(
        e3.selectbox(
            "Volume evidence",
            evidence_values,
            index=evidence_values.index(product.volume_evidence_state.value),
            key=f"product-volume-evidence-{product.product_id}",
        )
    )
    product.notes = st.text_area(
        "Product note",
        product.notes or "",
        key=f"product-note-{product.product_id}",
    ) or None
    product.contribution_per_unit = product.derived_contribution_per_unit
    product.contribution_margin = (
        product.derived_contribution_per_unit / product.selling_price_gross
        if product.derived_contribution_per_unit is not None
        and product.selling_price_gross not in (None, Decimal("0"))
        else None
    )

    add_col, duplicate_col, remove_col = st.columns(3)
    with add_col.expander("Add menu item"):
        with st.form("add-product-form"):
            new_id = st.text_input("New product ID")
            new_label = st.text_input("New product name")
            new_price = st.text_input("New selling price/unit")
            new_cost = st.text_input("New direct cost/unit")
            add_product = st.form_submit_button("Add product")
        if add_product:
            try:
                candidate = ProductItem(
                    product_id=new_id.strip(),
                    label=new_label.strip(),
                    active=True,
                    selling_price_gross=optional_decimal(new_price, "New selling price/unit"),
                    direct_cost_gross=optional_decimal(new_cost, "New direct cost/unit"),
                    status="HYPOTHESIS",
                )
                if candidate.product_id in {item.product_id for item in catalog.products}:
                    raise ValueError("Product ID already exists")
                candidate.contribution_per_unit = candidate.derived_contribution_per_unit
                catalog.products.append(candidate)
                for volume_scenario in catalog.volume_scenarios:
                    volume_scenario.quantities_per_day[candidate.product_id] = Decimal("0")
                sync_package(package)
                st.rerun()
            except (ValidationError, ValueError) as exc:
                st.error(str(exc))
    with duplicate_col:
        if st.button(
            "Duplicate selected menu item",
            key=f"duplicate-product-{product.product_id}",
            width="stretch",
        ):
            clone = product.model_copy(deep=True)
            clone.product_id = duplicate_identifier(
                product.product_id,
                {item.product_id for item in catalog.products},
            )
            clone.label = f"{product.label} copy"
            clone.price_evidence_state = EvidenceState.HYPOTHESIS
            clone.direct_cost_evidence_state = EvidenceState.HYPOTHESIS
            clone.volume_evidence_state = EvidenceState.HYPOTHESIS
            catalog.products.append(clone)
            for volume_scenario in catalog.volume_scenarios:
                volume_scenario.quantities_per_day[clone.product_id] = Decimal("0")
            sync_package(package)
            st.rerun()
    with remove_col:
        confirm_product_remove = st.checkbox(
            "Confirm removal",
            key=f"confirm-product-remove-{product.product_id}",
        )
        if st.button(
            "Remove selected menu item",
            disabled=len(catalog.products) <= 1 or not confirm_product_remove,
            key=f"remove-product-{product.product_id}",
            width="stretch",
        ):
            catalog.products = [
                item for item in catalog.products if item.product_id != product.product_id
            ]
            for volume_scenario in catalog.volume_scenarios:
                volume_scenario.quantities_per_day.pop(product.product_id, None)
            sync_package(package)
            st.rerun()

    mix_result = ProductMixEngine().run(catalog)
    st.dataframe(
        [
            {
                "Product": line.label,
                "Active": line.active,
                "Units/day": float(line.units_per_day),
                "Revenue/month": (
                    "Missing" if line.gross_revenue_monthly is None
                    else money(line.gross_revenue_monthly, currency)
                ),
                "Direct cost/month": (
                    "Missing" if line.direct_cost_monthly is None
                    else money(line.direct_cost_monthly, currency)
                ),
                "Contribution/month": (
                    "Missing" if line.contribution_monthly is None
                    else money(line.contribution_monthly, currency)
                ),
            }
            for line in mix_result.lines
        ],
        width="stretch",
        hide_index=True,
    )
    if mix_result.unresolved_fields:
        st.error(
            "Product mix is incomplete. Add values for: "
            + ", ".join(mix_result.unresolved_fields)
        )
    return mix_result


def render_economics(package: PortablePackage) -> None:
    st.subheader("Economics")
    st.caption(
        "Core food income can come from an editable product mix or the visible "
        "legacy workbook bridge. Other revenue adapters remain separate and additive."
    )
    base_scenario = case_module(package, "aggregate_scenario")
    scenario = base_scenario
    fixed_costs = case_module(package, "fixed_costs")
    contracts = case_module(package, "contracts")
    revenue_adapters = case_module(package, "revenue_adapters")
    product_catalog = case_module(package, "product_catalog")
    product_mix_result = None
    unresolved_income_fields: list[str] = []

    if product_catalog is not None:
        product_mix_result = render_product_mix_editor(
            package, product_catalog, base_scenario.currency
        )
        if (
            product_catalog.income_mode == CoreIncomeMode.PRODUCT_MIX
            and product_mix_result is not None
        ):
            unresolved_income_fields = product_mix_result.unresolved_fields
            if product_mix_result.complete:
                scenario, product_mix_result = ProductMixEngine().scenario_for_mix(
                    base_scenario, product_catalog
                )

    if (
        product_catalog is None
        or product_catalog.income_mode == CoreIncomeMode.LEGACY_BRIDGE
    ):
        st.markdown("**Legacy bridge inputs**")
        c1, c2, c3 = st.columns(3)
        base_scenario.visits_per_day = Decimal(
            str(c1.number_input("Visits/day", min_value=0.0, value=float(base_scenario.visits_per_day)))
        )
        base_scenario.days_per_month = Decimal(
            str(
                c2.number_input(
                    "Operating days/month",
                    min_value=0.1,
                    max_value=31.0,
                    value=float(base_scenario.days_per_month),
                )
            )
        )
        proposed_revenue_per_visit = Decimal(
            str(
                c3.number_input(
                    "Revenue/visit",
                    min_value=0.0,
                    value=float(base_scenario.revenue_per_visit),
                )
            )
        )
        c4, c5 = st.columns(2)
        proposed_db1_per_visit = Decimal(
            str(
                c4.number_input(
                    "Contribution/visit (DB1)",
                    min_value=0.0,
                    value=float(base_scenario.db1_per_visit),
                )
            )
        )
        if proposed_db1_per_visit <= proposed_revenue_per_visit:
            base_scenario.revenue_per_visit = proposed_revenue_per_visit
            base_scenario.db1_per_visit = proposed_db1_per_visit
        else:
            st.error(
                "Contribution/visit cannot exceed Revenue/visit. "
                "The invalid values were not applied."
            )
        scenario = base_scenario
    else:
        c5 = st

    unresolved_operator_cost_ids: list[str] = []
    if fixed_costs is not None and fixed_costs.cost_objects:
        scenario.fixed_overhead_monthly = fixed_costs.sync_selected_scenario_total(
            scenario.core_entity_id,
            scenario.visits_per_day,
        )
        base_scenario.fixed_overhead_monthly = scenario.fixed_overhead_monthly
        c5.metric(
            "Operator fixed/month",
            money(scenario.fixed_overhead_monthly, scenario.currency),
        )
    else:
        scenario.fixed_overhead_monthly = Decimal(
            str(
                c5.number_input(
                    "Fixed/month",
                    min_value=0.0,
                    value=float(scenario.fixed_overhead_monthly),
                )
            )
        )

    if fixed_costs is not None and fixed_costs.cost_objects:
        def edit_cost(cost) -> None:
            cost.label = st.text_input(
                "Cost name",
                cost.label,
                key=f"cost-label-{cost.cost_id}",
            )
            cost.active = st.checkbox(
                "Include in entity books",
                value=cost.active,
                key=f"cost-active-{cost.cost_id}",
            )
            type_values = [item.value for item in CostCalculationType if item != CostCalculationType.CAPEX]
            chosen_type = st.selectbox(
                "Calculation type",
                type_values,
                index=type_values.index(cost.calculation_type.value),
                key=f"cost-type-{cost.cost_id}",
            )
            cost.calculation_type = CostCalculationType(chosen_type)
            if cost.calculation_type == CostCalculationType.STEPPED_MONTHLY:
                cost.activation_threshold_visits_per_day = Decimal(
                    str(
                        st.number_input(
                            "Activation threshold units/day",
                            min_value=0.0,
                            value=float(cost.activation_threshold_visits_per_day or 0),
                            key=f"cost-threshold-{cost.cost_id}",
                        )
                    )
                )
            else:
                cost.activation_threshold_visits_per_day = None
            if cost.calculation_type in {
                CostCalculationType.FIXED_MONTHLY,
                CostCalculationType.STEPPED_MONTHLY,
                CostCalculationType.HYBRID,
            }:
                amount_label = f"{cost.label} amount/month"
                try:
                    cost.monthly_amount = optional_decimal(
                        st.text_input(
                            amount_label,
                            "" if cost.monthly_amount is None else str(cost.monthly_amount),
                            key=f"cost-amount-{cost.cost_id}",
                        ),
                        amount_label,
                    )
                except ValueError as exc:
                    st.error(str(exc))
            else:
                cost.monthly_amount = None
            if cost.calculation_type in {
                CostCalculationType.PER_UNIT,
                CostCalculationType.HYBRID,
            }:
                try:
                    cost.unit_amount = optional_decimal(
                        st.text_input(
                            "Cost per unit",
                            "" if cost.unit_amount is None else str(cost.unit_amount),
                            key=f"cost-unit-amount-{cost.cost_id}",
                        ),
                        "Cost per unit",
                    )
                except ValueError as exc:
                    st.error(str(exc))
                override = st.text_input(
                    "Units/day override (blank uses current product units)",
                    "" if cost.units_per_day_override is None else str(cost.units_per_day_override),
                    key=f"cost-units-override-{cost.cost_id}",
                )
                try:
                    cost.units_per_day_override = optional_decimal(override, "Units/day override")
                except ValueError as exc:
                    st.error(str(exc))
                cost.days_per_month = Decimal(
                    str(
                        st.number_input(
                            "Cost days/month",
                            min_value=0.1,
                            max_value=31.0,
                            value=float(cost.days_per_month),
                            key=f"cost-days-{cost.cost_id}",
                        )
                    )
                )
            else:
                cost.unit_amount = None
                cost.units_per_day_override = None
            entity_ids = list(scenario.entity_ids)
            cost.owner_entity_id = st.selectbox(
                "Cost owner",
                entity_ids,
                index=entity_ids.index(cost.owner_entity_id),
                key=f"cost-owner-{cost.cost_id}",
            )
            cost.payer_entity_id = st.selectbox(
                "Cost payer",
                entity_ids,
                index=entity_ids.index(cost.payer_entity_id),
                key=f"cost-payer-{cost.cost_id}",
            )
            states = [state.value for state in EvidenceState]
            cost.evidence_state = EvidenceState(
                st.selectbox(
                    "Cost evidence",
                    states,
                    index=states.index(cost.evidence_state.value),
                    key=f"cost-evidence-{cost.cost_id}",
                )
            )
            cost.source = st.text_input(
                "Cost source",
                cost.source or "",
                key=f"cost-source-{cost.cost_id}",
            ) or None
            cost.note = st.text_area(
                "Cost note",
                cost.note or "",
                key=f"cost-note-{cost.cost_id}",
            ) or None

        active_fixed_costs = [
            cost
            for cost in fixed_costs.cost_objects
            if cost.active and cost.calculation_type.value == "fixed_monthly"
        ]
        st.markdown("**Current monthly overhead assumptions**")
        st.caption(
            "These lines make up Operator fixed/month. They are workbook hypotheses, "
            "not confirmed bills or property-owner terms, and can be replaced as evidence arrives."
        )
        st.dataframe(
            [
                {
                    "Cost line": cost.label,
                    "Amount/month": money(cost.monthly_amount, scenario.currency),
                    "Status": (
                        "Workbook hypothesis"
                        if cost.evidence_state.value == "LEGACY_HYPOTHESIS"
                        else cost.evidence_state.value
                    ),
                }
                for cost in active_fixed_costs
            ],
            width="stretch",
            hide_index=True,
        )
        active_by_label = {cost.label: cost for cost in active_fixed_costs}
        selected_active_label = st.selectbox(
            "Edit current overhead line",
            list(active_by_label),
            key="current-cost-editor",
        )
        edit_cost(active_by_label[selected_active_label])

        stepped_costs = [
            cost
            for cost in fixed_costs.cost_objects
            if cost.calculation_type.value == "stepped_monthly"
        ]
        if stepped_costs:
            st.markdown("**Capacity-linked cost layers**")
            st.caption(
                "A layer affects the result only after its threshold is reached. "
                "A triggered layer without an amount makes the result incomplete."
            )
            st.dataframe(
                [
                    {
                        "Capacity layer": cost.label,
                        "Threshold visits/day": float(
                            cost.activation_threshold_visits_per_day or 0
                        ),
                        "Triggered": (
                            "Yes"
                            if cost.active
                            and scenario.visits_per_day
                            >= (cost.activation_threshold_visits_per_day or Decimal("0"))
                            else "No"
                        ),
                        "Amount/month": (
                            money(cost.monthly_amount, scenario.currency)
                            if cost.monthly_amount is not None
                            else "Not priced"
                        ),
                        "Evidence": cost.evidence_state.value,
                    }
                    for cost in stepped_costs
                ],
                width="stretch",
                hide_index=True,
            )
            stepped_by_label = {cost.label: cost for cost in stepped_costs}
            selected_step_label = st.selectbox(
                "Edit capacity layer",
                list(stepped_by_label),
                key="capacity-cost-editor",
            )
            edit_cost(stepped_by_label[selected_step_label])

        inactive_costs = [
            cost
            for cost in fixed_costs.cost_objects
            if not cost.active and cost.calculation_type.value != "stepped_monthly"
        ]
        if inactive_costs:
            st.markdown("**Not in the current model**")
            st.caption(
                "These are available cost types, not missing values from the current total. "
                "Activate one only when you want it to enter the entity books."
            )
            st.dataframe(
                [
                    {
                        "Cost type": cost.label,
                        "Status": "Not included",
                        "Evidence needed": cost.note or "Terms or evidence required.",
                    }
                    for cost in inactive_costs
                ],
                width="stretch",
                hide_index=True,
            )
            inactive_by_label = {cost.label: cost for cost in inactive_costs}
            selected_inactive_label = st.selectbox(
                "Inspect or add a cost type",
                list(inactive_by_label),
                key="inactive-cost-editor",
            )
            edit_cost(inactive_by_label[selected_inactive_label])

        st.markdown("**Add, duplicate or remove cost lines**")
        with st.expander("Add cost line"):
            with st.form("add-cost-form"):
                new_cost_label = st.text_input("New cost name")
                new_cost_type = st.selectbox(
                    "New cost calculation",
                    [
                        CostCalculationType.FIXED_MONTHLY.value,
                        CostCalculationType.PER_UNIT.value,
                        CostCalculationType.HYBRID.value,
                        CostCalculationType.STEPPED_MONTHLY.value,
                    ],
                )
                new_cost_owner = st.selectbox("New cost owner", list(scenario.entity_ids))
                new_cost_payer = st.selectbox("New cost payer", list(scenario.entity_ids))
                add_cost = st.form_submit_button("Add cost")
            if add_cost:
                try:
                    existing_ids = {item.cost_id for item in fixed_costs.cost_objects}
                    candidate = CostObject(
                        cost_id=safe_identifier(new_cost_label, existing_ids, "new_cost"),
                        label=new_cost_label.strip(),
                        category="meeting_idea",
                        calculation_type=CostCalculationType(new_cost_type),
                        owner_entity_id=new_cost_owner,
                        payer_entity_id=new_cost_payer,
                        active=False,
                        activation_threshold_visits_per_day=(
                            Decimal("0")
                            if new_cost_type == CostCalculationType.STEPPED_MONTHLY.value
                            else None
                        ),
                        evidence_state=EvidenceState.HYPOTHESIS,
                        note="Added during case exploration; amount and evidence remain provisional.",
                    )
                    fixed_costs.cost_objects.append(candidate)
                    sync_package(package)
                    st.rerun()
                except (ValidationError, ValueError) as exc:
                    st.error(str(exc))
        cost_labels = {item.cost_id: item.label for item in fixed_costs.cost_objects}
        managed_cost_id = st.selectbox(
            "Cost line to duplicate or remove",
            list(cost_labels),
            format_func=cost_labels.get,
            key="manage-cost-line",
        )
        managed_cost = next(
            item for item in fixed_costs.cost_objects
            if item.cost_id == managed_cost_id
        )
        cost_action_left, cost_action_right = st.columns(2)
        if cost_action_left.button("Duplicate cost", width="stretch"):
            clone = managed_cost.model_copy(deep=True)
            clone.cost_id = duplicate_identifier(
                managed_cost.cost_id,
                {item.cost_id for item in fixed_costs.cost_objects},
            )
            clone.label = f"{managed_cost.label} copy"
            clone.evidence_state = EvidenceState.HYPOTHESIS
            clone.source = None
            fixed_costs.cost_objects.append(clone)
            sync_package(package)
            st.rerun()
        confirm_cost_remove = st.checkbox(
            "Confirm removal of selected cost",
            key=f"confirm-cost-remove-{managed_cost.cost_id}",
        )
        if cost_action_right.button(
            "Remove cost",
            disabled=managed_cost.legacy_residual or not confirm_cost_remove,
            width="stretch",
        ):
            fixed_costs.cost_objects = [
                item for item in fixed_costs.cost_objects
                if item.cost_id != managed_cost.cost_id
            ]
            sync_package(package)
            st.rerun()

        scenario.fixed_overhead_monthly = fixed_costs.sync_selected_scenario_total(
            scenario.core_entity_id,
            scenario.visits_per_day,
        )
        base_scenario.fixed_overhead_monthly = scenario.fixed_overhead_monthly
        unresolved_cost_ids = fixed_costs.unresolved_active_cost_ids_at(
            scenario.visits_per_day
        )
        unresolved_operator_cost_ids = [
            cost.cost_id
            for cost in fixed_costs.cost_objects
            if cost.cost_id in unresolved_cost_ids
            and cost.payer_entity_id == scenario.core_entity_id
        ]
        if unresolved_operator_cost_ids:
            labels = [
                cost.label
                for cost in fixed_costs.cost_objects
                if cost.cost_id in unresolved_operator_cost_ids
            ]
            st.warning(
                "Current result is incomplete because these triggered costs need an amount: "
                + ", ".join(labels)
            )

    if revenue_adapters is not None:
        st.markdown("**Additional revenue and value adapters**")
        st.caption(
            "These streams are additive to the current grill DB1 unless marked as already included. "
            "Blocked or disabled streams contribute 0 SEK."
        )
        for adapter in revenue_adapters.adapters:
            with st.expander(
                f"{adapter.label} · {adapter.entity_id} · {adapter.evidence_state.value}"
            ):
                adapter.label = st.text_input(
                    "Income layer name",
                    adapter.label,
                    key=f"adapter-label-{adapter.adapter_id}",
                )
                adapter.entity_id = st.selectbox(
                    "Income owner",
                    list(base_scenario.entity_ids),
                    index=list(base_scenario.entity_ids).index(adapter.entity_id),
                    key=f"adapter-owner-{adapter.adapter_id}",
                )
                adapter.enabled = st.checkbox(
                    "Enabled",
                    value=adapter.enabled,
                    key=f"adapter-enabled-{adapter.adapter_id}",
                )
                states = [state.value for state in type(adapter.evidence_state)]
                selected_state = st.selectbox(
                    "Evidence state",
                    states,
                    index=states.index(adapter.evidence_state.value),
                    key=f"adapter-state-{adapter.adapter_id}",
                )
                adapter.evidence_state = type(adapter.evidence_state)(selected_state)
                adapter.included_in_core = st.checkbox(
                    "Already included in core DB1",
                    value=adapter.included_in_core,
                    key=f"adapter-core-{adapter.adapter_id}",
                )
                if adapter.kind == "fixed_monthly":
                    adapter.monthly_revenue = Decimal(str(st.number_input(
                        "Revenue/month", min_value=0.0,
                        value=float(adapter.monthly_revenue),
                        key=f"adapter-revenue-{adapter.adapter_id}",
                    )))
                    adapter.monthly_direct_cost = Decimal(str(st.number_input(
                        "Direct cost/month", min_value=0.0,
                        value=float(adapter.monthly_direct_cost),
                        key=f"adapter-cost-{adapter.adapter_id}",
                    )))
                elif adapter.kind == "per_event":
                    adapter.events_per_day = Decimal(str(st.number_input(
                        "Events/day", min_value=0.0,
                        value=float(adapter.events_per_day),
                        key=f"adapter-events-{adapter.adapter_id}",
                    )))
                    adapter.revenue_per_event = Decimal(str(st.number_input(
                        "Revenue/event", min_value=0.0,
                        value=float(adapter.revenue_per_event),
                        key=f"adapter-event-revenue-{adapter.adapter_id}",
                    )))
                    adapter.direct_cost_per_event = Decimal(str(st.number_input(
                        "Direct cost/event", min_value=0.0,
                        value=float(adapter.direct_cost_per_event),
                        key=f"adapter-event-cost-{adapter.adapter_id}",
                    )))
                elif adapter.kind == "revenue_share":
                    adapter.external_gross_revenue_monthly = Decimal(str(st.number_input(
                        "External gross revenue/month", min_value=0.0,
                        value=float(adapter.external_gross_revenue_monthly),
                        key=f"adapter-external-gross-{adapter.adapter_id}",
                    )))
                    adapter.share_rate = Decimal(str(st.number_input(
                        "Host share rate", min_value=0.0, max_value=1.0,
                        value=float(adapter.share_rate),
                        key=f"adapter-share-{adapter.adapter_id}",
                    )))
                    adapter.monthly_direct_cost = Decimal(str(st.number_input(
                        "Direct cost/month", min_value=0.0,
                        value=float(adapter.monthly_direct_cost),
                        key=f"adapter-share-cost-{adapter.adapter_id}",
                    )))
                elif adapter.kind == "usage":
                    adapter.events_per_day = Decimal(str(st.number_input(
                        "Usage events/day", min_value=0.0,
                        value=float(adapter.events_per_day),
                        key=f"adapter-usage-events-{adapter.adapter_id}",
                    )))
                    adapter.units_per_event = Decimal(str(st.number_input(
                        "Units/event", min_value=0.0,
                        value=float(adapter.units_per_event),
                        key=f"adapter-units-event-{adapter.adapter_id}",
                    )))
                    adapter.revenue_per_unit = Decimal(str(st.number_input(
                        "Revenue/unit", min_value=0.0,
                        value=float(adapter.revenue_per_unit),
                        key=f"adapter-unit-revenue-{adapter.adapter_id}",
                    )))
                    adapter.direct_cost_per_unit = Decimal(str(st.number_input(
                        "Direct cost/unit", min_value=0.0,
                        value=float(adapter.direct_cost_per_unit),
                        key=f"adapter-unit-cost-{adapter.adapter_id}",
                    )))
                    adapter.revenue_per_event = Decimal(str(st.number_input(
                        "Extra revenue/event", min_value=0.0,
                        value=float(adapter.revenue_per_event),
                        key=f"adapter-usage-event-revenue-{adapter.adapter_id}",
                    )))
                    adapter.direct_cost_per_event = Decimal(str(st.number_input(
                        "Extra direct cost/event", min_value=0.0,
                        value=float(adapter.direct_cost_per_event),
                        key=f"adapter-usage-event-cost-{adapter.adapter_id}",
                    )))
                adapter.note = st.text_area(
                    "Adapter note", adapter.note or "",
                    key=f"adapter-note-{adapter.adapter_id}",
                ) or None

        st.markdown("**Add, duplicate or remove income layers**")
        with st.expander("Add income layer"):
            with st.form("add-revenue-adapter-form"):
                new_adapter_label = st.text_input("New income layer name")
                new_adapter_kind = st.selectbox(
                    "Income calculation",
                    ["fixed_monthly", "per_event", "usage", "revenue_share"],
                )
                new_adapter_owner = st.selectbox(
                    "New income owner",
                    list(base_scenario.entity_ids),
                )
                add_adapter = st.form_submit_button("Add income layer")
            if add_adapter:
                existing_ids = {item.adapter_id for item in revenue_adapters.adapters}
                common = {
                    "adapter_id": safe_identifier(
                        new_adapter_label, existing_ids, "new_income"
                    ),
                    "label": new_adapter_label.strip(),
                    "entity_id": new_adapter_owner,
                    "enabled": False,
                    "evidence_state": EvidenceState.HYPOTHESIS,
                    "note": "Added during case exploration; commercial values remain provisional.",
                }
                adapter_types = {
                    "fixed_monthly": FixedMonthlyRevenueAdapter,
                    "per_event": PerEventRevenueAdapter,
                    "usage": UsageRevenueAdapter,
                    "revenue_share": RevenueShareAdapter,
                }
                try:
                    revenue_adapters.adapters.append(
                        adapter_types[new_adapter_kind](**common)
                    )
                    sync_package(package)
                    st.rerun()
                except (ValidationError, ValueError) as exc:
                    st.error(str(exc))
        if revenue_adapters.adapters:
            adapter_labels = {
                item.adapter_id: item.label for item in revenue_adapters.adapters
            }
            managed_adapter_id = st.selectbox(
                "Income layer to duplicate or remove",
                list(adapter_labels),
                format_func=adapter_labels.get,
                key="manage-income-layer",
            )
            managed_adapter = next(
                item for item in revenue_adapters.adapters
                if item.adapter_id == managed_adapter_id
            )
            adapter_action_left, adapter_action_right = st.columns(2)
            if adapter_action_left.button("Duplicate income layer", width="stretch"):
                clone = managed_adapter.model_copy(deep=True)
                clone.adapter_id = duplicate_identifier(
                    managed_adapter.adapter_id,
                    {item.adapter_id for item in revenue_adapters.adapters},
                )
                clone.label = f"{managed_adapter.label} copy"
                clone.evidence_state = EvidenceState.HYPOTHESIS
                revenue_adapters.adapters.append(clone)
                sync_package(package)
                st.rerun()
            confirm_adapter_remove = st.checkbox(
                "Confirm removal of selected income layer",
                key=f"confirm-adapter-remove-{managed_adapter.adapter_id}",
            )
            if adapter_action_right.button(
                "Remove income layer",
                disabled=not confirm_adapter_remove,
                width="stretch",
            ):
                revenue_adapters.adapters = [
                    item for item in revenue_adapters.adapters
                    if item.adapter_id != managed_adapter.adapter_id
                ]
                sync_package(package)
                st.rerun()

    product_mode = (
        product_catalog is not None
        and product_catalog.income_mode == CoreIncomeMode.PRODUCT_MIX
    )
    if product_mode and product_mix_result is not None and not product_mix_result.complete:
        scenario = base_scenario.model_copy(
            update={
                "visits_per_day": product_mix_result.total_units_per_day,
                "days_per_month": product_mix_result.operating_days_per_month,
                "revenue_per_visit": Decimal("0"),
                "db1_per_visit": Decimal("0"),
            }
        )
        scenario.fixed_overhead_monthly = base_scenario.fixed_overhead_monthly

    st.markdown("**Where the current inputs come from**")
    income_evidence = (
        product_mix_result.evidence_status
        if product_mode and product_mix_result is not None
        else "Legacy model hypothesis"
    )
    st.dataframe(
        [
            {
                "Input": "Total menu units/day" if product_mode else "Visits/day",
                "Current": f"{float(scenario.visits_per_day):,.1f}",
                "Evidence": income_evidence,
                "Source": (
                    "Sum of active item quantities in the selected product-mix scenario."
                    if product_mode
                    else "Selected aggregate purchase-volume assumption."
                ),
            },
            {
                "Input": "Operating days/month",
                "Current": f"{float(scenario.days_per_month):,.4g}",
                "Evidence": income_evidence if product_mode else "Model policy",
                "Source": (
                    "Editable setting on the selected product-mix scenario."
                    if product_mode
                    else "Average calendar days used by the legacy bridge."
                ),
            },
            {
                "Input": "Effective revenue/menu unit" if product_mode else "Revenue/visit",
                "Current": (
                    "Incomplete"
                    if unresolved_income_fields
                    else money(scenario.revenue_per_visit, scenario.currency)
                ),
                "Evidence": income_evidence,
                "Source": (
                    "Derived from active product prices and quantities."
                    if product_mode
                    else "Aggregate workbook bridge; not observed sales."
                ),
            },
            {
                "Input": (
                    "Effective contribution/menu unit"
                    if product_mode
                    else "Contribution/visit (DB1)"
                ),
                "Current": (
                    "Incomplete"
                    if unresolved_income_fields
                    else money(scenario.db1_per_visit, scenario.currency)
                ),
                "Evidence": income_evidence,
                "Source": (
                    "Derived from product revenue minus direct cost and waste."
                    if product_mode
                    else "Aggregate workbook bridge; not observed margin."
                ),
            },
            {
                "Input": "Fixed/month",
                "Current": money(scenario.fixed_overhead_monthly, scenario.currency),
                "Evidence": "Workbook hypothesis breakdown",
                "Source": (
                    "Sum of active cost objects ported from the 14 Mid hypothesis lines "
                    "in workbook Fixed_Costs; these are not confirmed bills."
                    if fixed_costs is not None and fixed_costs.cost_objects
                    else "Legacy aggregate; component-level parity is still missing."
                ),
            },
        ],
        width="stretch",
        hide_index=True,
    )

    result = DeterministicEngine().run(scenario)
    r1, r2, r3, r4 = st.columns(4)
    result_incomplete = bool(unresolved_income_fields)
    r1.metric(
        "Food sales/month" if product_mode else "Monthly sales",
        "Incomplete" if result_incomplete else money(result.monthly_sales, scenario.currency),
    )
    r2.metric(
        "Food contribution/month" if product_mode else "Monthly contribution",
        "Incomplete" if result_incomplete else money(result.monthly_db1, scenario.currency),
    )
    r3.metric(
        "Food operator result/month" if product_mode else "Operator core result/month",
        "Incomplete" if result_incomplete else money(result.core_cash_result, scenario.currency),
    )
    r4.metric(
        (
            "Food break-even menu units/day"
            if product_mode
            else "Calculated break-even visits/day"
        ),
        "Incomplete"
        if unresolved_operator_cost_ids or result_incomplete
        else (
            "Not available"
            if result.break_even_visits_per_day is None
            else f"{float(result.break_even_visits_per_day):,.1f}"
        ),
    )
    if product_mode:
        st.caption(
            "Food break-even is the total number of food and drink items that must be "
            "sold per day while the current menu mix stays proportional. It is not one "
            "specific product and it is not a customer count. Charging, vending, parcel "
            "and advertising adapters are excluded from this food break-even."
        )
        if (
            product_mix_result is not None
            and product_mix_result.total_units_per_day > 0
            and result.break_even_visits_per_day is not None
            and not result_incomplete
            and not unresolved_operator_cost_ids
        ):
            mix_scale = (
                result.break_even_visits_per_day
                / product_mix_result.total_units_per_day
            )
            st.markdown("**Food break-even at the current menu mix**")
            st.dataframe(
                [
                    {
                        "Menu item": line.label,
                        "Current units/day": f"{float(line.units_per_day):,.1f}",
                        "Mix share": (
                            f"{float(line.units_per_day / product_mix_result.total_units_per_day):.1%}"
                        ),
                        "Units/day at food break-even": (
                            f"{float(line.units_per_day * mix_scale):,.1f}"
                        ),
                    }
                    for line in product_mix_result.lines
                    if line.active and line.units_per_day > 0
                ],
                width="stretch",
                hide_index=True,
            )
    if unresolved_operator_cost_ids:
        st.warning(
            "Break-even is incomplete because triggered operator costs have no amount: "
            + ", ".join(unresolved_operator_cost_ids)
        )
    if result_incomplete:
        st.warning(
            "Core income and break-even remain incomplete until every active product "
            "with positive volume has both a selling price and direct cost."
        )

    if fixed_costs is not None and fixed_costs.cost_objects:
        books_result = EntityBooksEngine().run(
            scenario, fixed_costs, revenue_adapters, product_catalog=product_catalog
        )
        operator_book = books_result.book_for(scenario.core_entity_id)
        property_book = (
            books_result.book_for("property_owner")
            if "property_owner" in scenario.entity_ids
            else None
        )
        st.markdown("**Food business plus additional site layers**")
        st.caption(
            "The food result above stands on its own. This section then adds charging, "
            "vending, parcel, advertising and other enabled adapters. Internal payments "
            "appear in both entity books and cancel in Whole site."
        )
        b1, b2, b3 = st.columns(3)
        b1.metric(
            "Operator result/month",
            money(operator_book.result_monthly, scenario.currency),
        )
        b2.metric(
            "Property-owner result/month",
            "Not available"
            if property_book is None
            else money(property_book.result_monthly, scenario.currency),
        )
        b3.metric(
            "Whole site result/month",
            money(books_result.consolidated_result_monthly, scenario.currency),
        )
        st.dataframe(
            [
                {
                    "Book": book.entity_id,
                    "Inflows": money(book.inflows_monthly, scenario.currency),
                    "Outflows": money(book.outflows_monthly, scenario.currency),
                    "Result": money(book.result_monthly, scenario.currency),
                }
                for book in books_result.entity_books
            ],
            width="stretch",
            hide_index=True,
        )
        if books_result.adapter_results:
            st.markdown("**Extra adapter contribution outside food break-even**")
            st.dataframe(
                [
                    {
                        "Stream": adapter.label,
                        "Book": adapter.entity_id,
                        "Gross revenue": money(adapter.gross_revenue_monthly, scenario.currency),
                        "Direct cost": money(adapter.direct_cost_monthly, scenario.currency),
                        "Contribution": money(adapter.contribution_monthly, scenario.currency),
                        "State": "Blocked" if adapter.blocked else (
                            "Disabled" if not adapter.enabled else adapter.evidence_state.value
                        ),
                    }
                    for adapter in books_result.adapter_results
                ],
                width="stretch",
                hide_index=True,
            )

        if books_result.transfers:
            st.markdown("**Internal transfers eliminated in Whole site**")
            st.dataframe(
                [
                    {
                        "Payment": transfer.label,
                        "Payer": transfer.payer_entity_id,
                        "Recipient": transfer.recipient_entity_id,
                        "Amount/month": money(
                            transfer.amount_monthly, scenario.currency
                        ),
                    }
                    for transfer in books_result.transfers
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No internal payment is active. Site rent remains missing and inactive."
            )
        if books_result.unresolved_cost_ids:
            st.warning(
                "Active costs excluded from books because their calculation is unresolved: "
                + ", ".join(books_result.unresolved_cost_ids)
            )

    if (
        fixed_costs is not None
        and fixed_costs.cost_objects
        and contracts is not None
    ):
        st.markdown("**Rent deal comparison**")
        st.caption(
            "Comparison only, not agreed property-owner terms. Rent is treated as additional "
            "unless the legacy residual is reduced by the amount already included there. "
            "Turnover shares use modeled core gross sales only; adapter revenue is excluded. "
            "Service credit is non-cash property value and never increases Whole-site cash."
        )
        for comparison in contracts.rent_comparisons:
            with st.expander(f"Edit comparison: {comparison.label}"):
                comparison.label = st.text_input(
                    "Rent scenario name",
                    comparison.label,
                    key=f"rent-label-{comparison.scenario_id}",
                )
                base_label = (
                    f"{comparison.label} minimum rent/month"
                    if comparison.kind == "turnover_share"
                    else f"{comparison.label} base rent/month"
                )
                proposed_base = Decimal(
                    str(
                        st.number_input(
                            base_label,
                            min_value=0.0,
                            value=float(comparison.base_rent_monthly),
                            key=f"rent-base-{comparison.scenario_id}",
                        )
                    )
                )
                if comparison.kind == "stepped":
                    proposed_threshold = Decimal(
                        str(
                            st.number_input(
                                "Step threshold visits/day",
                                min_value=0.0,
                                value=float(comparison.threshold_visits_per_day or 0),
                                key=f"rent-threshold-{comparison.scenario_id}",
                            )
                        )
                    )
                    proposed_step = Decimal(
                        str(
                            st.number_input(
                                "Rent/month at or above threshold",
                                min_value=0.0,
                                value=float(comparison.stepped_rent_monthly or 0),
                                key=f"rent-step-{comparison.scenario_id}",
                            )
                        )
                    )
                    if proposed_step < proposed_base:
                        st.error("Stepped rent cannot be below base rent.")
                    else:
                        comparison.base_rent_monthly = proposed_base
                        comparison.threshold_visits_per_day = proposed_threshold
                        comparison.stepped_rent_monthly = proposed_step
                elif comparison.kind == "service_credit":
                    comparison.base_rent_monthly = proposed_base
                    service_credit_label = (
                        f"{comparison.label} property service credit/month"
                    )
                    try:
                        comparison.property_service_credit_monthly = optional_decimal(
                            st.text_input(
                                service_credit_label,
                                (
                                    ""
                                    if comparison.property_service_credit_monthly is None
                                    else str(
                                        comparison.property_service_credit_monthly
                                    )
                                ),
                                key=f"rent-service-credit-{comparison.scenario_id}",
                            ),
                            service_credit_label,
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                elif comparison.kind in {"turnover_share", "hybrid"}:
                    proposed_share_percent = Decimal(
                        str(
                            st.number_input(
                                f"{comparison.label} revenue share (%)",
                                min_value=0.0,
                                max_value=100.0,
                                value=float(
                                    (comparison.revenue_share_rate or Decimal("0"))
                                    * Decimal("100")
                                ),
                                key=f"rent-share-{comparison.scenario_id}",
                            )
                        )
                    )
                    comparison.base_rent_monthly = proposed_base
                    comparison.revenue_share_rate = (
                        proposed_share_percent / Decimal("100")
                    )
                else:
                    comparison.base_rent_monthly = proposed_base
                comparison.note = st.text_area(
                    "Comparison note",
                    comparison.note or "",
                    key=f"rent-note-{comparison.scenario_id}",
                ) or None

        st.markdown("**Add, duplicate or remove rent scenarios**")
        with st.expander("Add rent scenario"):
            with st.form("add-rent-scenario-form"):
                new_rent_label = st.text_input("New rent scenario name")
                new_rent_kind = st.selectbox(
                    "Rent structure",
                    ["fixed", "stepped", "turnover_share", "hybrid", "service_credit"],
                )
                add_rent = st.form_submit_button("Add rent scenario")
            if add_rent:
                try:
                    extra = {}
                    if new_rent_kind == "stepped":
                        extra = {
                            "threshold_visits_per_day": Decimal("0"),
                            "stepped_rent_monthly": Decimal("0"),
                        }
                    elif new_rent_kind in {"turnover_share", "hybrid"}:
                        extra = {"revenue_share_rate": Decimal("0")}
                    elif new_rent_kind == "service_credit":
                        extra = {"property_service_credit_monthly": None}
                    contracts.rent_comparisons.append(
                        RentComparisonScenario(
                            scenario_id=safe_identifier(
                                new_rent_label,
                                {item.scenario_id for item in contracts.rent_comparisons},
                                "new_rent",
                            ),
                            label=new_rent_label.strip(),
                            kind=new_rent_kind,
                            payer_entity_id=scenario.core_entity_id,
                            recipient_entity_id=(
                                "property_owner"
                                if "property_owner" in scenario.entity_ids
                                else scenario.entity_ids[-1]
                            ),
                            base_rent_monthly=Decimal("0"),
                            status="Hypothesis",
                            note="Added during case exploration; not an agreed commercial term.",
                            **extra,
                        )
                    )
                    sync_package(package)
                    st.rerun()
                except (ValidationError, ValueError) as exc:
                    st.error(str(exc))
        if contracts.rent_comparisons:
            rent_labels = {
                item.scenario_id: item.label for item in contracts.rent_comparisons
            }
            managed_rent_id = st.selectbox(
                "Rent scenario to duplicate or remove",
                list(rent_labels),
                format_func=rent_labels.get,
                key="manage-rent-scenario",
            )
            managed_rent = next(
                item for item in contracts.rent_comparisons
                if item.scenario_id == managed_rent_id
            )
            rent_action_left, rent_action_right = st.columns(2)
            if rent_action_left.button("Duplicate rent scenario", width="stretch"):
                clone = managed_rent.model_copy(deep=True)
                clone.scenario_id = duplicate_identifier(
                    managed_rent.scenario_id,
                    {item.scenario_id for item in contracts.rent_comparisons},
                )
                clone.label = f"{managed_rent.label} copy"
                clone.status = "Hypothesis"
                contracts.rent_comparisons.append(clone)
                sync_package(package)
                st.rerun()
            confirm_rent_remove = st.checkbox(
                "Confirm removal of selected rent scenario",
                key=f"confirm-rent-remove-{managed_rent.scenario_id}",
            )
            if rent_action_right.button(
                "Remove rent scenario",
                disabled=not confirm_rent_remove,
                width="stretch",
            ):
                contracts.rent_comparisons = [
                    item for item in contracts.rent_comparisons
                    if item.scenario_id != managed_rent.scenario_id
                ]
                sync_package(package)
                st.rerun()

        comparison_results = RentComparisonEngine().run_many(
            scenario,
            fixed_costs,
            contracts.rent_comparisons,
            revenue_adapters=revenue_adapters,
        )
        st.dataframe(
            [
                {
                    "Scenario": item.label,
                    "Structure": item.kind,
                    "Revenue share": (
                        ""
                        if item.revenue_share_rate is None
                        else f"{float(item.revenue_share_rate * 100):,.1f}%"
                    ),
                    "Effective rent": money(
                        item.effective_rent_monthly, scenario.currency
                    ),
                    "Service credit": (
                        "Missing"
                        if (
                            item.kind == "service_credit"
                            and item.property_service_credit_monthly is None
                        )
                        else money(
                            item.property_service_credit_monthly or Decimal("0"),
                            scenario.currency,
                        )
                    ),
                    "Operator result": money(
                        item.operator_result_monthly, scenario.currency
                    ),
                    "Property-owner cash result": money(
                        item.recipient_result_monthly, scenario.currency
                    ),
                    "Property-owner total value": (
                        "Incomplete"
                        if item.recipient_total_value_monthly is None
                        else money(
                            item.recipient_total_value_monthly,
                            scenario.currency,
                        )
                    ),
                    "Whole site result": money(
                        item.consolidated_result_monthly, scenario.currency
                    ),
                    "Operator break-even/day": (
                        "Incomplete"
                        if item.unresolved_cost_ids
                        else (
                            "Not available"
                            if item.operator_break_even_visits_per_day is None
                            else f"{float(item.operator_break_even_visits_per_day):,.1f}"
                        )
                    ),
                    "Missing costs": ", ".join(item.unresolved_cost_ids),
                    "Status": item.status,
                }
                for item in comparison_results
            ],
            width="stretch",
            hide_index=True,
        )

    for breakdown_id in (
        "monthly_sales",
        "monthly_db1",
        "core_cash_result",
        "break_even_visits_per_day",
    ):
        breakdown = result.breakdowns[breakdown_id]
        with st.expander(f"How calculated? {breakdown.label}"):
            st.code(breakdown.formula, language=None)
            st.dataframe(
                [
                    {
                        "Input": term.label,
                        "Value": float(term.value),
                        "Unit": term.unit,
                    }
                    for term in breakdown.terms
                ],
                width="stretch",
                hide_index=True,
            )
            if breakdown.result is not None:
                st.markdown(
                    f"**Result:** {float(breakdown.result):,.2f} {breakdown.unit}"
                )

    st.subheader("Set a break-even target")
    st.caption(
        "A target is a reverse calculation, not evidence. Apply it to one driver "
        "only; the other assumptions stay unchanged."
    )
    current_break_even = result.break_even_visits_per_day or Decimal("1")
    target_break_even = Decimal(
        str(
            st.number_input(
                ("Target food break-even menu units/day" if product_mode else "Target break-even visits/day"),
                min_value=0.1,
                value=float(current_break_even),
                step=1.0,
            )
        )
    )
    required_db1 = scenario.fixed_overhead_monthly / (
        target_break_even * scenario.days_per_month
    )
    maximum_fixed = (
        target_break_even * scenario.days_per_month * scenario.db1_per_visit
    )
    t1, t2 = st.columns(2)
    t1.metric(("Required contribution/menu unit" if product_mode else "Required contribution/visit"), money(required_db1, scenario.currency))
    t2.metric("Maximum fixed/month", money(maximum_fixed, scenario.currency))
    apply_db1, apply_fixed = st.columns(2)
    if unresolved_operator_cost_ids:
        st.warning(
            "Reverse targets are disabled until triggered operator costs have amounts."
        )
    if apply_db1.button(
        ("Use required contribution/menu unit" if product_mode else "Use required contribution/visit"),
        width="stretch",
        disabled=(
            product_mode
            or result_incomplete
            or required_db1 > scenario.revenue_per_visit
            or bool(unresolved_operator_cost_ids)
        ),
    ):
        scenario.db1_per_visit = required_db1
        sync_package(package)
        st.rerun()
    if apply_fixed.button(
        "Use maximum fixed/month",
        width="stretch",
        disabled=bool(unresolved_operator_cost_ids) or result_incomplete,
    ):
        if fixed_costs is not None and fixed_costs.cost_objects:
            try:
                fixed_costs.set_active_fixed_monthly_total(
                    maximum_fixed,
                    scenario.visits_per_day,
                )
                scenario.fixed_overhead_monthly = maximum_fixed
                sync_package(package)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        else:
            scenario.fixed_overhead_monthly = maximum_fixed
            sync_package(package)
            st.rerun()
    if not product_mode and required_db1 > scenario.revenue_per_visit:
        st.warning(
            "This target requires contribution per visit above revenue per visit. "
            "It cannot be applied without changing more than one assumption."
        )

    st.markdown("**Reference scenarios**")
    st.dataframe(
        [
            {
                "Scenario": item.label,
                "Visits/day": float(item.visits_per_day),
                "Monthly sales": money(item.monthly_gross_sales, item.currency),
                "Core result": money(item.monthly_core_result, item.currency),
                "Status": item.status,
                "Note": item.note or "",
            }
            for item in case_module(package, "economic_scenarios").scenarios
        ],
        width="stretch",
        hide_index=True,
    )


def render_case_result(package: PortablePackage) -> None:
    st.subheader("Case result")
    st.caption("Decision view. Edit assumptions in Economics, Funding, Contracts or Questions.")
    base = case_module(package, "aggregate_scenario")
    costs = case_module(package, "fixed_costs")
    adapters = case_module(package, "revenue_adapters")
    catalog = case_module(package, "product_catalog")
    assets = case_module(package, "assets_revenue")
    funding = case_module(package, "funding")
    if base is None or costs is None:
        st.info("This case does not support a consolidated result view yet.")
        return

    scenario = base.model_copy(deep=True)
    mix = None
    if catalog is not None and catalog.income_mode == CoreIncomeMode.PRODUCT_MIX:
        mix = ProductMixEngine().run(catalog)
        if mix.complete:
            scenario, mix = ProductMixEngine().scenario_for_mix(scenario, catalog)
    scenario.fixed_overhead_monthly = costs.sync_selected_scenario_total(
        scenario.core_entity_id, scenario.visits_per_day
    )
    food = DeterministicEngine().run(scenario)
    books = EntityBooksEngine().run(
        scenario, costs, adapters, product_catalog=catalog
    )
    operator = books.book_for(scenario.core_entity_id)
    incomplete = bool(books.unresolved_cost_ids or books.unresolved_income_fields)

    if incomplete:
        decision = "Cannot yet be assessed"
        detail = "Active income or cost inputs are still unresolved."
    elif food.core_cash_result >= 0:
        decision = "Food can pay for itself under current assumptions"
        detail = "Additional adapters are upside and are not needed to make the food result positive."
    else:
        decision = "Food does not yet pay for itself under current assumptions"
        detail = "Additional adapters improve the site, but do not change the food-only test."
    st.markdown(f"## {decision}")
    st.caption(detail + " This is a modeled reading, not a forecast or validation.")

    st.markdown("**Food business on its own**")
    a, b, c, d = st.columns(4)
    a.metric("Food sales/month", "Incomplete" if incomplete else money(food.monthly_sales, scenario.currency))
    b.metric("Food contribution/month", "Incomplete" if incomplete else money(food.monthly_db1, scenario.currency))
    c.metric("Food operator result/month", "Incomplete" if incomplete else money(food.core_cash_result, scenario.currency))
    d.metric("Food break-even menu units/day", "Incomplete" if incomplete else ("Not available" if food.break_even_visits_per_day is None else f"{float(food.break_even_visits_per_day):,.1f}"))
    st.caption("Menu units are total food and drink items at the current mix. They are not one specific product and not necessarily one customer.")
    if mix is not None and mix.total_units_per_day > 0 and food.break_even_visits_per_day is not None and not incomplete:
        scale = food.break_even_visits_per_day / mix.total_units_per_day
        st.dataframe([{"Menu item": line.label, "Current units/day": f"{float(line.units_per_day):,.1f}", "Units/day at food break-even": f"{float(line.units_per_day * scale):,.1f}"} for line in mix.lines if line.active and line.units_per_day > 0], width="stretch", hide_index=True)

    st.markdown("**Additional site layers**")
    st.caption("These contributions sit outside the food-only break-even.")
    st.dataframe([{"Layer": item.label, "Book": item.entity_id, "Contribution/month": money(item.contribution_monthly, scenario.currency), "State": "Blocked" if item.blocked else ("Disabled" if not item.enabled else item.evidence_state.value)} for item in books.adapter_results], width="stretch", hide_index=True)

    st.markdown("**Who receives the value**")
    e1, e2, e3 = st.columns(3)
    e1.metric("Food operator result/month", money(operator.result_monthly, scenario.currency))
    property_book = next((item for item in books.entity_books if item.entity_id == "property_owner"), None)
    e2.metric("Property-owner result/month", "Not available" if property_book is None else money(property_book.result_monthly, scenario.currency))
    e3.metric("Whole site result/month", money(books.consolidated_result_monthly, scenario.currency))
    st.dataframe([{"Book": item.entity_id, "Inflows": money(item.inflows_monthly, scenario.currency), "Outflows": money(item.outflows_monthly, scenario.currency), "Result": money(item.result_monthly, scenario.currency)} for item in books.entity_books], width="stretch", hide_index=True)

    if assets is not None and funding is not None:
        capex = CapexPortfolioEngine().run(assets, list(scenario.entity_ids), [item.source_id for item in funding.sources])
        st.markdown("**Investment and funding**")
        st.warning(
            "Modeled asset amounts. Read each asset evidence status before using them. "
            "They are not automatically property-owner terms, invoices, payment requests or "
            "commitments by Dennis. Entity names are model roles only."
        )
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Modeled site CAPEX", money(capex.known_site_capex, scenario.currency))
        f2.metric("Assumed upfront cash", money(capex.known_site_upfront_cash, scenario.currency))
        f3.metric("Assumed financed", money(capex.known_site_financed_amount, scenario.currency))
        f4.metric("Unallocated modeled CAPEX", money(max(Decimal("0"), capex.known_site_capex - capex.known_site_upfront_cash - capex.known_site_financed_amount), scenario.currency))
        st.dataframe(
            [
                {
                    "Model role": item.entity_id,
                    "Assumed CAPEX payer": money(item.known_payer_capex, scenario.currency),
                    "Assumed upfront cash": money(item.known_upfront_cash, scenario.currency),
                    "Assumed financed": money(item.known_financed_amount, scenario.currency),
                }
                for item in capex.entity_summaries
                if item.known_payer_capex or item.known_upfront_cash or item.known_financed_amount
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "food_operator means the potential food business in the model. It does not "
            "mean Dennis personally unless a future agreement explicitly says so."
        )
        if capex.unresolved_asset_ids:
            st.warning("Investment reading is incomplete for: " + ", ".join(capex.unresolved_asset_ids))

    if catalog is not None and catalog.volume_scenarios:
        st.markdown("**Food scenarios**")
        rows = []
        for volume in catalog.volume_scenarios:
            working = catalog.model_copy(deep=True)
            working.selected_volume_scenario_id = volume.scenario_id
            try:
                candidate, candidate_mix = ProductMixEngine().scenario_for_mix(base.model_copy(deep=True), working)
            except ValueError:
                rows.append({"Scenario": volume.label, "Food result/month": "Incomplete", "Food break-even/day": "Incomplete"})
                continue
            candidate.fixed_overhead_monthly = costs.sync_selected_scenario_total(candidate.core_entity_id, candidate.visits_per_day)
            candidate_result = DeterministicEngine().run(candidate)
            rows.append({"Scenario": volume.label, "Menu units/day": f"{float(candidate_mix.total_units_per_day):,.1f}", "Food result/month": money(candidate_result.core_cash_result, candidate.currency), "Food break-even/day": "Not available" if candidate_result.break_even_visits_per_day is None else f"{float(candidate_result.break_even_visits_per_day):,.1f}"})
        st.dataframe(rows, width="stretch", hide_index=True)

    if books.unresolved_cost_ids or books.unresolved_income_fields:
        st.markdown("**What still controls the decision**")
        for item in books.unresolved_cost_ids + books.unresolved_income_fields:
            st.write(f"- {item}")

def render_funding(package: PortablePackage) -> None:
    st.subheader("Funding")
    funding = case_module(package, "funding")
    assets = case_module(package, "assets_revenue")
    scenario = case_module(package, "aggregate_scenario")

    if assets is not None and scenario is not None:
        st.markdown("**CAPEX ownership and financing**")
        st.caption(
            "Asset amounts are separate from the legacy workbook funding totals below. "
            "Blank values remain null. Financing funds an asset and is not added to site CAPEX."
        )
        st.warning(
            "Entered amounts inherit each asset evidence status. In a TEST SCENARIO they "
            "are assumptions, not agreed property-owner terms, invoices or personal commitments."
        )
        entity_ids = list(scenario.entity_ids)
        funding_source_ids = [item.source_id for item in funding.sources]
        for asset in assets.assets:
            amount = (
                money(asset.capex_amount, scenario.currency)
                if asset.capex_amount is not None
                else "missing"
            )
            with st.expander(f"{asset.label} · {asset.status} · {amount}"):
                asset.label = st.text_input(
                    "Asset name",
                    asset.label,
                    key=f"asset-label-{asset.asset_id}",
                )
                asset.included_in_capex_plan = st.checkbox(
                    "Include in CAPEX plan",
                    value=asset.included_in_capex_plan,
                    key=f"asset-capex-active-{asset.asset_id}",
                )
                asset.owner_entity_id = st.selectbox(
                    "Asset owner",
                    entity_ids,
                    index=entity_ids.index(asset.owner_entity_id),
                    key=f"asset-owner-{asset.asset_id}",
                )
                payer_options = [""] + entity_ids
                asset.payer_entity_id = (
                    st.selectbox(
                        "CAPEX payer",
                        payer_options,
                        index=payer_options.index(asset.payer_entity_id or ""),
                        key=f"asset-payer-{asset.asset_id}",
                    )
                    or None
                )
                source_options = [""] + funding_source_ids
                asset.funding_source_id = (
                    st.selectbox(
                        "Funding source",
                        source_options,
                        index=source_options.index(asset.funding_source_id or ""),
                        key=f"asset-funding-{asset.asset_id}",
                    )
                    or None
                )
                for field_name, label in (
                    ("capex_amount", "Total CAPEX"),
                    ("upfront_cash_amount", "Upfront cash"),
                    ("financed_amount", "Financed amount"),
                    ("monthly_financing_cost", "Monthly financing cost"),
                    ("monthly_operating_cost", "Monthly operating cost"),
                ):
                    try:
                        setattr(
                            asset,
                            field_name,
                            optional_decimal(
                                st.text_input(
                                    f"{asset.label} {label}",
                                    (
                                        ""
                                        if getattr(asset, field_name) is None
                                        else str(getattr(asset, field_name))
                                    ),
                                    key=f"asset-{field_name}-{asset.asset_id}",
                                ),
                                label,
                            ),
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                asset.status = st.text_input(
                    "Asset status",
                    asset.status,
                    key=f"asset-status-{asset.asset_id}",
                )
                asset.note = st.text_area(
                    "Asset note",
                    asset.note or "",
                    key=f"asset-note-{asset.asset_id}",
                ) or None

        st.markdown("**Add, duplicate or remove assets**")
        with st.expander("Add asset"):
            with st.form("add-asset-form"):
                new_asset_label = st.text_input("New asset name")
                new_asset_owner = st.selectbox("New asset owner", entity_ids)
                add_asset = st.form_submit_button("Add asset")
            if add_asset:
                try:
                    assets.assets.append(
                        AssetDefinition(
                            asset_id=safe_identifier(
                                new_asset_label,
                                {item.asset_id for item in assets.assets},
                                "new_asset",
                            ),
                            label=new_asset_label.strip(),
                            owner_entity_id=new_asset_owner,
                            payer_entity_id=None,
                            included_in_capex_plan=False,
                            status="Hypothesis",
                            note="Added during case exploration; scope, payer and amount remain provisional.",
                        )
                    )
                    sync_package(package)
                    st.rerun()
                except (ValidationError, ValueError) as exc:
                    st.error(str(exc))
        if assets.assets:
            asset_labels = {item.asset_id: item.label for item in assets.assets}
            managed_asset_id = st.selectbox(
                "Asset to duplicate or remove",
                list(asset_labels),
                format_func=asset_labels.get,
                key="manage-asset",
            )
            managed_asset = next(
                item for item in assets.assets
                if item.asset_id == managed_asset_id
            )
            asset_action_left, asset_action_right = st.columns(2)
            if asset_action_left.button("Duplicate asset", width="stretch"):
                clone = managed_asset.model_copy(deep=True)
                clone.asset_id = duplicate_identifier(
                    managed_asset.asset_id,
                    {item.asset_id for item in assets.assets},
                )
                clone.label = f"{managed_asset.label} copy"
                clone.status = "Hypothesis"
                assets.assets.append(clone)
                sync_package(package)
                st.rerun()
            confirm_asset_remove = st.checkbox(
                "Confirm removal of selected asset",
                key=f"confirm-asset-remove-{managed_asset.asset_id}",
            )
            if asset_action_right.button(
                "Remove asset",
                disabled=not confirm_asset_remove,
                width="stretch",
            ):
                assets.assets = [
                    item for item in assets.assets
                    if item.asset_id != managed_asset.asset_id
                ]
                for stream in assets.revenue_streams:
                    if stream.asset_id == managed_asset.asset_id:
                        stream.asset_id = None
                fixed_costs = case_module(package, "fixed_costs")
                if fixed_costs is not None:
                    for cost in fixed_costs.cost_objects:
                        if cost.asset_ref == managed_asset.asset_id:
                            cost.asset_ref = None
                sync_package(package)
                st.rerun()

        try:
            capex_result = CapexPortfolioEngine().run(
                assets,
                entity_ids,
                funding_source_ids,
            )
        except ValueError as exc:
            st.error(str(exc))
            capex_result = None

        if capex_result is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                "Modeled site CAPEX",
                money(capex_result.known_site_capex, scenario.currency),
            )
            c2.metric(
                "Assumed upfront cash",
                money(capex_result.known_site_upfront_cash, scenario.currency),
            )
            c3.metric(
                "Assumed financed",
                money(capex_result.known_site_financed_amount, scenario.currency),
            )
            c4.metric(
                "Monthly financing",
                money(
                    capex_result.known_site_monthly_financing_cost,
                    scenario.currency,
                ),
            )
            st.dataframe(
                [
                    {
                        "Entity": item.entity_id,
                        "Owned CAPEX": money(
                            item.known_owned_capex, scenario.currency
                        ),
                        "Payer commitment": money(
                            item.known_payer_capex, scenario.currency
                        ),
                        "Upfront cash": money(
                            item.known_upfront_cash, scenario.currency
                        ),
                        "Financed": money(
                            item.known_financed_amount, scenario.currency
                        ),
                        "Monthly financing": money(
                            item.known_monthly_financing_cost,
                            scenario.currency,
                        ),
                    }
                    for item in capex_result.entity_summaries
                ],
                width="stretch",
                hide_index=True,
            )
            st.dataframe(
                [
                    {
                        "Asset": asset.label,
                        "Owner": asset.owner_entity_id,
                        "Payer": asset.payer_entity_id or "Missing",
                        "Funding source": asset.funding_source_id or "Missing",
                        "CAPEX": (
                            money(asset.capex_amount, scenario.currency)
                            if asset.capex_amount is not None
                            else "Missing"
                        ),
                        "Upfront cash": (
                            money(asset.upfront_cash_amount, scenario.currency)
                            if asset.upfront_cash_amount is not None
                            else "Missing"
                        ),
                        "Financed": (
                            money(asset.financed_amount, scenario.currency)
                            if asset.financed_amount is not None
                            else "Missing"
                        ),
                        "Status": asset.status,
                    }
                    for asset in assets.assets
                    if asset.included_in_capex_plan
                ],
                width="stretch",
                hide_index=True,
            )
            if capex_result.unresolved_asset_ids:
                st.warning(
                    "CAPEX assets still missing total amount or payer: "
                    + ", ".join(capex_result.unresolved_asset_ids)
                )

    st.markdown("**Legacy funding requirements**")
    for item in funding.requirements:
        with st.expander(f"{item.label} · {money(item.amount, item.currency)} · {item.status}"):
            item.amount = Decimal(
                str(st.number_input("Amount", min_value=0.0, value=float(item.amount), key=f"req-amount-{item.requirement_id}"))
            )
            item.status = st.text_input("Status", item.status, key=f"req-status-{item.requirement_id}")
            item.note = st.text_area("Note", item.note or "", key=f"req-note-{item.requirement_id}") or None
    st.markdown("**Sources**")
    for item in funding.sources:
        with st.expander(f"{item.label} · {money(item.amount, item.currency)} · {item.status}"):
            item.amount = Decimal(
                str(st.number_input("Amount", min_value=0.0, value=float(item.amount), key=f"source-amount-{item.source_id}"))
            )
            item.status = st.text_input("Status", item.status, key=f"source-status-{item.source_id}")
            item.restricted = st.checkbox("Restricted", item.restricted, key=f"source-restricted-{item.source_id}")
            item.note = st.text_area("Note", item.note or "", key=f"source-note-{item.source_id}") or None
    st.markdown("**Risks and missing terms**")
    st.dataframe(
        [
            {"Risk": risk.label, "Status": risk.status, "Note": risk.note}
            for risk in funding.risks
        ],
        width="stretch",
        hide_index=True,
    )


def render_contracts(package: PortablePackage) -> None:
    st.subheader("Contract options")
    contracts = case_module(package, "contracts")
    scenario = case_module(package, "aggregate_scenario")
    entity_ids = list(scenario.entity_ids)
    st.caption("Leave unknown commercial terms blank. Blank values remain null in the export.")
    for contract in contracts.scenarios:
        with st.expander(f"{contract.label} · {contract.status}"):
            contract.label = st.text_input(
                "Contract name",
                contract.label,
                key=f"contract-label-{contract.contract_id}",
            )
            kinds = [item.value for item in ContractStructureKind]
            contract.kind = ContractStructureKind(
                st.selectbox(
                    "Contract structure",
                    kinds,
                    index=kinds.index(contract.kind.value),
                    key=f"contract-kind-{contract.contract_id}",
                )
            )
            party_options = [""] + entity_ids
            contract.payer_entity_id = (
                st.selectbox(
                    "Contract payer",
                    party_options,
                    index=party_options.index(contract.payer_entity_id or ""),
                    key=f"contract-payer-{contract.contract_id}",
                )
                or None
            )
            contract.recipient_entity_id = (
                st.selectbox(
                    "Contract recipient",
                    party_options,
                    index=party_options.index(contract.recipient_entity_id or ""),
                    key=f"contract-recipient-{contract.contract_id}",
                )
                or None
            )
            contract.status = st.text_input(
                "Status", contract.status, key=f"contract-status-{contract.contract_id}"
            )
            try:
                contract.fixed_payment_monthly = optional_decimal(
                    st.text_input(
                        "Fixed payment/month",
                        "" if contract.fixed_payment_monthly is None else str(contract.fixed_payment_monthly),
                        key=f"contract-fixed-{contract.contract_id}",
                    ),
                    "Fixed payment/month",
                )
                contract.revenue_share_rate = optional_decimal(
                    st.text_input(
                        "Revenue share rate (0-1)",
                        "" if contract.revenue_share_rate is None else str(contract.revenue_share_rate),
                        key=f"contract-share-{contract.contract_id}",
                    ),
                    "Revenue share rate",
                )
                if contract.revenue_share_rate is not None and contract.revenue_share_rate > 1:
                    raise ValueError("Revenue share rate cannot exceed 1")
                contract.minimum_guarantee_monthly = optional_decimal(
                    st.text_input(
                        "Minimum guarantee/month",
                        "" if contract.minimum_guarantee_monthly is None else str(contract.minimum_guarantee_monthly),
                        key=f"contract-minimum-{contract.contract_id}",
                    ),
                    "Minimum guarantee/month",
                )
                contract.one_time_amount = optional_decimal(
                    st.text_input(
                        "One-time amount",
                        "" if contract.one_time_amount is None else str(contract.one_time_amount),
                        key=f"contract-once-{contract.contract_id}",
                    ),
                    "One-time amount",
                )
            except ValueError as exc:
                st.error(str(exc))
            contract.note = st.text_area(
                "Note", contract.note or "", key=f"contract-note-{contract.contract_id}"
            ) or None

    st.markdown("**Add, duplicate or remove contract options**")
    with st.expander("Add contract option"):
        with st.form("add-contract-form"):
            new_contract_label = st.text_input("New contract name")
            new_contract_kind = st.selectbox(
                "New contract structure",
                [item.value for item in ContractStructureKind],
            )
            add_contract = st.form_submit_button("Add contract")
        if add_contract:
            try:
                contracts.scenarios.append(
                    ContractScenario(
                        contract_id=safe_identifier(
                            new_contract_label,
                            {item.contract_id for item in contracts.scenarios},
                            "new_contract",
                        ),
                        label=new_contract_label.strip(),
                        kind=ContractStructureKind(new_contract_kind),
                        parties=entity_ids[:2],
                        currency=scenario.currency,
                        status="Hypothesis",
                        note="Added during case exploration; terms remain unanswered.",
                    )
                )
                sync_package(package)
                st.rerun()
            except (ValidationError, ValueError) as exc:
                st.error(str(exc))
    if contracts.scenarios:
        contract_labels = {
            item.contract_id: item.label for item in contracts.scenarios
        }
        managed_contract_id = st.selectbox(
            "Contract option to duplicate or remove",
            list(contract_labels),
            format_func=contract_labels.get,
            key="manage-contract-option",
        )
        managed_contract = next(
            item for item in contracts.scenarios
            if item.contract_id == managed_contract_id
        )
        contract_action_left, contract_action_right = st.columns(2)
        if contract_action_left.button("Duplicate contract", width="stretch"):
            clone = managed_contract.model_copy(deep=True)
            clone.contract_id = duplicate_identifier(
                managed_contract.contract_id,
                {item.contract_id for item in contracts.scenarios},
            )
            clone.label = f"{managed_contract.label} copy"
            clone.status = "Hypothesis"
            contracts.scenarios.append(clone)
            sync_package(package)
            st.rerun()
        confirm_contract_remove = st.checkbox(
            "Confirm removal of selected contract",
            key=f"confirm-contract-remove-{managed_contract.contract_id}",
        )
        if contract_action_right.button(
            "Remove contract",
            disabled=not confirm_contract_remove,
            width="stretch",
        ):
            contracts.scenarios = [
                item for item in contracts.scenarios
                if item.contract_id != managed_contract.contract_id
            ]
            fixed_costs = case_module(package, "fixed_costs")
            if fixed_costs is not None:
                for cost in fixed_costs.cost_objects:
                    if cost.contract_ref == managed_contract.contract_id:
                        cost.contract_ref = None
            sync_package(package)
            st.rerun()


def render_questions(package: PortablePackage) -> None:
    st.subheader("Questions and decision gates")
    decision_plan = case_module(package, "decision_plan")
    blocking = [gate for gate in decision_plan.gates if gate.state.value in {"FAIL", "BLOCKED"}]
    if blocking:
        st.warning(f"{len(blocking)} blocking or failed decision gates remain visible.")
    st.dataframe(
        [
            {
                "Gate": gate.label,
                "State": gate.state.value,
                "Severity": gate.severity,
                "Why": gate.why,
                "Evidence needed": gate.evidence_needed or "",
            }
            for gate in decision_plan.gates
        ],
        width="stretch",
        hide_index=True,
    )
    st.markdown("**Stakeholder questions**")
    for question in decision_plan.stakeholder_questions:
        with st.expander(f"{question.label} · {question.status}"):
            question.status = st.text_input(
                "Status", question.status, key=f"question-status-{question.question_id}"
            )
            answer = package.workspace.stakeholder_answers.get(question.question_id, "")
            answer = st.text_area("Answer", answer, key=f"question-answer-{question.question_id}")
            if answer.strip():
                package.workspace.stakeholder_answers[question.question_id] = answer
            else:
                package.workspace.stakeholder_answers.pop(question.question_id, None)
            question.note = st.text_area(
                "Evidence note", question.note or "", key=f"question-note-{question.question_id}"
            ) or None


def render_brief(package: PortablePackage) -> None:
    st.subheader("Meeting brief")
    package.workspace.meeting_brief_markdown = st.text_area(
        "Brief markdown", package.workspace.meeting_brief_markdown, height=520
    )


def render_export(package: PortablePackage) -> None:
    st.sidebar.divider()
    st.sidebar.caption("Portable case file")
    filename = f"{package.metadata.case_id}.marketgap.json"
    payload = (
        dump_case_package_v2_json(package)
        if isinstance(package, CasePackageV2)
        else dump_case_package_json(package)
    )
    st.sidebar.download_button(
        "Export case",
        data=payload,
        file_name=filename,
        mime="application/json",
        width="stretch",
    )
    st.sidebar.caption("Export creates a new file. The imported source is not overwritten.")


def render_workspace() -> None:
    package = package_from_state()
    if package is None:
        st.session_state["surface"] = "home"
        st.rerun()
    assert package is not None
    views = ["Overview"]
    if case_module(package, "aggregate_scenario") is not None and case_module(package, "fixed_costs") is not None:
        views.append("Case result")
    if case_module(package, "demand_surface") is not None:
        views.append("Demand")
    if (
        case_module(package, "aggregate_scenario") is not None
        and case_module(package, "economic_scenarios") is not None
    ):
        views.append("Economics")
    if case_module(package, "funding") is not None:
        views.append("Funding")
    if case_module(package, "contracts") is not None:
        views.append("Contracts")
    if case_module(package, "decision_plan") is not None:
        views.append("Questions")
    views.append("Brief")
    render_workspace_header(package)
    view = st.sidebar.radio(
        "Workspace",
        views,
    )
    if view == "Overview":
        render_overview(package)
    elif view == "Case result":
        render_case_result(package)
    elif view == "Demand":
        render_demand(package)
    elif view == "Economics":
        render_economics(package)
    elif view == "Funding":
        render_funding(package)
    elif view == "Contracts":
        render_contracts(package)
    elif view == "Questions":
        render_questions(package)
    else:
        render_brief(package)
    sync_package(package)
    render_export(package)


st.set_page_config(page_title="Hedegreen Research Market Gaps", layout="wide")
st.session_state.setdefault("surface", "home")

if st.session_state["surface"] == "workspace":
    render_workspace()
elif st.session_state["surface"] == "public-case":
    render_public_case()
elif st.session_state["surface"] == "new":
    render_new_case()
else:
    render_home()
