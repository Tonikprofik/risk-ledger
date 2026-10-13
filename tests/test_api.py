import json
from pathlib import Path

from fastapi.testclient import TestClient

from loss_experience.api import create_app
from loss_experience.domain import Observations, Provenance

SNAPSHOT = Path(__file__).parent.parent / "docs" / "openapi.json"


class InMemorySource:
    def __init__(self, **values: tuple[float | None, ...]) -> None:
        self._values = values

    def observations(self, asset_id: str) -> Observations | None:
        values = self._values.get(asset_id)
        return None if values is None else Observations(asset_id, values, Provenance("memory"))

    def all_observations(self) -> list[Observations]:
        return []


app = create_app(InMemorySource(F1=(0.6, 0.8), F2=(None, None, 0.4)))
client = TestClient(app)


def test_known_asset_with_data_is_ok_with_value() -> None:
    response = client.get("/v1/assets/F1/assessment")

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": "F1",
        "status": "ok",
        "value": 0.7,
        "coverage_fraction": 1.0,
        "provenance": {"source": "memory"},
    }


def test_mostly_nodata_is_200_with_status_and_no_value() -> None:
    body = client.get("/v1/assets/F2/assessment").json()

    assert (body["status"], body["value"]) == ("insufficient_data", None)


def test_unknown_asset_is_404() -> None:
    assert client.get("/v1/assets/F9/assessment").status_code == 404


def test_openapi_matches_published_contract() -> None:
    """Fails on any contract change. If the change is intended and additive, regenerate with
    `loss-experience openapi > docs/openapi.json` and say so in the commit."""
    assert app.openapi() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
