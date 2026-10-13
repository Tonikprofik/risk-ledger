"""Independent check of the loss experience, standard library only (D18).

Recomputes Earned premium, Incurred loss and the two Exclusions from the four CSVs under
the D14 policy, without importing the service, and optionally compares one Portfolio
with the API's JSON; `--ranking` also recounts every Portfolio's total and compares the
order and figures of GET /portfolios/loss-experience (D16):

    python scripts/check_loss_experience.py --data data [--portfolio PF-01]
        [--api http://localhost:8000] [--ranking]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

FIELDS = (
    "policy_count",
    "earned_premium_dkk",
    "incurred_loss_dkk",
    "loss_ratio",
    "claim_count",
    "largest_claim_dkk",
)
COUNT_FIELDS = frozenset({"policy_count", "claim_count"})
DKK_TOLERANCE = 0.5
RATIO_TOLERANCE = 0.0005
CLAIM_STATUSES = frozenset({"settled", "open", "withdrawn", "declined"})
EXCLUSION_REASONS = ("policy_not_found", "negative_paid_amount")

Rates = dict[tuple[str, str], float]
Value = int | float | None


@dataclass
class Tally:
    """A count of rows and their summed DKK amount."""

    count: int = 0
    amount_dkk: float = 0.0

    def add(self, amount_dkk: float) -> None:
        self.count += 1
        self.amount_dkk += amount_dkk


@dataclass
class Totals:
    """The six loss-experience figures for one Peril of one Portfolio, or the book."""

    policy_count: int = 0
    earned_premium_dkk: float = 0.0
    incurred_loss_dkk: float = 0.0
    claim_count: int = 0
    largest_claim_dkk: float | None = None

    def add_policy(self, premium_dkk: float) -> None:
        self.policy_count += 1
        self.earned_premium_dkk += premium_dkk

    def add_claim(self, incurred_dkk: float) -> None:
        self.claim_count += 1
        self.incurred_loss_dkk += incurred_dkk
        if self.largest_claim_dkk is None or incurred_dkk > self.largest_claim_dkk:
            self.largest_claim_dkk = incurred_dkk

    @property
    def loss_ratio(self) -> float | None:
        if self.earned_premium_dkk == 0:
            return None
        return self.incurred_loss_dkk / self.earned_premium_dkk

    def as_dict(self) -> dict[str, Value]:
        return {
            "policy_count": self.policy_count,
            "earned_premium_dkk": self.earned_premium_dkk,
            "incurred_loss_dkk": self.incurred_loss_dkk,
            "loss_ratio": self.loss_ratio,
            "claim_count": self.claim_count,
            "largest_claim_dkk": self.largest_claim_dkk,
        }


@dataclass
class Result:
    book: Totals
    cells: dict[tuple[str, str], Totals]
    perils: list[str]
    portfolios: set[str]
    portfolio_totals: dict[str, Totals]
    exclusions: dict[str, Tally]
    eur_claims: Tally

    def portfolio(self, portfolio_id: str) -> dict[str, Totals]:
        return {p: self.cells.get((portfolio_id, p), Totals()) for p in self.perils}

    def ranking(self) -> list[tuple[str, Totals]]:
        """Every Portfolio, worst total ratio first, ties by incurred loss, then id (D16)."""
        rows = [(p, self.portfolio_totals.get(p, Totals())) for p in self.portfolios]
        return sorted(rows, key=worst_first)


def worst_first(row: tuple[str, Totals]) -> tuple[bool, float, float, str]:
    portfolio_id, totals = row
    ratio = totals.loss_ratio
    if ratio is None:
        return (True, 0.0, 0.0, portfolio_id)
    return (False, -ratio, -totals.incurred_loss_dkk, portfolio_id)


def parse_date(text: str) -> date:
    """ISO first, then day-first DD-MM-YYYY (D14)."""
    value = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"unparseable date: {text!r}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_dkk(rates: Rates, amount: float, currency: str, on: date) -> float:
    key = (f"{on:%Y-%m}", currency.strip().upper())
    if key not in rates:
        raise SystemExit(f"no FX rate for {key[1]} in {key[0]}")
    return amount * rates[key]


def incurred_amount(status: str, paid: float, reserve: float) -> float:
    """settled = paid, open = paid + reserve, withdrawn and declined = 0."""
    if status == "settled":
        return paid
    if status == "open":
        return paid + reserve
    return 0.0


def compute(data_dir: Path) -> Result:
    portfolio_of_asset = {
        r["asset_id"].strip(): r["portfolio_id"].strip() for r in read_rows(data_dir / "assets.csv")
    }
    rates: Rates = {
        (r["month"].strip(), r["currency"].strip().upper()): float(r["rate_dkk_per_unit"])
        for r in read_rows(data_dir / "fx_rates.csv")
    }

    book = Totals()
    cells: dict[tuple[str, str], Totals] = defaultdict(Totals)
    portfolio_totals: dict[str, Totals] = defaultdict(Totals)
    cell_of_policy: dict[str, tuple[str, str]] = {}
    for row in read_rows(data_dir / "policies.csv"):
        policy_id = row["policy_id"].strip()
        if policy_id in cell_of_policy:
            raise SystemExit(f"duplicate policy_id {policy_id}")
        asset_id = row["asset_id"].strip()
        if asset_id not in portfolio_of_asset:
            raise SystemExit(f"policy {policy_id} names unknown asset {asset_id}")
        cell = (portfolio_of_asset[asset_id], row["peril"].strip().lower())
        premium_dkk = to_dkk(
            rates,
            float(row["annual_premium"]),
            row["currency"],
            parse_date(row["inception_date"]),
        )
        cell_of_policy[policy_id] = cell
        cells[cell].add_policy(premium_dkk)
        portfolio_totals[cell[0]].add_policy(premium_dkk)
        book.add_policy(premium_dkk)

    exclusions = {reason: Tally() for reason in EXCLUSION_REASONS}
    eur_claims = Tally()
    for row in read_rows(data_dir / "claims.csv"):
        status = row["status"].strip().lower()
        if status not in CLAIM_STATUSES:
            raise SystemExit(f"claim {row['claim_id']} has unknown status {status!r}")
        paid = float(row["paid_amount"])
        currency = row["currency"].strip().upper()
        # The claim's own currency at its loss month, never its policy's currency.
        incurred_dkk = to_dkk(
            rates,
            incurred_amount(status, paid, float(row["reserve_amount"])),
            currency,
            parse_date(row["loss_date"]),
        )
        cell = cell_of_policy.get(row["policy_id"].strip())
        if cell is None:
            exclusions["policy_not_found"].add(incurred_dkk)
            continue
        if paid < 0:
            exclusions["negative_paid_amount"].add(incurred_dkk)
            continue
        cells[cell].add_claim(incurred_dkk)
        portfolio_totals[cell[0]].add_claim(incurred_dkk)
        book.add_claim(incurred_dkk)
        if currency == "EUR":
            eur_claims.add(incurred_dkk)

    return Result(
        book=book,
        cells=dict(cells),
        perils=sorted({peril for _, peril in cells}),
        portfolios=set(portfolio_of_asset.values()),
        portfolio_totals=dict(portfolio_totals),
        exclusions=exclusions,
        eur_claims=eur_claims,
    )


def fmt_dkk(value: float | None) -> str:
    return "null" if value is None else f"{value:,.0f}"


def fmt_ratio(value: float | None) -> str:
    return "null" if value is None else f"{value:.3f}"


def table_row(label: str, t: Totals) -> str:
    return (
        f"{label:<12}{t.policy_count:>9,}{fmt_dkk(t.earned_premium_dkk):>14}"
        f"{fmt_dkk(t.incurred_loss_dkk):>14}{fmt_ratio(t.loss_ratio):>8}"
        f"{t.claim_count:>8,}{fmt_dkk(t.largest_claim_dkk):>13}"
    )


def print_figures(result: Result, portfolio_id: str) -> None:
    header = (
        f"{'':<12}{'policies':>9}{'earned_dkk':>14}{'incurred_dkk':>14}"
        f"{'ratio':>8}{'claims':>8}{'largest_dkk':>13}"
    )
    print(header)
    print(table_row("book", result.book))
    for reason, tally in result.exclusions.items():
        print(f"excluded {reason}: {tally.count:,} claims, {fmt_dkk(tally.amount_dkk)} DKK")
    eur = result.eur_claims
    print(f"EUR-denominated claims: {eur.count:,}, incurred DKK {fmt_dkk(eur.amount_dkk)}")
    print(portfolio_id)
    for peril, totals in result.portfolio(portfolio_id).items():
        print(table_row(peril, totals))


def values_equal(field: str, expected: Value, actual: object) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        return False
    if field in COUNT_FIELDS:
        tolerance = 0.0
    elif field == "loss_ratio":
        tolerance = RATIO_TOLERANCE
    else:
        tolerance = DKK_TOLERANCE
    return abs(expected - actual) <= tolerance


def compare(expected: dict[str, Totals], payload: object, portfolio_id: str) -> list[str]:
    """Return one FAIL line per field that differs between the CSVs and the API."""
    if not isinstance(payload, dict):
        return [f"FAIL {portfolio_id}: response is not a JSON object"]
    perils = cast("dict[str, object]", payload).get("perils")
    if not isinstance(perils, list):
        return [f"FAIL {portfolio_id}: response has no 'perils' list"]
    by_peril: dict[str, dict[str, object]] = {}
    for item in cast("list[object]", perils):
        if isinstance(item, dict) and isinstance(cast("dict[str, object]", item).get("peril"), str):
            entry = cast("dict[str, object]", item)
            by_peril[cast(str, entry["peril"])] = entry
        else:
            return [f"FAIL {portfolio_id}: a 'perils' item has no 'peril' string"]

    failures: list[str] = []
    for peril, totals in expected.items():
        api = by_peril.pop(peril, None)
        if api is None:
            failures.append(f"FAIL {portfolio_id} {peril}: missing from the API response")
            continue
        failures.extend(field_failures(f"{portfolio_id} {peril}", totals, api))
    failures.extend(
        f"FAIL {portfolio_id} {peril}: in the API but not in the CSVs" for peril in by_peril
    )
    return failures


def field_failures(label: str, totals: Totals, api: dict[str, object]) -> list[str]:
    """One FAIL line per figure that differs by more than its tolerance."""
    failures: list[str] = []
    for field, value in totals.as_dict().items():
        if field not in api:
            failures.append(f"FAIL {label}.{field}: key missing from the API")
        elif not values_equal(field, value, api[field]):
            failures.append(f"FAIL {label}.{field}: csv {value!r}, api {api[field]!r}")
    return failures


def compare_ranking(expected: list[tuple[str, Totals]], payload: object) -> list[str]:
    """FAIL lines for a different order, or for any Portfolio's total that differs."""
    if not isinstance(payload, dict):
        return ["FAIL ranking: response is not a JSON object"]
    items = cast("dict[str, object]", payload).get("portfolios")
    if not isinstance(items, list):
        return ["FAIL ranking: response has no 'portfolios' list"]
    api_order: list[str] = []
    api_totals: dict[str, dict[str, object]] = {}
    for item in cast("list[object]", items):
        entry = cast("dict[str, object]", item) if isinstance(item, dict) else {}
        portfolio_id, total = entry.get("portfolio_id"), entry.get("total")
        if not isinstance(portfolio_id, str) or not isinstance(total, dict):
            return ["FAIL ranking: an item has no 'portfolio_id' string or 'total' object"]
        api_order.append(portfolio_id)
        api_totals[portfolio_id] = cast("dict[str, object]", total)

    failures: list[str] = []
    expected_order = [portfolio_id for portfolio_id, _ in expected]
    if api_order != expected_order:
        failures.append(f"FAIL ranking order: csv {expected_order}, api {api_order}")
    for portfolio_id, totals in expected:
        api = api_totals.get(portfolio_id)
        if api is None:
            failures.append(f"FAIL ranking {portfolio_id}: missing from the API response")
        else:
            failures.extend(field_failures(f"ranking {portfolio_id} total", totals, api))
    return failures


def fetch(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as response:
        return cast(object, json.load(response))


def fetch_or_fail(url: str) -> tuple[object, str | None]:
    """The JSON at `url`, or a FAIL line saying why there is none."""
    try:
        return fetch(url), None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        return None, f"FAIL {url}: {error}"
    except json.JSONDecodeError as error:
        return None, f"FAIL {url}: response is not JSON ({error})"


def check_portfolio(result: Result, portfolio_id: str, api_base: str) -> bool:
    url = f"{api_base.rstrip('/')}/portfolios/{portfolio_id}/loss-experience"
    payload, error = fetch_or_fail(url)
    if error is not None:
        print(error)
        return False
    failures = compare(result.portfolio(portfolio_id), payload, portfolio_id)
    for line in failures:
        print(line)
    checked = len(result.perils) * len(FIELDS)
    if failures:
        print(f"FAIL: {len(failures)} differences against {url}")
        return False
    print(f"PASS: {portfolio_id} matches {url} on {checked} figures")
    return True


def check_ranking(ranking: list[tuple[str, Totals]], api_base: str) -> bool:
    url = f"{api_base.rstrip('/')}/portfolios/loss-experience"
    payload, error = fetch_or_fail(url)
    if error is not None:
        print(error)
        return False
    failures = compare_ranking(ranking, payload)
    for line in failures:
        print(line)
    if failures:
        print(f"FAIL: {len(failures)} differences in the ranking against {url}")
        return False
    checked = len(ranking) * len(FIELDS)
    print(
        f"PASS: ranking of {len(ranking)} portfolios matches {url} in order and {checked} figures"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute loss experience from the CSVs.")
    parser.add_argument("--data", type=Path, required=True, help="directory with the four CSVs")
    parser.add_argument("--portfolio", default="PF-01", help="Portfolio to show and compare")
    parser.add_argument("--api", help="API base URL, e.g. http://localhost:8000")
    parser.add_argument(
        "--ranking", action="store_true", help="also show and compare every Portfolio's total"
    )
    args = parser.parse_args(argv)
    portfolio_id = cast(str, args.portfolio)
    api_base = cast("str | None", args.api)
    with_ranking = cast(bool, args.ranking)

    result = compute(cast(Path, args.data))
    if portfolio_id not in result.portfolios:
        print(f"unknown portfolio {portfolio_id}", file=sys.stderr)
        return 2
    print_figures(result, portfolio_id)
    ranking = result.ranking()
    if with_ranking:
        print("ranking, worst ratio first")
        for row_portfolio_id, totals in ranking:
            print(table_row(row_portfolio_id, totals))
    if api_base is None:
        return 0

    passed = check_portfolio(result, portfolio_id, api_base)
    if with_ranking:
        passed = check_ranking(ranking, api_base) and passed
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
