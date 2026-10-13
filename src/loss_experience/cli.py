"""Command line: run the core without a server, and produce proof that it works.

loss-experience portfolio PF-01      one Portfolio's loss experience, as the API's JSON
loss-experience quality              exclusions with their DKK amounts, then repair and flag counts
loss-experience ranking              every Portfolio's total, worst loss ratio first
loss-experience proof                every Portfolio and Peril, the ranking, then the quality
                                 lines; also written to proof/latest.txt
loss-experience openapi              the API contract, for docs/openapi.json

`--data` is the directory holding assets.csv, policies.csv, claims.csv and fx_rates.csv.
Without it: `data` when it holds CSVs, else `data/sample`, a tiny committed set with one of
each awkward row (CI has no real data). The first output line names the directory used.
"""

import argparse
import json
import sys
from pathlib import Path

from loss_experience.api import PortfolioLossExperienceOut, create_app
from loss_experience.domain import (
    Book,
    DataQuality,
    FxTable,
    PerilLossExperience,
    exclusion_summaries,
    loss_experience,
    rank_portfolios,
)
from loss_experience.sources import load_book

DEFAULT_DATA = Path("data")
SAMPLE_DATA = DEFAULT_DATA / "sample"
PROOF = Path("proof/latest.txt")
EMPTY_BOOK = Book((), (), (), FxTable({}), (), DataQuality(0, 0, 0, 0, 0, 0.0, 0, 0))


def default_data() -> Path:
    return DEFAULT_DATA if any(DEFAULT_DATA.glob("*.csv")) else SAMPLE_DATA


def _or_null(value: float | None, spec: str) -> str:
    return "null" if value is None else format(value, spec)


def _peril_line(portfolio_id: str, result: PerilLossExperience) -> str:
    return (
        f"{portfolio_id}\t{result.peril}\tpolicies={result.policy_count}"
        f"\tpremium_dkk={result.earned_premium_dkk:.2f}"
        f"\tincurred_dkk={result.incurred_loss_dkk:.2f}"
        f"\tratio={_or_null(result.loss_ratio, '.4f')}\tclaims={result.claim_count}"
        f"\tlargest_dkk={_or_null(result.largest_claim_dkk, '.2f')}"
    )


def ranking_lines(book: Book) -> list[str]:
    """One line per Portfolio, worst total loss ratio first (D16)."""
    return [
        f"ranked\t{result.portfolio_id}\tpolicies={result.total.policy_count}"
        f"\tpremium_dkk={result.total.earned_premium_dkk:.2f}"
        f"\tincurred_dkk={result.total.incurred_loss_dkk:.2f}"
        f"\tratio={_or_null(result.total.loss_ratio, '.4f')}\tclaims={result.total.claim_count}"
        f"\tlargest_dkk={_or_null(result.total.largest_claim_dkk, '.2f')}"
        for result in rank_portfolios(book)
    ]


def portfolio_lines(book: Book) -> list[str]:
    """One line per Portfolio and Peril, Portfolios sorted by id, Perils in enum order."""
    lines: list[str] = []
    for portfolio_id in sorted({asset.portfolio_id for asset in book.assets}):
        result = loss_experience(book, portfolio_id)
        if result is not None:
            lines.extend(_peril_line(portfolio_id, peril) for peril in result.perils)
    return lines


def quality_lines(book: Book) -> list[str]:
    lines = [
        f"loaded\tassets={len(book.assets)}\tpolicies={len(book.policies)}"
        f"\tclaims={len(book.claims)}"
    ]
    lines.extend(
        f"excluded\t{summary.reason}\tclaims={summary.claim_count}"
        f"\tamount_dkk={summary.amount_dkk:.2f}"
        for summary in exclusion_summaries(book.exclusions)
    )
    quality = book.data_quality
    return [
        *lines,
        f"repaired\tperil_spellings\tpolicies={quality.peril_spellings_repaired}",
        f"repaired\tday_first_loss_dates\tclaims={quality.day_first_loss_dates_repaired}",
        f"repaired\tday_first_reported_dates\tclaims={quality.day_first_reported_dates_repaired}",
        f"flagged\tloss_before_inception\tclaims={quality.loss_before_inception_flagged}",
        f"flagged\tsettled_with_reserve\tclaims={quality.settled_with_reserve_flagged}"
        f"\treserve_dkk={quality.settled_reserve_dkk:.2f}",
        f"flagged\tmixed_currency\tclaims={quality.mixed_currency_claims}",
        f"flagged\toverlapping_terms\tpolicies={quality.overlapping_terms}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loss-experience")
    parser.add_argument("--data", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    portfolio = commands.add_parser("portfolio")
    portfolio.add_argument("portfolio_id")
    commands.add_parser("quality")
    commands.add_parser("ranking")
    commands.add_parser("proof")
    commands.add_parser("openapi")
    args = parser.parse_args(argv)

    if args.command == "openapi":
        print(json.dumps(create_app(EMPTY_BOOK).openapi(), indent=2, sort_keys=True))
        return 0

    data: Path = args.data if args.data is not None else default_data()
    book = load_book(data)
    if args.command == "portfolio":
        portfolio_id: str = args.portfolio_id
        result = loss_experience(book, portfolio_id)
        if result is None:
            print(f"unknown portfolio {portfolio_id!r} in {data.as_posix()}", file=sys.stderr)
            return 1
        print(PortfolioLossExperienceOut.from_domain(result).model_dump_json(indent=2))
        return 0

    if args.command == "ranking":
        body = ranking_lines(book)
    elif args.command == "proof":
        body = [*portfolio_lines(book), *ranking_lines(book), *quality_lines(book)]
    else:
        body = quality_lines(book)
    text = "\n".join([f"data: {data.as_posix()}", *body]) + "\n"
    if args.command == "proof":
        PROOF.parent.mkdir(exist_ok=True)
        PROOF.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0
