"""Load the four source CSVs into a Book. The only place that parses; input is checked here, once.

The policy for awkward rows is docs/DECISIONS.md D14: peril spellings and day-first dates are
repaired and counted; a Claim that cannot be a cost of a known Policy becomes an Exclusion with
its DKK amount; everything else is kept, and the oddities that do not change a result are flagged.
"""

import csv
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Protocol

from loss_experience.domain import (
    Asset,
    Book,
    Claim,
    ClaimStatus,
    Currency,
    DataQuality,
    Exclusion,
    ExclusionReason,
    FxTable,
    Observations,
    Peril,
    Policy,
    Provenance,
    incurred_loss_dkk,
    to_dkk,
)

ASSET_COLUMNS = (
    "asset_id",
    "portfolio_id",
    "region",
    "asset_type",
    "construction_year",
    "sum_insured_dkk",
)
POLICY_COLUMNS = (
    "policy_id",
    "asset_id",
    "peril",
    "inception_date",
    "expiry_date",
    "annual_premium",
    "currency",
)
CLAIM_COLUMNS = (
    "claim_id",
    "policy_id",
    "loss_date",
    "reported_date",
    "paid_amount",
    "reserve_amount",
    "currency",
    "status",
)
FX_COLUMNS = ("month", "currency", "rate_dkk_per_unit")

type Row = Mapping[str, str]
type FxKey = tuple[int, int, Currency]


def load_book(data_dir: Path) -> Book:
    """assets.csv, policies.csv, claims.csv and fx_rates.csv from `data_dir`. No state: the
    same files give an equal Book."""
    fx_rows = _load(data_dir / "fx_rates.csv", FX_COLUMNS, _fx_rate)
    _require_unique([key for key, _ in fx_rows], "fx_rates.csv (month, currency)")
    fx = FxTable(dict(fx_rows))

    assets = tuple(_load(data_dir / "assets.csv", ASSET_COLUMNS, _asset))
    _require_unique([asset.asset_id for asset in assets], "assets.csv asset_id")

    parsed_policies = _load(data_dir / "policies.csv", POLICY_COLUMNS, _policy)
    policies = tuple(policy for policy, _ in parsed_policies)
    _require_unique([policy.policy_id for policy in policies], "policies.csv policy_id")
    policy_by_id = {policy.policy_id: policy for policy in policies}

    parsed_claims = _load(data_dir / "claims.csv", CLAIM_COLUMNS, _claim)
    _require_unique([claim.claim_id for claim, _, _ in parsed_claims], "claims.csv claim_id")

    claims: list[Claim] = []
    exclusions: list[Exclusion] = []
    for claim, _, _ in parsed_claims:
        reason = _exclusion_reason(claim, policy_by_id)
        if reason is None:
            claims.append(claim)
        else:
            exclusions.append(Exclusion(reason, claim.claim_id, incurred_loss_dkk(claim, fx)))

    settled_with_reserve = [
        claim
        for claim in claims
        if claim.status is ClaimStatus.SETTLED and claim.reserve_amount > 0
    ]
    quality = DataQuality(
        peril_spellings_repaired=sum(repaired for _, repaired in parsed_policies),
        day_first_loss_dates_repaired=sum(loss for _, loss, _ in parsed_claims),
        day_first_reported_dates_repaired=sum(reported for _, _, reported in parsed_claims),
        loss_before_inception_flagged=sum(
            claim.loss_date < policy_by_id[claim.policy_id].inception_date for claim in claims
        ),
        settled_with_reserve_flagged=len(settled_with_reserve),
        settled_reserve_dkk=math.fsum(
            to_dkk(claim.reserve_amount, claim.currency, claim.loss_date, fx)
            for claim in settled_with_reserve
        ),
        mixed_currency_claims=sum(
            claim.currency is not policy_by_id[claim.policy_id].currency for claim in claims
        ),
        overlapping_terms=_overlapping_terms(policies),
    )
    return Book(assets, policies, tuple(claims), fx, tuple(exclusions), quality)


def _exclusion_reason(claim: Claim, policy_by_id: Mapping[str, Policy]) -> ExclusionReason | None:
    if claim.policy_id not in policy_by_id:
        return ExclusionReason.POLICY_NOT_FOUND
    if claim.paid_amount < 0:
        return ExclusionReason.NEGATIVE_PAID_AMOUNT
    return None


def _overlapping_terms(policies: Sequence[Policy]) -> int:
    """Consecutive terms of one Asset and Peril where the later incepts on or before the
    earlier's expiry date."""
    terms: dict[tuple[str, Peril], list[Policy]] = {}
    for policy in policies:
        terms.setdefault((policy.asset_id, policy.peril), []).append(policy)
    return sum(
        later.inception_date <= earlier.expiry_date
        for group in terms.values()
        for earlier, later in pairwise(sorted(group, key=lambda policy: policy.inception_date))
    )


def _load[T](path: Path, columns: Sequence[str], parse: Callable[[Row], T]) -> list[T]:
    records: list[T] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        missing = sorted(set(columns) - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"{path.name} lacks columns {missing}")
        for line, row in enumerate(reader, start=2):
            try:
                records.append(parse(row))
            except ValueError as error:
                raise ValueError(f"{path.name}:{line}: {error}") from error
    return records


def _require_unique[K](keys: Sequence[K], what: str) -> None:
    repeated = sorted(str(key) for key, count in Counter(keys).items() if count > 1)
    if repeated:
        raise ValueError(f"{what} repeats {len(repeated)} values, first {repeated[:3]}")


def _fx_rate(row: Row) -> tuple[FxKey, float]:
    month = datetime.strptime(row["month"], "%Y-%m")
    rate = _number(row["rate_dkk_per_unit"])
    if rate <= 0:
        raise ValueError(f"rate {rate} is not positive")
    return (month.year, month.month, Currency(row["currency"])), rate


def _asset(row: Row) -> Asset:
    return Asset(
        asset_id=row["asset_id"],
        portfolio_id=row["portfolio_id"],
        region=row["region"],
        asset_type=row["asset_type"],
        construction_year=int(row["construction_year"]),
        sum_insured_dkk=_number(row["sum_insured_dkk"]),
    )


def _policy(row: Row) -> tuple[Policy, bool]:
    """The Policy, and whether its peril spelling was repaired."""
    raw_peril = row["peril"]
    peril = Peril(raw_peril.strip().lower())
    policy = Policy(
        policy_id=row["policy_id"],
        asset_id=row["asset_id"],
        peril=peril,
        inception_date=_iso_date(row["inception_date"]),
        expiry_date=_iso_date(row["expiry_date"]),
        annual_premium=_number(row["annual_premium"]),
        currency=Currency(row["currency"]),
    )
    return policy, raw_peril != peril.value


def _claim(row: Row) -> tuple[Claim, bool, bool]:
    """The Claim, and whether its loss date and reported date were day-first."""
    loss_date, loss_day_first = _date(row["loss_date"])
    reported_date, reported_day_first = _date(row["reported_date"])
    claim = Claim(
        claim_id=row["claim_id"],
        policy_id=row["policy_id"],
        loss_date=loss_date,
        reported_date=reported_date,
        paid_amount=_number(row["paid_amount"]),
        reserve_amount=_number(row["reserve_amount"]),
        currency=Currency(row["currency"]),
        status=ClaimStatus(row["status"]),
    )
    return claim, loss_day_first, reported_day_first


def _iso_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def _date(text: str) -> tuple[date, bool]:
    """ISO `YYYY-MM-DD` first, then day-first `DD-MM-YYYY`; the flag says the second was used."""
    try:
        return _iso_date(text), False
    except ValueError:
        pass
    try:
        return datetime.strptime(text.strip(), "%d-%m-%Y").date(), True
    except ValueError:
        raise ValueError(f"date {text!r} is neither YYYY-MM-DD nor DD-MM-YYYY") from None


def _number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"amount {text!r} is not a finite number")
    return value


# --- Starter assessment skeleton, kept only so api.py imports until U2 ----------------------


class ObservationSource(Protocol):
    def observations(self, asset_id: str) -> Observations | None: ...

    def all_observations(self) -> list[Observations]: ...


class CsvObservationSource:
    """CSV with `asset_id,value` rows; an empty cell is nodata."""

    def __init__(self, path: Path) -> None:
        self._provenance = Provenance(source=path.name)
        self._values: dict[str, list[float | None]] = {}
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                value = row["value"].strip()
                self._values.setdefault(row["asset_id"], []).append(float(value) if value else None)

    def observations(self, asset_id: str) -> Observations | None:
        values = self._values.get(asset_id)
        return None if values is None else Observations(asset_id, tuple(values), self._provenance)

    def all_observations(self) -> list[Observations]:
        return [
            Observations(asset_id, tuple(values), self._provenance)
            for asset_id, values in sorted(self._values.items())
        ]
