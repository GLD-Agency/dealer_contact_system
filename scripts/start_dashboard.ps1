Set-Location $PSScriptRoot\..

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Virtual environment not found at .\.venv\Scripts\python.exe" -ForegroundColor Red
  Write-Host "Run: python -m venv .venv" -ForegroundColor Yellow
  Write-Host "Then: .\.venv\Scripts\pip.exe install -r requirements.txt" -ForegroundColor Yellow
  exit 1
}

& ".\.venv\Scripts\python.exe" main.py serve-dashboard
