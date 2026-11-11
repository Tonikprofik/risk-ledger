"""Command line: run the core without a server, and produce proof that it works.

risk-ledger portfolio PF-01      one Portfolio's loss experience, as the API's JSON
risk-ledger quality              exclusions with their DKK amounts, then repair and flag counts
risk-ledger ranking              every Portfolio's total, worst loss ratio first
risk-ledger proof                every Portfolio and Peril, the ranking, then the quality
                                 lines; without --data it is also written to proof/latest.txt
risk-ledger openapi              the API contract, for docs/openapi.json

`--data` is the directory holding assets.csv, policies.csv, claims.csv and fx_rates.csv.
Without it: `data` when it holds CSVs, else `sample`, a tiny committed set with one of
each awkward row. `proof` without `--data` always reads `sample`, so proof/latest.txt is
the same on every machine and in CI. The first output line names the directory used.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import assert_never

from risk_ledger.api import PortfolioLossExperienceOut, create_app
from risk_ledger.domain import (
    Book,
    FlagKind,
    LossFigures,
    RepairKind,
    exclusion_summaries,
    flag_counts,
    loss_experience,
    rank_portfolios,
    repair_counts,
)
from risk_ledger.sources import SAMPLE_DATA, default_data, load_book

PROOF = Path("proof/latest.txt")


def _or_null(value: float | None, spec: str) -> str:
    return "null" if value is None else format(value, spec)


def _figures(figures: LossFigures) -> str:
    """The six figures at the API's precision, so a proof line and a response agree."""
    return (
        f"policies={figures.policy_count}"
        f"\tpremium_dkk={figures.earned_premium_dkk:.2f}"
        f"\tincurred_dkk={figures.incurred_loss_dkk:.2f}"
        f"\tratio={_or_null(figures.loss_ratio, '.4f')}\tclaims={figures.claim_count}"
        f"\tlargest_dkk={_or_null(figures.largest_claim_dkk, '.2f')}"
    )


def ranking_lines(book: Book) -> list[str]:
    """One line per Portfolio, worst total loss ratio first (D16)."""
    return [
        f"ranked\t{result.portfolio_id}\t{_figures(result.total)}"
        for result in rank_portfolios(book)
    ]


def portfolio_lines(book: Book) -> list[str]:
    """One line per Portfolio and Peril, Portfolios sorted by id, Perils in enum order."""
    lines: list[str] = []
    for portfolio_id in sorted({asset.portfolio_id for asset in book.assets}):
        result = loss_experience(book, portfolio_id)
        if result is not None:
            lines.extend(f"{portfolio_id}\t{p.peril}\t{_figures(p.figures)}" for p in result.perils)
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
    parser = argparse.ArgumentParser(prog="risk-ledger")
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
        app = create_app(load_book(SAMPLE_DATA))  # the schema does not depend on the data
        print(json.dumps(app.openapi(), indent=2, sort_keys=True))
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
    if args.command == "proof" and args.data is None:
        PROOF.parent.mkdir(exist_ok=True)
        PROOF.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0
