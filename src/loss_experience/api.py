"""HTTP shell over the domain. Routes translate; they hold no rules.

The response models are the public contract (docs/openapi.json). They are separate from
the domain dataclasses so internal renames cannot break clients. v1 changes are additive.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from loss_experience.domain import Assessment, Ok, Status, assess
from loss_experience.sources import CsvObservationSource, ObservationSource


class ProvenanceOut(BaseModel):
    source: str


class AssessmentOut(BaseModel):
    asset_id: str
    status: Status
    value: float | None = Field(description="Present if and only if status is ok.")
    coverage_fraction: float = Field(ge=0, le=1)
    provenance: ProvenanceOut

    @classmethod
    def from_domain(cls, assessment: Assessment) -> "AssessmentOut":
        outcome = assessment.outcome
        return cls(
            asset_id=assessment.asset_id,
            status=outcome.status,
            value=outcome.value if isinstance(outcome, Ok) else None,
            coverage_fraction=assessment.coverage_fraction,
            provenance=ProvenanceOut(source=assessment.provenance.source),
        )


class Health(BaseModel):
    status: str


def create_app(source: ObservationSource, *, min_coverage: float = 0.5) -> FastAPI:
    app = FastAPI(title="the company task", version="1.0.0")

    @app.get("/health")
    def health() -> Health:
        return Health(status="ok")

    @app.get(
        "/v1/assets/{asset_id}/assessment",
        responses={404: {"description": "Unknown asset"}},
    )
    def get_assessment(asset_id: str) -> AssessmentOut:
        observations = source.observations(asset_id)
        if observations is None:
            raise HTTPException(status_code=404, detail=f"Unknown asset {asset_id!r}")
        return AssessmentOut.from_domain(assess(observations, min_coverage=min_coverage))

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn --factory loss_experience.api:app_from_env`."""
    path = Path(os.environ.get("COMPANY_OBSERVATIONS", "data/sample/observations.csv"))
    return create_app(CsvObservationSource(path))
