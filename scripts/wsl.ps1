# Run a uv command for this repo inside WSL, e.g. `./scripts/wsl.ps1 run pytest`.
# Windows Application Control on the author's machine blocks compiled wheels
# such as pandas, pyproj and rasterio, so Python runs in Linux instead.
$repo = Split-Path -Parent $PSScriptRoot
wsl.exe -d Ubuntu-24.04 --cd $repo -- env UV_PROJECT_ENVIRONMENT=.venv-wsl UV_LINK_MODE=copy uv @args
exit $LASTEXITCODE
