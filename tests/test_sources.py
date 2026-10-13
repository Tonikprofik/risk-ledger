import shutil
from datetime import date
from pathlib import Path

import pytest

from loss_experience.domain import (
    Claim,
    DataQuality,
    ExclusionReason,
    Peril,
    incurred_loss_dkk,
)
from loss_experience.sources import load_book

SAMPLE = Path(__file__).parent.parent / "data" / "sample"
BOOK = load_book(SAMPLE)


def claim(claim_id: str) -> Claim:
    return next(claim for claim in BOOK.claims if claim.claim_id == claim_id)


def test_orphan_and_negative_paid_claims_are_excluded_with_their_dkk_amount() -> None:
    # The orphan is 1,200 EUR lost in 2023-06 (EUR 7.46); the negative one is -2,500 DKK.
    assert [(e.reason, e.claim_id, round(e.amount_dkk, 2)) for e in BOOK.exclusions] == [
        (ExclusionReason.POLICY_NOT_FOUND, "CLM-900010", 8952.0),
        (ExclusionReason.NEGATIVE_PAID_AMOUNT, "CLM-900011", -2500.0),
    ]


def test_excluded_claims_are_not_claims_of_the_book() -> None:
    claim_ids = {claim.claim_id for claim in BOOK.claims}

    assert len(BOOK.claims) == 10
    assert {"CLM-900010", "CLM-900011"}.isdisjoint(claim_ids)


def test_repairs_and_flags_are_counted() -> None:
    assert BOOK.data_quality == DataQuality(
        peril_spellings_repaired=3,
        day_first_loss_dates_repaired=2,
        day_first_reported_dates_repaired=2,
        loss_before_inception_flagged=1,
        settled_with_reserve_flagged=1,
        settled_reserve_dkk=1500.0,
        mixed_currency_claims=1,
        overlapping_terms=1,
    )


def test_padded_and_mixed_case_perils_are_normalised() -> None:
    peril_of = {policy.policy_id: policy.peril for policy in BOOK.policies}

    assert [peril_of["POL-500002"], peril_of["POL-500003"], peril_of["POL-500007"]] == [
        Peril.FLOOD,
        Peril.HAIL,
        Peril.STORM,
    ]


def test_eur_claim_on_dkk_policy_converts_at_the_eur_rate_of_its_own_loss_month() -> None:
    # 1,000 EUR lost 2023-09 (EUR 7.47); its policy is DKK and incepted 2023-03 (EUR 7.45).
    assert round(incurred_loss_dkk(claim("CLM-900004"), BOOK.fx), 2) == 7470.0


def test_day_first_dates_parse_as_day_month_year() -> None:
    assert claim("CLM-900002").loss_date == date(2023, 6, 15)
    assert claim("CLM-900003").reported_date == date(2023, 7, 5)


def test_missing_column_fails_naming_the_file(tmp_path: Path) -> None:
    data = shutil.copytree(SAMPLE, tmp_path / "data")
    (data / "claims.csv").write_text(
        "claim_id,policy_id,loss_date,reported_date,paid_amount,reserve_amount,currency\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"claims\.csv lacks columns \['status'\]"):
        load_book(data)


def test_loading_twice_gives_an_equal_book() -> None:
    assert load_book(SAMPLE) == BOOK


CLAIM_HEADER = (
    "claim_id,policy_id,loss_date,reported_date,paid_amount,reserve_amount,currency,status"
)
POLICY_HEADER = "policy_id,asset_id,peril,inception_date,expiry_date,annual_premium,currency"


@pytest.mark.parametrize(
    "row",
    [
        "CLM-1,POL-500001,13-13-2024,2023-09-30,100.00,0.00,DKK,settled",
        "CLM-1,POL-500001,2023-09-12,2023-09-30,,0.00,DKK,settled",
        "CLM-1,POL-500001,2023-09-12,2023-09-30,100.00,0.00,DKK,paid",
    ],
    ids=["impossible-date", "blank-paid", "unknown-status"],
)
def test_malformed_claim_value_fails_naming_file_and_line(tmp_path: Path, row: str) -> None:
    data = shutil.copytree(SAMPLE, tmp_path / "data")
    (data / "claims.csv").write_text(f"{CLAIM_HEADER}\n{row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"claims\.csv:\d+:"):
        load_book(data)


@pytest.mark.parametrize(
    ("file", "content", "message"),
    [
        (
            "policies.csv",
            f"{POLICY_HEADER}\nPOL-1,AST-999999,fire,2023-06-01,2024-05-31,100.00,DKK\n",
            r"policies\.csv: 1 policies name an asset_id not in assets\.csv, first \['POL-1'\]",
        ),
        (
            "policies.csv",
            f"{POLICY_HEADER}\nPOL-1,AST-100000,fire,2023-10-01,2024-09-30,100.00,DKK\n",
            r"policies\.csv POL-1: no DKK rate for 2023-10",
        ),
        (
            "claims.csv",
            f"{CLAIM_HEADER}\nCLM-1,POL-500001,2023-10-02,2023-10-05,100.00,0.00,EUR,settled\n",
            r"claims\.csv CLM-1: no EUR rate for 2023-10",
        ),
    ],
    ids=["unknown-asset", "premium-fx-gap", "claim-fx-gap"],
)
def test_broken_reference_fails_the_load_naming_the_row(
    tmp_path: Path, file: str, content: str, message: str
) -> None:
    data = shutil.copytree(SAMPLE, tmp_path / "data")
    (data / file).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_book(data)
