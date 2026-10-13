"""Domain types and pure calculations. No I/O, no framework imports.

Terms follow docs/GLOSSARY.md. Rename `value` to the task's metric with its unit
(for example `mean_ndvi` or `depth_m`) once the task names it.
"""

from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean
from typing import ClassVar


class Status(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    # Add OUT_OF_COVERAGE, and its Outcome class, only when the task's data has an area or
    # period an Asset can fall outside.


@dataclass(frozen=True)
class Ok:
    value: float
    status: ClassVar[Status] = Status.OK


@dataclass(frozen=True)
class InsufficientData:
    status: ClassVar[Status] = Status.INSUFFICIENT_DATA


# Only Ok carries a value, so "ok without a value" and "missing with a value" cannot be built.
type Outcome = Ok | InsufficientData


@dataclass(frozen=True)
class Provenance:
    source: str


@dataclass(frozen=True)
class Observations:
    """Every sample for one Asset. `None` is nodata, never zero."""

    asset_id: str
    values: tuple[float | None, ...]
    provenance: Provenance


@dataclass(frozen=True)
class Assessment:
    asset_id: str
    outcome: Outcome
    coverage_fraction: float
    provenance: Provenance


def assess(observations: Observations, *, min_coverage: float) -> Assessment:
    """Mean of the valid samples, or insufficient data when coverage is below `min_coverage`."""
    total = len(observations.values)
    valid = [v for v in observations.values if v is not None]
    coverage = len(valid) / total if total else 0.0

    outcome = Ok(fmean(valid)) if valid and coverage >= min_coverage else InsufficientData()
    return Assessment(observations.asset_id, outcome, coverage, observations.provenance)
