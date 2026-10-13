"""HTTP shell over the domain. Routes translate; they hold no rules.

The response models are the public contract (docs/openapi.json). They are separate from
the domain dataclasses so internal renames cannot break clients; changes are additive.
Rounding happens here and only here: DKK to 2 decimals, the loss ratio to 4.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from loss_experience.domain import (
    Book,
    ExclusionReason,
    ExclusionSummary,
    Peril,
    PerilLossExperience,
    PortfolioLossExperience,
    loss_experience,
)
from loss_experience.sources import load_book

DKK_DECIMALS = 2
RATIO_DECIMALS = 4


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


class PerilLossExperienceOut(BaseModel):
    peril: Peril
    policy_count: int = Field(ge=0)
    earned_premium_dkk: float = Field(description="Full annual premium at the inception month.")
    incurred_loss_dkk: float
    loss_ratio: float | None = Field(
        description="incurred_loss_dkk / earned_premium_dkk; null when earned premium is 0."
    )
    claim_count: int = Field(ge=0, description="Kept Claims of every status.")
    largest_claim_dkk: float | None = Field(description="null when claim_count is 0.")

    @classmethod
    def from_domain(cls, result: PerilLossExperience) -> "PerilLossExperienceOut":
        return cls(
            peril=result.peril,
            policy_count=result.policy_count,
            earned_premium_dkk=round(result.earned_premium_dkk, DKK_DECIMALS),
            incurred_loss_dkk=round(result.incurred_loss_dkk, DKK_DECIMALS),
            loss_ratio=_rounded(result.loss_ratio, RATIO_DECIMALS),
            claim_count=result.claim_count,
            largest_claim_dkk=_rounded(result.largest_claim_dkk, DKK_DECIMALS),
        )


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
    perils: list[PerilLossExperienceOut] = Field(description="Every Peril, always listed.")
    exclusions: list[ExclusionOut] = Field(
        description="Source Claims left out of every result, one row per reason."
    )

    @classmethod
    def from_domain(cls, result: PortfolioLossExperience) -> "PortfolioLossExperienceOut":
        return cls(
            portfolio_id=result.portfolio_id,
            perils=[PerilLossExperienceOut.from_domain(peril) for peril in result.perils],
            exclusions=[ExclusionOut.from_domain(summary) for summary in result.exclusions],
        )


class Health(BaseModel):
    status: str


def create_app(book: Book) -> FastAPI:
    app = FastAPI(title="the company loss experience", version="1.0.0")

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok")

    # FastAPI matches in declaration order: declare static /portfolios/... paths (U4) up here.
    @app.get(
        "/portfolios/{portfolio_id}/loss-experience",
        responses={404: {"description": "No Asset belongs to this Portfolio"}},
    )
    def get_loss_experience(portfolio_id: str) -> PortfolioLossExperienceOut:
        result = loss_experience(book, portfolio_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Unknown portfolio {portfolio_id!r}")
        return PortfolioLossExperienceOut.from_domain(result)

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn --factory loss_experience.api:app_from_env`; reads LOSS_DATA."""
    return create_app(load_book(Path(os.environ.get("LOSS_DATA", "data"))))
