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
from typing import assert_never

from loss_experience.api import PortfolioLossExperienceOut, create_app
from loss_experience.domain import (
    Book,
    DataQuality,
    FlagKind,
    FxTable,
    PerilLossExperience,
    RepairKind,
    exclusion_summaries,
    flag_counts,
    loss_experience,
    rank_portfolios,
    repair_counts,
)
from loss_experience.sources import SAMPLE_DATA, default_data, load_book

PROOF = Path("proof/latest.txt")
EMPTY_BOOK = Book((), (), (), FxTable({}), (), DataQuality(0, 0, 0, 0, 0, 0.0, 0, 0))


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


def _counted(kind: RepairKind | FlagKind) -> str:
    """The rows a repair or flag count is of."""
    match kind:
        case RepairKind.PERIL_SPELLINGS | FlagKind.OVERLAPPING_TERMS:
            return "policies"
        case (
            RepairKind.DAY_FIRST_LOSS_DATES
            | RepairKind.DAY_FIRST_REPORTED_DATES
            | FlagKind.LOSS_BEFORE_INCEPTION
            | FlagKind.SETTLED_WITH_RESERVE
            | FlagKind.MIXED_CURRENCY
        ):
            return "claims"
        case _:
            assert_never(kind)


def quality_lines(book: Book) -> list[str]:
    """The data the API's /data-quality serves, one line per count. The only flag amount is the
    settled_with_reserve reserve, hence its label."""
    return [
        f"loaded\tassets={len(book.assets)}\tpolicies={len(book.policies)}"
        f"\tclaims={len(book.claims)}",
        *(
            f"excluded\t{summary.reason}\tclaims={summary.claim_count}"
            f"\tamount_dkk={summary.amount_dkk:.2f}"
            for summary in exclusion_summaries(book.exclusions)
        ),
        *(
            f"repaired\t{repair.kind}\t{_counted(repair.kind)}={repair.count}"
            for repair in repair_counts(book.data_quality)
        ),
        *(
            f"flagged\t{flag.kind}\t{_counted(flag.kind)}={flag.count}"
            + ("" if flag.amount_dkk is None else f"\treserve_dkk={flag.amount_dkk:.2f}")
            for flag in flag_counts(book.data_quality)
        ),
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

    if args.data is not None:
        data: Path = args.data
    elif args.command == "proof":
        data = SAMPLE_DATA  # the proof is the committed baseline, so it never follows local data
    else:
        data = default_data()
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
