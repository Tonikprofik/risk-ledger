"""Domain types and pure calculations for loss experience. No I/O, no framework imports.

Terms follow docs/GLOSSARY.md. A `_dkk` field is in DKK; `paid_amount`, `reserve_amount` and
`annual_premium` are in the `currency` their own row states and are converted only through `to_dkk`.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import assert_never


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
    """A source Claim left out of every result, with the `policy_id` it names (which may not
    exist) and the Incurred loss it would have had."""

    reason: ExclusionReason
    claim_id: str
    policy_id: str
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


def underwriting_year(policy: Policy) -> int:
    """The calendar year in which the Policy incepted."""
    return policy.inception_date.year


def earned_premium_dkk(policy: Policy, fx: FxTable) -> float:
    """The full annual premium, no pro-rata, in DKK at the inception month, converted from the
    Policy's own currency."""
    return to_dkk(policy.annual_premium, policy.currency, policy.inception_date, fx)


@dataclass(frozen=True)
class PerilLossExperience:
    """One Peril of one Portfolio. `loss_ratio` is None iff `earned_premium_dkk` is 0;
    `largest_claim_dkk` is None iff `claim_count` is 0."""

    peril: Peril
    policy_count: int
    earned_premium_dkk: float
    incurred_loss_dkk: float
    loss_ratio: float | None
    claim_count: int
    largest_claim_dkk: float | None


@dataclass(frozen=True)
class ExclusionSummary:
    """How many source Claims one ExclusionReason left out, and their Incurred loss in DKK."""

    reason: ExclusionReason
    claim_count: int
    amount_dkk: float


@dataclass(frozen=True)
class PortfolioLossExperience:
    """Every Peril in enum order, and the Exclusions that affect it: `negative_paid_amount` of
    its own Policies, and every `policy_not_found`, which names no Policy and so no Portfolio."""

    portfolio_id: str
    perils: tuple[PerilLossExperience, ...]
    exclusions: tuple[ExclusionSummary, ...]


def exclusion_summaries(exclusions: Sequence[Exclusion]) -> tuple[ExclusionSummary, ...]:
    """One summary per ExclusionReason in enum order, including reasons with no Claims."""
    return tuple(
        ExclusionSummary(
            reason=reason,
            claim_count=sum(exclusion.reason is reason for exclusion in exclusions),
            amount_dkk=math.fsum(
                exclusion.amount_dkk for exclusion in exclusions if exclusion.reason is reason
            ),
        )
        for reason in ExclusionReason
    )


def _shown_in_portfolio(exclusion: Exclusion, policy_ids: set[str]) -> bool:
    match exclusion.reason:
        case ExclusionReason.POLICY_NOT_FOUND:
            return True  # it names no Policy, so no Portfolio: every result shows it
        case ExclusionReason.NEGATIVE_PAID_AMOUNT:
            return exclusion.policy_id in policy_ids
        case _:
            assert_never(exclusion.reason)


def loss_experience(book: Book, portfolio_id: str) -> PortfolioLossExperience | None:
    """The Portfolio's Loss experience, or None when no Asset belongs to it. A Claim counts in
    the Portfolio and Peril of the Policy its `policy_id` names, whatever its status."""
    asset_ids = {asset.asset_id for asset in book.assets if asset.portfolio_id == portfolio_id}
    if not asset_ids:
        return None
    premiums_dkk: dict[Peril, list[float]] = {peril: [] for peril in Peril}
    peril_by_policy_id: dict[str, Peril] = {}
    for policy in book.policies:
        if policy.asset_id in asset_ids:
            premiums_dkk[policy.peril].append(earned_premium_dkk(policy, book.fx))
            peril_by_policy_id[policy.policy_id] = policy.peril
    losses_dkk: dict[Peril, list[float]] = {peril: [] for peril in Peril}
    for claim in book.claims:
        peril = peril_by_policy_id.get(claim.policy_id)
        if peril is not None:
            losses_dkk[peril].append(incurred_loss_dkk(claim, book.fx))
    return PortfolioLossExperience(
        portfolio_id=portfolio_id,
        perils=tuple(
            _peril_loss_experience(peril, premiums_dkk[peril], losses_dkk[peril]) for peril in Peril
        ),
        exclusions=exclusion_summaries(
            [e for e in book.exclusions if _shown_in_portfolio(e, set(peril_by_policy_id))]
        ),
    )


def _peril_loss_experience(
    peril: Peril, premiums_dkk: Sequence[float], losses_dkk: Sequence[float]
) -> PerilLossExperience:
    earned_dkk = math.fsum(premiums_dkk)
    incurred_dkk = math.fsum(losses_dkk)
    return PerilLossExperience(
        peril=peril,
        policy_count=len(premiums_dkk),
        earned_premium_dkk=earned_dkk,
        incurred_loss_dkk=incurred_dkk,
        loss_ratio=None if earned_dkk == 0 else incurred_dkk / earned_dkk,
        claim_count=len(losses_dkk),
        largest_claim_dkk=max(losses_dkk, default=None),
    )
