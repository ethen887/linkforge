param([string]$IsccPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency synchronization failed.' }
    $compilerArgs = @()
    if ($IsccPath) { $compilerArgs = @('--iscc', $IsccPath) }
    uv run --locked python -m scripts.build_installer @compilerArgs
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
} finally {
    Pop-Location
}
