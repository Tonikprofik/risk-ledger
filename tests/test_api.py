import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from loss_experience.api import create_app
from loss_experience.domain import Claim, ClaimStatus, Currency, Peril, Policy
from loss_experience.sources import load_book

ROOT = Path(__file__).parent.parent
SNAPSHOT = ROOT / "docs" / "openapi.json"
SAMPLE_BOOK = load_book(ROOT / "data" / "sample")

app = create_app(SAMPLE_BOOK)
client = TestClient(app)


def by_peril(body: dict[str, list[dict[str, object]]]) -> dict[str, dict[str, object]]:
    return {str(item["peril"]): item for item in body["perils"]}


def test_known_portfolio_lists_every_peril_with_its_figures_and_exclusions() -> None:
    # PF-01 holds POL-500001 and -500005 (storm, 10,000 + 10,500 DKK), POL-500002 (flood,
    # 12,000 DKK) and POL-500006 (subsidence, 3,000 DKK). Storm: settled 10,000 and 6,000 (its
    # reserve ignored). Flood: settled 8,000, open 2,000 + 3,000, withdrawn 0. Subsidence's only
    # claim is the negative-paid exclusion; the orphan (1,200 EUR at 7.46) shows in every result.
    # Total: 35,500 premium, 29,000 incurred, 29,000 / 35,500 = 0.8169.
    response = client.get("/portfolios/PF-01/loss-experience")

    assert response.status_code == 200
    assert response.json() == {
        "portfolio_id": "PF-01",
        "total": {
            "policy_count": 4,
            "earned_premium_dkk": 35500.0,
            "incurred_loss_dkk": 29000.0,
            "loss_ratio": 0.8169,
            "claim_count": 5,
            "largest_claim_dkk": 10000.0,
        },
        "perils": [
            {
                "peril": "fire",
                "policy_count": 0,
                "earned_premium_dkk": 0.0,
                "incurred_loss_dkk": 0.0,
                "loss_ratio": None,
                "claim_count": 0,
                "largest_claim_dkk": None,
            },
            {
                "peril": "flood",
                "policy_count": 1,
                "earned_premium_dkk": 12000.0,
                "incurred_loss_dkk": 13000.0,
                "loss_ratio": 1.0833,
                "claim_count": 3,
                "largest_claim_dkk": 8000.0,
            },
            {
                "peril": "hail",
                "policy_count": 0,
                "earned_premium_dkk": 0.0,
                "incurred_loss_dkk": 0.0,
                "loss_ratio": None,
                "claim_count": 0,
                "largest_claim_dkk": None,
            },
            {
                "peril": "storm",
                "policy_count": 2,
                "earned_premium_dkk": 20500.0,
                "incurred_loss_dkk": 16000.0,
                "loss_ratio": 0.7805,
                "claim_count": 2,
                "largest_claim_dkk": 10000.0,
            },
            {
                "peril": "subsidence",
                "policy_count": 1,
                "earned_premium_dkk": 3000.0,
                "incurred_loss_dkk": 0.0,
                "loss_ratio": 0.0,
                "claim_count": 0,
                "largest_claim_dkk": None,
            },
        ],
        "exclusions": [
            {"reason": "policy_not_found", "claim_count": 1, "amount_dkk": 8952.0},
            {"reason": "negative_paid_amount", "claim_count": 1, "amount_dkk": -2500.0},
        ],
    }


def test_unknown_portfolio_is_404_naming_it() -> None:
    response = client.get("/portfolios/PF-99/loss-experience")

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "Unknown portfolio 'PF-99'"},
    )


def test_ranking_lists_every_portfolio_worst_total_ratio_first() -> None:
    # PF-01: 29,000 / 35,500 = 0.8169. PF-02: 18,927.50 / 39,555.50 = 0.4785 (fire 7,470,
    # hail 7,457.50, storm 4,000 over 5,000 + 30,555.50 + 4,000).
    body = client.get("/portfolios/loss-experience").json()

    assert [(item["portfolio_id"], item["total"]["loss_ratio"]) for item in body["portfolios"]] == [
        ("PF-01", 0.8169),
        ("PF-02", 0.4785),
        ("PF-03", None),
    ]


def test_ranking_puts_a_portfolio_without_premium_last_with_a_null_ratio() -> None:
    # PF-03 has an Asset but no Policy: an observed zero premium, so no ratio, not ratio 0.
    last = client.get("/portfolios/loss-experience").json()["portfolios"][-1]

    assert (last["portfolio_id"], last["total"]) == (
        "PF-03",
        {
            "policy_count": 0,
            "earned_premium_dkk": 0.0,
            "incurred_loss_dkk": 0.0,
            "loss_ratio": None,
            "claim_count": 0,
            "largest_claim_dkk": None,
        },
    )


def test_eur_claim_on_dkk_policy_converts_at_the_eur_rate_of_its_loss_month() -> None:
    # POL-500004 is a 5,000 DKK fire policy; CLM-900004 is 1,000 EUR lost in 2023-09 (7.47),
    # CLM-900008 is declined and counts with 0.
    fire = by_peril(client.get("/portfolios/PF-02/loss-experience").json())["fire"]

    assert (fire["incurred_loss_dkk"], fire["loss_ratio"], fire["largest_claim_dkk"]) == (
        7470.0,
        1.494,
        7470.0,
    )


def test_negative_paid_exclusion_shows_only_in_its_own_portfolio() -> None:
    body = client.get("/portfolios/PF-02/loss-experience").json()

    assert body["exclusions"] == [
        {"reason": "policy_not_found", "claim_count": 1, "amount_dkk": 8952.0},
        {"reason": "negative_paid_amount", "claim_count": 0, "amount_dkk": 0.0},
    ]


def test_zero_earned_premium_gives_a_null_ratio_not_zero() -> None:
    free = Policy(
        "POL-1", "AST-100006", Peril.FIRE, date(2023, 6, 1), date(2024, 5, 31), 0.0, Currency.DKK
    )
    paid = Claim(
        "CLM-1",
        "POL-1",
        date(2023, 9, 2),
        date(2023, 9, 10),
        250.0,
        0.0,
        Currency.DKK,
        ClaimStatus.SETTLED,
    )
    book = replace(SAMPLE_BOOK, policies=(free,), claims=(paid,))

    body = TestClient(create_app(book)).get("/portfolios/PF-03/loss-experience").json()

    assert by_peril(body)["fire"] == {
        "peril": "fire",
        "policy_count": 1,
        "earned_premium_dkk": 0.0,
        "incurred_loss_dkk": 250.0,
        "loss_ratio": None,
        "claim_count": 1,
        "largest_claim_dkk": 250.0,
    }


def test_openapi_matches_published_contract() -> None:
    """Fails on any contract change. If the change is intended and additive, regenerate with
    `loss-experience openapi > docs/openapi.json` and say so in the commit."""
    assert app.openapi() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
