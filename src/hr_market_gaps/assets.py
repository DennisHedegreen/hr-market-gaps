from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetDefinition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    owner_entity_id: str = Field(min_length=1)
    payer_entity_id: str | None = None
    funding_source_id: str | None = None
    included_in_capex_plan: bool = True
    status: str = Field(min_length=1)
    capex_amount: Decimal | None = Field(default=None, ge=0)
    upfront_cash_amount: Decimal | None = Field(default=None, ge=0)
    financed_amount: Decimal | None = Field(default=None, ge=0)
    monthly_financing_cost: Decimal | None = Field(default=None, ge=0)
    monthly_operating_cost: Decimal | None = Field(default=None, ge=0)
    note: str | None = None


class CaseRevenueStream(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    stream_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    owner_entity_id: str = Field(min_length=1)
    asset_id: str | None = None
    adapter_id: str | None = None
    status: str = Field(min_length=1)
    note: str | None = None


class AssetRevenueLayer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    layer_id: str = Field(min_length=1)
    assets: list[AssetDefinition] = Field(default_factory=list)
    revenue_streams: list[CaseRevenueStream] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_are_valid(self) -> "AssetRevenueLayer":
        asset_ids = [asset.asset_id for asset in self.assets]
        stream_ids = [stream.stream_id for stream in self.revenue_streams]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_id values must be unique")
        if len(stream_ids) != len(set(stream_ids)):
            raise ValueError("stream_id values must be unique")
        known_assets = set(asset_ids)
        unknown_assets = sorted(
            {
                stream.asset_id
                for stream in self.revenue_streams
                if stream.asset_id is not None and stream.asset_id not in known_assets
            }
        )
        if unknown_assets:
            raise ValueError(
                "revenue_stream asset_id values must reference known assets: "
                + ", ".join(unknown_assets)
            )
        return self


class EntityCapexSummary(BaseModel):
    entity_id: str = Field(min_length=1)
    known_owned_capex: Decimal = Decimal("0")
    known_payer_capex: Decimal = Decimal("0")
    known_upfront_cash: Decimal = Decimal("0")
    known_financed_amount: Decimal = Decimal("0")
    known_monthly_financing_cost: Decimal = Decimal("0")


class CapexPortfolioResult(BaseModel):
    entity_summaries: list[EntityCapexSummary]
    known_site_capex: Decimal = Decimal("0")
    known_site_upfront_cash: Decimal = Decimal("0")
    known_site_financed_amount: Decimal = Decimal("0")
    known_site_monthly_financing_cost: Decimal = Decimal("0")
    unresolved_asset_ids: list[str] = Field(default_factory=list)

    def summary_for(self, entity_id: str) -> EntityCapexSummary:
        return next(
            item for item in self.entity_summaries if item.entity_id == entity_id
        )


class CapexPortfolioEngine:
    """Summarize asset CAPEX once while retaining owner, payer and funding roles."""

    def run(
        self,
        layer: AssetRevenueLayer,
        entity_ids: list[str],
        funding_source_ids: list[str] | None = None,
    ) -> CapexPortfolioResult:
        known_entities = set(entity_ids)
        known_sources = set(funding_source_ids or [])
        summaries = {
            entity_id: EntityCapexSummary(entity_id=entity_id)
            for entity_id in entity_ids
        }
        unresolved: list[str] = []
        site_capex = Decimal("0")
        site_upfront = Decimal("0")
        site_financed = Decimal("0")
        site_monthly_financing = Decimal("0")

        for asset in layer.assets:
            if not asset.included_in_capex_plan:
                continue
            if asset.owner_entity_id not in known_entities:
                raise ValueError(f"Unknown asset owner entity_id: {asset.owner_entity_id}")
            if (
                asset.payer_entity_id is not None
                and asset.payer_entity_id not in known_entities
            ):
                raise ValueError(f"Unknown asset payer entity_id: {asset.payer_entity_id}")
            if (
                asset.funding_source_id is not None
                and asset.funding_source_id not in known_sources
            ):
                raise ValueError(
                    f"Unknown asset funding source: {asset.funding_source_id}"
                )
            if (
                asset.capex_amount is not None
                and asset.upfront_cash_amount is not None
                and asset.financed_amount is not None
                and asset.upfront_cash_amount + asset.financed_amount
                > asset.capex_amount
            ):
                raise ValueError(
                    f"Asset funding exceeds CAPEX amount: {asset.asset_id}"
                )

            owner_summary = summaries[asset.owner_entity_id]
            if asset.capex_amount is not None:
                owner_summary.known_owned_capex += asset.capex_amount
                site_capex += asset.capex_amount

            if asset.payer_entity_id is not None:
                payer_summary = summaries[asset.payer_entity_id]
                if asset.capex_amount is not None:
                    payer_summary.known_payer_capex += asset.capex_amount
                if asset.upfront_cash_amount is not None:
                    payer_summary.known_upfront_cash += asset.upfront_cash_amount
                if asset.financed_amount is not None:
                    payer_summary.known_financed_amount += asset.financed_amount
                if asset.monthly_financing_cost is not None:
                    payer_summary.known_monthly_financing_cost += (
                        asset.monthly_financing_cost
                    )

            site_upfront += asset.upfront_cash_amount or Decimal("0")
            site_financed += asset.financed_amount or Decimal("0")
            site_monthly_financing += (
                asset.monthly_financing_cost or Decimal("0")
            )
            if asset.capex_amount is None or asset.payer_entity_id is None:
                unresolved.append(asset.asset_id)

        return CapexPortfolioResult(
            entity_summaries=list(summaries.values()),
            known_site_capex=site_capex,
            known_site_upfront_cash=site_upfront,
            known_site_financed_amount=site_financed,
            known_site_monthly_financing_cost=site_monthly_financing,
            unresolved_asset_ids=unresolved,
        )
