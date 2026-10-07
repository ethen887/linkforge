$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency synchronization failed.' }
    uv run --locked python scripts/build_windows.py
    if ($LASTEXITCODE -ne 0) { throw 'Portable build failed.' }
} finally {
    Pop-Location
}
