"""Command line: run the core without a server, and produce proof that it works.

loss-experience quality              exclusions with their DKK amounts, then repair and flag counts
loss-experience proof                the same lines, also written to proof/latest.txt
loss-experience openapi              the API contract, for docs/openapi.json

`--data` is the directory holding assets.csv, policies.csv, claims.csv and fx_rates.csv
(default `data`; `data/sample` is a tiny set with one of each awkward row).
"""

import argparse
import json
import math
from pathlib import Path

from loss_experience.api import create_app
from loss_experience.domain import Book, ExclusionReason, Observations
from loss_experience.sources import load_book

DEFAULT_DATA = Path("data")
PROOF = Path("proof/latest.txt")


class _NoObservations:
    """Empty source so `openapi` runs until U2 replaces the starter's assessment API."""

    def observations(self, asset_id: str) -> Observations | None:
        return None

    def all_observations(self) -> list[Observations]:
        return []


def quality_lines(book: Book) -> list[str]:
    lines = [
        f"loaded\tassets={len(book.assets)}\tpolicies={len(book.policies)}"
        f"\tclaims={len(book.claims)}"
    ]
    for reason in ExclusionReason:
        excluded = [exclusion for exclusion in book.exclusions if exclusion.reason is reason]
        amount_dkk = math.fsum(exclusion.amount_dkk for exclusion in excluded)
        lines.append(f"excluded\t{reason}\tclaims={len(excluded)}\tamount_dkk={amount_dkk:.2f}")
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
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("quality")
    commands.add_parser("proof")
    commands.add_parser("openapi")
    args = parser.parse_args(argv)

    if args.command == "openapi":
        print(json.dumps(create_app(_NoObservations()).openapi(), indent=2, sort_keys=True))
        return 0

    data: Path = args.data
    text = "\n".join([f"data: {data.as_posix()}", *quality_lines(load_book(data))]) + "\n"
    if args.command == "proof":
        PROOF.parent.mkdir(exist_ok=True)
        PROOF.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0
