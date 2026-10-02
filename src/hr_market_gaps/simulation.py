from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from random import Random
from statistics import mean

from .engine import DeterministicEngine
from .models import AggregateScenario


@dataclass(frozen=True)
class TriangularAssumption:
    """Explicit low/base/high uncertainty for one numeric scenario field."""

    field: str
    low: Decimal
    base: Decimal
    high: Decimal
    label: str
    unit: str


@dataclass(frozen=True)
class SimulationConfig:
    runs: int
    seed: int
    assumptions: tuple[TriangularAssumption, ...]


@dataclass(frozen=True)
class SimulationResult:
    runs: int
    seed: int
    percentiles: dict[str, dict[str, Decimal]]
    probability_core_positive: Decimal
    probability_capacity_breach: Decimal | None
    drivers: list[tuple[str, Decimal]]


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("Cannot calculate percentiles for an empty simulation")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _correlation(xs: list[Decimal], ys: list[Decimal]) -> Decimal:
    if len(xs) < 2 or len(xs) != len(ys):
        return Decimal("0")
    x_mean = mean(float(x) for x in xs)
    y_mean = mean(float(y) for y in ys)
    dx = [float(x) - x_mean for x in xs]
    dy = [float(y) - y_mean for y in ys]
    x_var = sum(value * value for value in dx)
    y_var = sum(value * value for value in dy)
    if x_var == 0 or y_var == 0:
        return Decimal("0")
    corr = sum(a * b for a, b in zip(dx, dy)) / ((x_var * y_var) ** 0.5)
    return Decimal(str(abs(corr)))


class MonteCarloSimulator:
    """Generic aggregate-case risk simulation.

    The simulator only samples fields that the caller explicitly marks as
    uncertain. Scenario points are never interpreted as probability
    distributions unless the caller supplies them as assumptions.
    """

    def __init__(self, engine: DeterministicEngine | None = None) -> None:
        self.engine = engine or DeterministicEngine()

    def run(self, scenario: AggregateScenario, config: SimulationConfig) -> SimulationResult:
        if config.runs <= 0:
            raise ValueError("runs must be positive")
        rng = Random(config.seed)
        metrics = {
            "monthly_sales": [],
            "monthly_db1": [],
            "core_cash_result": [],
        }
        capacity_breaches = 0
        sampled_inputs: dict[str, list[Decimal]] = {
            assumption.field: [] for assumption in config.assumptions
        }

        for _ in range(config.runs):
            update: dict[str, Decimal] = {}
            for assumption in config.assumptions:
                value = Decimal(
                    str(
                        rng.triangular(
                            float(assumption.low),
                            float(assumption.high),
                            float(assumption.base),
                        )
                    )
                )
                update[assumption.field] = value
                sampled_inputs[assumption.field].append(value)

            sampled = scenario.model_copy(update=update)
            result = self.engine.run(sampled)
            metrics["monthly_sales"].append(result.monthly_sales)
            metrics["monthly_db1"].append(result.monthly_db1)
            metrics["core_cash_result"].append(result.core_cash_result)
            if result.average_idle_minutes_per_hour == 0:
                capacity_breaches += 1

        percentile_points = {
            "P05": Decimal("0.05"),
            "P25": Decimal("0.25"),
            "P50": Decimal("0.50"),
            "P75": Decimal("0.75"),
            "P95": Decimal("0.95"),
        }
        percentiles = {
            metric: {
                label: _percentile(values, fraction)
                for label, fraction in percentile_points.items()
            }
            for metric, values in metrics.items()
        }
        positive_count = sum(
            1 for value in metrics["core_cash_result"] if value > Decimal("0")
        )
        drivers = sorted(
            (
                (
                    next(
                        assumption.label
                        for assumption in config.assumptions
                        if assumption.field == field
                    ),
                    _correlation(values, metrics["core_cash_result"]),
                )
                for field, values in sampled_inputs.items()
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        return SimulationResult(
            runs=config.runs,
            seed=config.seed,
            percentiles=percentiles,
            probability_core_positive=Decimal(positive_count) / Decimal(config.runs),
            probability_capacity_breach=Decimal(capacity_breaches) / Decimal(config.runs),
            drivers=drivers,
        )
