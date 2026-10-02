from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .case_package_v2 import (
    CasePackageV2,
    NetworkMarketDesign,
    PublicArtifact,
    PublicCaseRecord,
    build_joint_product_v2_package,
    build_network_market_v2_package,
)
from .loader import load_joint_product_scenario


class TidAdapterError(ValueError):
    """The canonical TID register cannot be projected safely into app packages."""


class TidCaseLink(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    label: str = Field(min_length=1)
    href: str = Field(min_length=1)
    download: bool = False


class TidMarketGapCase(BaseModel):
    """Public-safe fields consumed from the richer canonical TID record."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    hr_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    maturity: str | None = None
    status: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    boundaries: list[str] = Field(default_factory=list)
    links: list[TidCaseLink] = Field(default_factory=list)


class TidMarketGapRegistry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    objects: list[TidMarketGapCase]


def load_tid_market_gap_registry(path: str | Path) -> TidMarketGapRegistry:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        registry = TidMarketGapRegistry.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise TidAdapterError(f"Invalid TID Market Gaps registry: {exc}") from exc
    if registry.slug != "market-gaps":
        raise TidAdapterError(
            f"Expected Market Gaps registry, received {registry.slug!r}"
        )
    slugs = [case.slug for case in registry.objects]
    if len(slugs) != len(set(slugs)):
        raise TidAdapterError("TID Market Gaps case slugs must be unique")
    return registry


def _public_record(
    registry: TidMarketGapRegistry,
    case: TidMarketGapCase,
) -> PublicCaseRecord:
    return PublicCaseRecord(
        registry_id=f"hr.registry.{registry.slug}.0001",
        case_id=case.case_id,
        title=case.title,
        status=case.status,
        maturity=case.maturity,
        summary=case.summary,
        boundaries=case.boundaries,
        artifacts=[
            PublicArtifact(
                label=link.label,
                href=link.href,
                kind="download" if link.download else "link",
            )
            for link in case.links
        ],
    )


def _load_network_design(path: Path) -> NetworkMarketDesign:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return NetworkMarketDesign.model_validate(raw)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise TidAdapterError(f"Invalid network-market design: {exc}") from exc


def build_public_case_packages(
    project_root: str | Path,
    tid_registry_path: str | Path,
) -> dict[str, CasePackageV2]:
    """Build the reviewed public app bundle from the canonical TID register."""

    project_root = Path(project_root).resolve()
    registry = load_tid_market_gap_registry(tid_registry_path)
    packages: dict[str, CasePackageV2] = {}

    for case in registry.objects:
        record = _public_record(registry, case)
        if case.slug == "100-burger-a-day":
            scenario = load_joint_product_scenario(
                project_root
                / "cases"
                / "100_burger_a_day"
                / "public_article_bridge.yaml"
            )
            package = build_joint_product_v2_package(scenario, record=record)
        elif case.slug == "the-two-person-market":
            design = _load_network_design(
                project_root
                / "cases"
                / "two_person_market"
                / "design_target.yaml"
            )
            package = build_network_market_v2_package(design, record=record)
        else:
            raise TidAdapterError(
                "Public TID case has no reviewed interactive adapter: "
                f"{case.slug}"
            )

        if package.metadata.visibility.value != "PUBLIC":
            raise TidAdapterError(
                f"Public adapter produced non-public package: {case.slug}"
            )
        packages[case.slug] = package

    return packages

