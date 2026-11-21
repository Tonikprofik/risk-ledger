# Risk Ledger

Risk Ledger is a Python API and CLI for reviewing property insurance portfolios. It loads assets, policies, claims, and monthly exchange rates from CSV and reports premiums, incurred losses, and loss ratios by peril in DKK.

## Try it

With Python 3.12 and uv installed, run the CLI on the bundled synthetic sample:

```bash
uv sync --locked
uv run risk-ledger --data sample portfolio PF-01
uv run risk-ledger --data sample ranking
uv run risk-ledger --data sample quality
```

Start the FastAPI service and try the same portfolio over HTTP:

```bash
LOSS_DATA=sample uv run uvicorn --factory risk_ledger.api:app_from_env
curl http://localhost:8000/portfolios/PF-01/loss-experience
```

The interactive OpenAPI docs are at `http://localhost:8000/docs`. In PowerShell, set `$env:LOSS_DATA = "sample"` before running the Uvicorn command. You can also start the API with `docker compose up --build`. To use your own CSVs, match the files in [sample/](sample/), put them in the ignored `data/` directory, and start the service without the sample override.

## Check the results

| What to check | Command | Expected result on the sample |
|---|---|---|
| Portfolio breakdown | `uv run risk-ledger --data sample portfolio PF-01` | Flood has DKK 12,000 in premium, DKK 13,000 in incurred loss, and a loss ratio of 1.0833. Fire has a null loss ratio. |
| Portfolio ranking | `uv run risk-ledger --data sample ranking` | PF-01 ranks first. PF-03 has no loss ratio and ranks last. |
| Data quality | `uv run risk-ledger --data sample quality` | One orphan claim and one negative payment are excluded. Repairs and flags have separate counts. |
| Independent check | `python scripts/check_loss_experience.py --data sample --api http://localhost:8000 --ranking` | Recomputes portfolio figures and ranking from the CSVs and compares them with the running API. |
| Tests and reproducible proof | `uv run pytest` and `uv run risk-ledger proof` | Tests include the OpenAPI contract. The proof reproduces [proof/latest.txt](proof/latest.txt). |

## How it works

`sources.py` validates and normalizes the CSVs at load time. It reports exclusions and flags with counts and monetary amounts where available. `domain.py` calculates portfolio results without I/O. The API and CLI share those calculations.

Premium converts at the policy inception month and claims convert at the loss month. Each amount uses its own currency. A zero premium yields a null loss ratio. See the [glossary](docs/GLOSSARY.md) and [design decisions](docs/DECISIONS.md) for the calculation rules and tradeoffs.

The development setup includes CI, Docker, and a WSL wrapper. [AGENTS.md](AGENTS.md) describes how the agent setup is used. [The engineering log](docs/AI_LOG.md) records how the work was reviewed and verified.
