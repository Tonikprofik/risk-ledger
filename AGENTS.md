# Working on Risk Ledger

Read [project scope](docs/TASK.md), [design decisions](docs/DECISIONS.md), and the [glossary](docs/GLOSSARY.md) before changing the service. The [README](README.md) shows how to reproduce a result on synthetic data.

Keep calculations in the pure domain module. Validate and normalize at the file boundary, preserve the OpenAPI contract, and distinguish missing values from zero. Keep private inputs in the ignored `data/` directory.

Run `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`, and `uv run risk-ledger proof`. The proof should leave `proof/latest.txt` unchanged.

On Windows, use `./scripts/wsl.ps1 run <cmd>` if Application Control blocks Python wheels. The [engineering log](docs/AI_LOG.md) has the setup notes.

Agent profiles live in `.claude/agents/` and `.codex/agents/`. Reusable skills and their notices live in `.agents/skills/` and `.claude/skills/`. The engineer reviews the diff and decides what ships.
