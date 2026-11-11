"""HTTP shell over the domain. Routes translate; they hold no rules.

The response models are the public contract (docs/openapi.json). They are separate from
the domain dataclasses so internal renames cannot break clients; changes are additive.
Rounding happens here and only here: DKK to 2 decimals, the loss ratio to 4.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from loss_experience.domain import (
    Book,
    ExclusionReason,
    ExclusionSummary,
    FlagCount,
    FlagKind,
    LossFigures,
    Peril,
    PerilLossExperience,
    PortfolioLossExperience,
    RepairCount,
    RepairKind,
    exclusion_summaries,
    flag_counts,
    loss_experience,
    rank_portfolios,
    repair_counts,
)
from loss_experience.sources import default_data, load_book

DKK_DECIMALS = 2
RATIO_DECIMALS = 4


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


class LossFiguresOut(BaseModel):
    """The six figures of the brief; DKK rounded to 2 decimals, the ratio to 4."""

    policy_count: int = Field(ge=0)
    earned_premium_dkk: float = Field(description="Full annual premium at the inception month.")
    incurred_loss_dkk: float
    loss_ratio: float | None = Field(
        description="incurred_loss_dkk / earned_premium_dkk; null when earned premium is 0."
    )
    claim_count: int = Field(ge=0, description="Kept Claims of every status.")
    largest_claim_dkk: float | None = Field(description="null when claim_count is 0.")

    @staticmethod
    def _fields(figures: LossFigures) -> dict[str, object]:
        return {
            "policy_count": figures.policy_count,
            "earned_premium_dkk": round(figures.earned_premium_dkk, DKK_DECIMALS),
            "incurred_loss_dkk": round(figures.incurred_loss_dkk, DKK_DECIMALS),
            "loss_ratio": _rounded(figures.loss_ratio, RATIO_DECIMALS),
            "claim_count": figures.claim_count,
            "largest_claim_dkk": _rounded(figures.largest_claim_dkk, DKK_DECIMALS),
        }

    @classmethod
    def from_domain(cls, figures: LossFigures) -> "LossFiguresOut":
        return cls.model_validate(cls._fields(figures))


class PerilLossExperienceOut(LossFiguresOut):
    peril: Peril

    @classmethod
    def from_peril(cls, result: PerilLossExperience) -> "PerilLossExperienceOut":
        return cls.model_validate({"peril": result.peril, **cls._fields(result.figures)})


class ExclusionOut(BaseModel):
    """policy_not_found is book-wide (no Policy, so no Portfolio); the rest are this Portfolio's."""

    reason: ExclusionReason
    claim_count: int = Field(ge=0)
    amount_dkk: float = Field(description="Incurred loss the excluded Claims would have had.")

    @classmethod
    def from_domain(cls, summary: ExclusionSummary) -> "ExclusionOut":
        return cls(
            reason=summary.reason,
            claim_count=summary.claim_count,
            amount_dkk=round(summary.amount_dkk, DKK_DECIMALS),
        )


class PortfolioLossExperienceOut(BaseModel):
    portfolio_id: str
    total: LossFiguresOut = Field(description="The six figures over every Peril.")
    perils: list[PerilLossExperienceOut] = Field(description="Every Peril, always listed.")
    exclusions: list[ExclusionOut] = Field(
        description="Source Claims left out of every result, one row per reason."
    )

    @classmethod
    def from_domain(cls, result: PortfolioLossExperience) -> "PortfolioLossExperienceOut":
        return cls(
            portfolio_id=result.portfolio_id,
            total=LossFiguresOut.from_domain(result.total),
            perils=[PerilLossExperienceOut.from_peril(peril) for peril in result.perils],
            exclusions=[ExclusionOut.from_domain(summary) for summary in result.exclusions],
        )


class PortfolioRankingOut(BaseModel):
    portfolios: list[PortfolioLossExperienceOut] = Field(
        description="Every Portfolio, worst first: total loss_ratio descending, ties by "
        "incurred_loss_dkk descending, then portfolio_id; null ratios last, by portfolio_id."
    )


class LoadedCountsOut(BaseModel):
    assets: int = Field(ge=0)
    policies: int = Field(ge=0)
    claims: int = Field(ge=0, description="Claims kept; excluded Claims are in exclusions.")
    fx_rates: int = Field(ge=0, description="Monthly rates, one per month and currency.")


class RepairCountOut(BaseModel):
    kind: RepairKind
    count: int = Field(
        ge=0, description="Policies for peril_spellings, Claims for the day-first dates."
    )

    @classmethod
    def from_domain(cls, repair: RepairCount) -> "RepairCountOut":
        return cls(kind=repair.kind, count=repair.count)


class FlagCountOut(BaseModel):
    kind: FlagKind
    count: int = Field(ge=0, description="Policies for overlapping_terms, Claims otherwise.")
    amount_dkk: float | None = Field(
        description="The reserve still carried by settled_with_reserve Claims (not incurred "
        "loss); null for the kinds that record no DKK amount."
    )

    @classmethod
    def from_domain(cls, flag: FlagCount) -> "FlagCountOut":
        return cls(
            kind=flag.kind, count=flag.count, amount_dkk=_rounded(flag.amount_dkk, DKK_DECIMALS)
        )


class DataQualityOut(BaseModel):
    """The whole book: what was loaded, excluded, repaired at load, and kept but flagged."""

    loaded: LoadedCountsOut
    exclusions: list[ExclusionOut] = Field(
        description="Every excluded source Claim of the book, one row per reason."
    )
    repairs: list[RepairCountOut] = Field(description="Values changed at load, rows kept.")
    flags: list[FlagCountOut] = Field(description="Rows kept as they are and reported.")

    @classmethod
    def from_domain(cls, book: Book) -> "DataQualityOut":
        return cls(
            loaded=LoadedCountsOut(
                assets=len(book.assets),
                policies=len(book.policies),
                claims=len(book.claims),
                fx_rates=len(book.fx.rates_dkk_per_unit),
            ),
            exclusions=[
                ExclusionOut.from_domain(summary)
                for summary in exclusion_summaries(book.exclusions)
            ],
            repairs=[RepairCountOut.from_domain(r) for r in repair_counts(book.data_quality)],
            flags=[FlagCountOut.from_domain(f) for f in flag_counts(book.data_quality)],
        )


class Health(BaseModel):
    status: str
    data: str = Field(
        description="Where the Book was loaded from; `sample` means the committed 7-asset set"
    )


def create_app(book: Book, source: str = "memory") -> FastAPI:
    app = FastAPI(title="Loss experience", version="1.0.0")

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok", data=source)

    @app.get("/portfolios/loss-experience")
    def get_ranking() -> PortfolioRankingOut:
        return PortfolioRankingOut(
            portfolios=[
                PortfolioLossExperienceOut.from_domain(result) for result in rank_portfolios(book)
            ]
        )

    @app.get(
        "/portfolios/{portfolio_id}/loss-experience",
        responses={404: {"description": "No Asset belongs to this Portfolio"}},
    )
    def get_loss_experience(portfolio_id: str) -> PortfolioLossExperienceOut:
        result = loss_experience(book, portfolio_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Unknown portfolio {portfolio_id!r}")
        return PortfolioLossExperienceOut.from_domain(result)

    @app.get("/data-quality")
    def get_data_quality() -> DataQualityOut:
        return DataQualityOut.from_domain(book)

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn --factory loss_experience.api:app_from_env`.

    Reads LOSS_DATA; without it, `data` when it holds CSVs, else the committed `sample`.
    """
    env = os.environ.get("LOSS_DATA")
    data = Path(env) if env else default_data()
    logging.getLogger(__name__).warning("loading book from %s", data.as_posix())
    return create_app(load_book(data), source=data.as_posix())
