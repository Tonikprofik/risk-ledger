from dataclasses import replace
from datetime import date

import pytest

from risk_ledger.domain import (
    Claim,
    ClaimStatus,
    Currency,
    FxTable,
    MissingFxRate,
    incurred_loss_dkk,
)

FX = FxTable({(2023, 9, Currency.DKK): 1.0, (2023, 9, Currency.EUR): 7.47})


def claim(
    status: ClaimStatus, *, paid: float, reserve: float, currency: Currency = Currency.DKK
) -> Claim:
    return Claim(
        "CLM-1", "POL-1", date(2023, 9, 2), date(2023, 9, 10), paid, reserve, currency, status
    )


def test_settled_costs_what_was_paid_and_ignores_a_reserve() -> None:
    assert incurred_loss_dkk(claim(ClaimStatus.SETTLED, paid=1000.0, reserve=400.0), FX) == 1000.0


def test_open_costs_paid_plus_reserve() -> None:
    assert incurred_loss_dkk(claim(ClaimStatus.OPEN, paid=1000.0, reserve=400.0), FX) == 1400.0


def test_withdrawn_costs_nothing_even_when_something_was_paid() -> None:
    assert incurred_loss_dkk(claim(ClaimStatus.WITHDRAWN, paid=700.0, reserve=100.0), FX) == 0.0


def test_declined_costs_nothing() -> None:
    assert incurred_loss_dkk(claim(ClaimStatus.DECLINED, paid=0.0, reserve=250.0), FX) == 0.0


def test_eur_claim_converts_at_the_eur_rate_of_its_loss_month() -> None:
    open_eur = claim(ClaimStatus.OPEN, paid=100.0, reserve=50.0, currency=Currency.EUR)

    assert round(incurred_loss_dkk(open_eur, FX), 2) == 1120.5


def test_missing_fx_month_raises_instead_of_defaulting() -> None:
    october = replace(
        claim(ClaimStatus.SETTLED, paid=10.0, reserve=0.0), loss_date=date(2023, 10, 1)
    )

    with pytest.raises(MissingFxRate, match="no DKK rate for 2023-10"):
        incurred_loss_dkk(october, FX)
