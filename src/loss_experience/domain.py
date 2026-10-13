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
    """Only what a result uses. assets.csv also has region, type, construction year and sum
    insured; the filters that would read them were cut (D17), so they are not parsed."""

    asset_id: str
    portfolio_id: str


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


class RepairKind(StrEnum):
    """What load changed into its canonical form; a Repair never removes a row."""

    PERIL_SPELLINGS = "peril_spellings"
    DAY_FIRST_LOSS_DATES = "day_first_loss_dates"
    DAY_FIRST_REPORTED_DATES = "day_first_reported_dates"


class FlagKind(StrEnum):
    """What load kept as it is but reports, because it does not change a result (D14)."""

    LOSS_BEFORE_INCEPTION = "loss_before_inception"
    SETTLED_WITH_RESERVE = "settled_with_reserve"
    MIXED_CURRENCY = "mixed_currency"
    OVERLAPPING_TERMS = "overlapping_terms"


@dataclass(frozen=True)
class RepairCount:
    kind: RepairKind
    count: int


@dataclass(frozen=True)
class FlagCount:
    """`amount_dkk` is None where the count has no DKK amount recorded."""

    kind: FlagKind
    count: int
    amount_dkk: float | None


def repair_counts(quality: DataQuality) -> tuple[RepairCount, ...]:
    """One count per RepairKind in enum order, including kinds with no rows."""
    return tuple(RepairCount(kind, _repaired(quality, kind)) for kind in RepairKind)


def _repaired(quality: DataQuality, kind: RepairKind) -> int:
    match kind:
        case RepairKind.PERIL_SPELLINGS:
            return quality.peril_spellings_repaired
        case RepairKind.DAY_FIRST_LOSS_DATES:
            return quality.day_first_loss_dates_repaired
        case RepairKind.DAY_FIRST_REPORTED_DATES:
            return quality.day_first_reported_dates_repaired
        case _:
            assert_never(kind)


def flag_counts(quality: DataQuality) -> tuple[FlagCount, ...]:
    """One count per FlagKind in enum order, including kinds with no rows."""
    return tuple(_flagged(quality, kind) for kind in FlagKind)


def _flagged(quality: DataQuality, kind: FlagKind) -> FlagCount:
    match kind:
        case FlagKind.LOSS_BEFORE_INCEPTION:
            return FlagCount(kind, quality.loss_before_inception_flagged, None)
        case FlagKind.SETTLED_WITH_RESERVE:
            return FlagCount(
                kind, quality.settled_with_reserve_flagged, quality.settled_reserve_dkk
            )
        case FlagKind.MIXED_CURRENCY:
            return FlagCount(kind, quality.mixed_currency_claims, None)
        case FlagKind.OVERLAPPING_TERMS:
            return FlagCount(kind, quality.overlapping_terms, None)
        case _:
            assert_never(kind)


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


def earned_premium_dkk(policy: Policy, fx: FxTable) -> float:
    """The full annual premium, no pro-rata, in DKK at the inception month, converted from the
    Policy's own currency."""
    return to_dkk(policy.annual_premium, policy.currency, policy.inception_date, fx)


@dataclass(frozen=True)
class LossFigures:
    """The six figures of the brief over a set of Policies and their Claims. `loss_ratio` is
    None iff `earned_premium_dkk` is 0; `largest_claim_dkk` is None iff `claim_count` is 0."""

    policy_count: int
    earned_premium_dkk: float
    incurred_loss_dkk: float
    loss_ratio: float | None
    claim_count: int
    largest_claim_dkk: float | None


@dataclass(frozen=True)
class PerilLossExperience:
    """The figures of one Peril of one Portfolio."""

    peril: Peril
    figures: LossFigures


@dataclass(frozen=True)
class ExclusionSummary:
    """How many source Claims one ExclusionReason left out, and their Incurred loss in DKK."""

    reason: ExclusionReason
    claim_count: int
    amount_dkk: float


@dataclass(frozen=True)
class PortfolioLossExperience:
    """The total over every Peril, every Peril in enum order, and the Exclusions that affect it:
    `negative_paid_amount` of its own Policies, and every `policy_not_found`, which names no
    Policy and so no Portfolio."""

    portfolio_id: str
    total: LossFigures
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
    policy_ids = set(peril_by_policy_id)
    return PortfolioLossExperience(
        portfolio_id=portfolio_id,
        total=_figures(
            [dkk for peril in Peril for dkk in premiums_dkk[peril]],
            [dkk for peril in Peril for dkk in losses_dkk[peril]],
        ),
        perils=tuple(
            PerilLossExperience(peril, _figures(premiums_dkk[peril], losses_dkk[peril]))
            for peril in Peril
        ),
        exclusions=exclusion_summaries(
            [e for e in book.exclusions if _shown_in_portfolio(e, policy_ids)]
        ),
    )


def rank_portfolios(book: Book) -> tuple[PortfolioLossExperience, ...]:
    """Every Portfolio named by an Asset, worst first: total `loss_ratio` descending, ties by
    `incurred_loss_dkk` descending, then `portfolio_id`; Portfolios without a ratio last, by
    `portfolio_id`."""
    results = (loss_experience(book, p) for p in {asset.portfolio_id for asset in book.assets})
    return tuple(sorted((r for r in results if r is not None), key=_worst_first))


def _worst_first(result: PortfolioLossExperience) -> tuple[bool, float, float, str]:
    ratio = result.total.loss_ratio
    if ratio is None:
        return (True, 0.0, 0.0, result.portfolio_id)
    return (False, -ratio, -result.total.incurred_loss_dkk, result.portfolio_id)


def _figures(premiums_dkk: Sequence[float], losses_dkk: Sequence[float]) -> LossFigures:
    """One entry per Earned premium and one per Incurred loss, in DKK; `fsum` for exact sums."""
    earned_dkk = math.fsum(premiums_dkk)
    incurred_dkk = math.fsum(losses_dkk)
    return LossFigures(
        policy_count=len(premiums_dkk),
        earned_premium_dkk=earned_dkk,
        incurred_loss_dkk=incurred_dkk,
        loss_ratio=None if earned_dkk == 0 else incurred_dkk / earned_dkk,
        claim_count=len(losses_dkk),
        largest_claim_dkk=max(losses_dkk, default=None),
    )
