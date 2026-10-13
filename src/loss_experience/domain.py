"""Domain types and pure calculations for loss experience. No I/O, no framework imports.

Terms follow docs/GLOSSARY.md. A `_dkk` field is in DKK; `paid_amount`, `reserve_amount` and
`annual_premium` are in the `currency` their own row states and are converted only through `to_dkk`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import fmean
from typing import ClassVar, assert_never


class Peril(StrEnum):
    FIRE = "fire"
    FLOOD = "flood"
    HAIL = "hail"
    STORM = "storm"
    SUBSIDENCE = "subsidence"


class ClaimStatus(StrEnum):
    SETTLED = "settled"
    OPEN = "open"
    WITHDRAWN = "withdrawn"
    DECLINED = "declined"


class Currency(StrEnum):
    DKK = "DKK"
    EUR = "EUR"


class ExclusionReason(StrEnum):
    POLICY_NOT_FOUND = "policy_not_found"
    NEGATIVE_PAID_AMOUNT = "negative_paid_amount"


@dataclass(frozen=True)
class Asset:
    asset_id: str
    portfolio_id: str
    region: str
    asset_type: str
    construction_year: int
    sum_insured_dkk: float


@dataclass(frozen=True)
class Policy:
    policy_id: str
    asset_id: str
    peril: Peril
    inception_date: date
    expiry_date: date
    annual_premium: float
    currency: Currency


@dataclass(frozen=True)
class Claim:
    claim_id: str
    policy_id: str
    loss_date: date
    reported_date: date
    paid_amount: float
    reserve_amount: float
    currency: Currency
    status: ClaimStatus


@dataclass(frozen=True)
class Exclusion:
    """A source Claim left out of every result, with the Incurred loss it would have had."""

    reason: ExclusionReason
    claim_id: str
    amount_dkk: float


class MissingFxRate(LookupError):
    """No rate for a currency in a month. Never defaulted to 1 or 0."""


@dataclass(frozen=True)
class FxTable:
    """DKK per unit of a currency, keyed by (year, month, currency)."""

    rates_dkk_per_unit: Mapping[tuple[int, int, Currency], float]

    def rate(self, year: int, month: int, currency: Currency) -> float:
        found = self.rates_dkk_per_unit.get((year, month, currency))
        if found is None:
            raise MissingFxRate(f"no {currency} rate for {year:04d}-{month:02d}")
        return found


@dataclass(frozen=True)
class DataQuality:
    """What load repaired or flagged. A Repair changes a value; a flag keeps the row as it is."""

    peril_spellings_repaired: int
    day_first_loss_dates_repaired: int
    day_first_reported_dates_repaired: int
    loss_before_inception_flagged: int
    settled_with_reserve_flagged: int
    settled_reserve_dkk: float
    mixed_currency_claims: int
    overlapping_terms: int


@dataclass(frozen=True)
class Book:
    """Everything loaded. Every Claim names a known Policy; excluded Claims are only Exclusions."""

    assets: tuple[Asset, ...]
    policies: tuple[Policy, ...]
    claims: tuple[Claim, ...]
    fx: FxTable
    exclusions: tuple[Exclusion, ...]
    data_quality: DataQuality


def to_dkk(amount: float, currency: Currency, on: date, fx: FxTable) -> float:
    """`amount` in `currency`, at that currency's rate for the month of `on`."""
    return amount * fx.rate(on.year, on.month, currency)


def incurred_loss_dkk(claim: Claim, fx: FxTable) -> float:
    """settled: paid; open: paid plus reserve; withdrawn and declined: 0. In DKK at the loss
    month, converted from the Claim's own currency."""
    match claim.status:
        case ClaimStatus.SETTLED:
            amount = claim.paid_amount
        case ClaimStatus.OPEN:
            amount = claim.paid_amount + claim.reserve_amount
        case ClaimStatus.WITHDRAWN | ClaimStatus.DECLINED:
            return 0.0
        case _:
            assert_never(claim.status)
    return to_dkk(amount, claim.currency, claim.loss_date, fx)


# --- Starter assessment skeleton, kept only so api.py and its tests import until U2 ---------


class Status(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class Ok:
    value: float
    status: ClassVar[Status] = Status.OK


@dataclass(frozen=True)
class InsufficientData:
    status: ClassVar[Status] = Status.INSUFFICIENT_DATA


type Outcome = Ok | InsufficientData


@dataclass(frozen=True)
class Provenance:
    source: str


@dataclass(frozen=True)
class Observations:
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
    total = len(observations.values)
    valid = [v for v in observations.values if v is not None]
    coverage = len(valid) / total if total else 0.0
    outcome = Ok(fmean(valid)) if valid and coverage >= min_coverage else InsufficientData()
    return Assessment(observations.asset_id, outcome, coverage, observations.provenance)
