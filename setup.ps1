# Sidenote - setup for a cloned repo.
#
# Installs the package (which pulls its own dependencies from pyproject.toml)
# and adds the PowerShell helper functions. If you installed from PyPI with
# `pip install sidenote`, you don't need this script at all - just run
# `sidenote init`.

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Sidenote - Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Installing from: $scriptDir" -ForegroundColor Gray
Write-Host ""

# Check Python
Write-Host "[1/3] Checking Python installation..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "X Python not found! Install Python 3.9+ from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "  Python found: $pythonVersion" -ForegroundColor Green

# Install the package. Dependencies come from pyproject.toml, so there is only
# one place where versions are declared.
Write-Host ""
Write-Host "[2/3] Installing sidenote and dependencies..." -ForegroundColor Yellow
Push-Location $scriptDir
try {
    python -m pip install -e .
} finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "X Installation failed." -ForegroundColor Red
    exit 1
}
Write-Host "  Package installed" -ForegroundColor Green

# Add the PowerShell helpers via the CLI itself, rather than writing a second
# copy of the profile block here that could drift out of sync.
Write-Host ""
Write-Host "[3/3] Adding PowerShell commands..." -ForegroundColor Yellow
sidenote init

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Setup Complete!" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close and reopen PowerShell, then use:" -ForegroundColor White
Write-Host "  sidenote" -ForegroundColor Yellow -NoNewline
Write-Host "         - Start the overlay" -ForegroundColor White
Write-Host "  sidenote stop" -ForegroundColor Yellow -NoNewline
Write-Host "    - Stop the overlay" -ForegroundColor White
Write-Host "  sidenote status" -ForegroundColor Yellow -NoNewline
Write-Host "  - Check whether it's running" -ForegroundColor White
Write-Host "  Shift+Tab" -ForegroundColor Yellow -NoNewline
Write-Host "        - Toggle from anywhere" -ForegroundColor White
Write-Host ""
