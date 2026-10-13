---
name: verify
description: "Apply to every build unit and before calling anything done. One unit at a time: name its proof first, build it, run the checks and the real artifact, review, record the result in the README feature map, commit."
---

# Verify

Light version of `principle-sequence-verifiable-units` and `principle-prove-it-works`. A unit is done
when its proof shows it, not when the code compiles. This is the full per-unit loop; `AGENTS.md`
summarises it.

## Per unit

1. **Name the proof first.** Add or update its row in the README feature map:

   | Feature | Proof command | Observed | Status |
   |---|---|---|---|
   | Field assessment | `loss-experience assess F1` | | planned |

2. **Build the smallest change** that makes that proof possible. One behaviour, disjoint files.
3. **Run the checks.**
   - Windows: `uv run ruff check . --fix`, `uv run ruff format .`, `uv run pyright`
   - Python execution: `./scripts/wsl.ps1 run pytest` and `./scripts/wsl.ps1 run loss-experience proof`
     (plain `uv run` elsewhere)
   - Web, if touched: `pnpm -C web typecheck`, `pnpm -C web test`, `pnpm -C web build`
   - A failure from the tool or environment rather than the code: look in the Papercuts table in
     `docs/AI_LOG.md` first; if it is new and cost more than two minutes, add its line.
4. **Exercise the real artifact.** Run the proof command on the task's own data, not only the sample.
   For the API, start it once and request one known and one unknown Asset. When the task's data
   becomes the default, change `DEFAULT_DATA` in `cli.py` and commit that data (or a small cut of it)
   so CI's `git diff --exit-code proof/` still matches.
5. **Read the diff of `proof/latest.txt`.** Every changed line has a reason you can say out loud.
   A value that became zero where data is missing is a bug. If the run disproves an assumption,
   stop and supersede the decision in `docs/DECISIONS.md` before the next unit.
6. **Review.** Before committing, give `reviewer` the uncommitted diff, the proof output and any new
   decision when the unit changes a calculation, a contract or a decision. Skip it for docs or
   wiring units and say so in the AI log.
7. **Record.** Set the row's Status to `proven` with the observed output in one line, commit the unit
   with a conventional message, and add its line to `docs/AI_LOG.md`.

## Before declaring the task done

- The user task row is `proven` by running the task on its real data, not by the tests.
- All other feature map rows are `proven` or moved to "What I left out".
- `git status` is clean, CI commands pass, `proof/latest.txt` matches the README.
- Report one line per unit: unit, checks, proof, verdict.
