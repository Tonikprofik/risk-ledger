"""Command line: run the core without a server, and produce proof that it works.

loss-experience assess F1            one Assessment as JSON
loss-experience proof                every sample Asset, written to proof/latest.txt
loss-experience openapi              the API contract, for docs/openapi.json
"""

import argparse
import json
import sys
from pathlib import Path

from loss_experience.api import AssessmentOut, create_app
from loss_experience.domain import assess
from loss_experience.sources import CsvObservationSource

DEFAULT_DATA = Path("data/sample/observations.csv")
PROOF = Path("proof/latest.txt")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loss-experience")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--min-coverage", type=float, default=0.5)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("assess").add_argument("asset_id")
    commands.add_parser("proof")
    commands.add_parser("openapi")
    args = parser.parse_args(argv)

    source = CsvObservationSource(args.data)
    if args.command == "openapi":
        print(json.dumps(create_app(source).openapi(), indent=2, sort_keys=True))
        return 0
    if args.command == "assess":
        observations = source.observations(args.asset_id)
        if observations is None:
            print(f"unknown asset {args.asset_id!r}", file=sys.stderr)
            return 1
        result = assess(observations, min_coverage=args.min_coverage)
        print(AssessmentOut.from_domain(result).model_dump_json(indent=2))
        return 0

    lines = [f"data: {args.data.as_posix()}  min_coverage: {args.min_coverage}"]
    for observations in source.all_observations():
        out = AssessmentOut.from_domain(assess(observations, min_coverage=args.min_coverage))
        value = "-" if out.value is None else f"{out.value:.4f}"
        lines.append(
            f"{out.asset_id}\t{out.status}\tvalue={value}\tcoverage={out.coverage_fraction:.2f}"
        )
    PROOF.parent.mkdir(exist_ok=True)
    PROOF.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(PROOF.read_text(encoding="utf-8"), end="")
    return 0
