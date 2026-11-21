# Engineering log

| Work | How it was checked |
|---|---|
| Input loading and portfolio calculations | A human engineer reviewed the input rules and checked the service against an independent CSV calculation. |
| API and CLI | Agent-assisted changes were reviewed separately and checked against observable outputs, including the OpenAPI snapshot. |
| Local setup | The service was exercised through the CLI and Docker. The sample proof is reproducible in CI. |
| Portfolio documentation | Codex removed assessment context and private-input aggregates from the public-facing material. The sample supplies the figures shown in the README. |

## Papercuts

| Symptom | Fix |
|---|---|
| Windows Application Control blocks compiled wheels | Run Python commands through `./scripts/wsl.ps1 run <cmd>`. Run `./scripts/wsl.ps1 sync` after dependency changes. |
| Git Bash rewrites WSL paths | Run the WSL wrapper from PowerShell. |
