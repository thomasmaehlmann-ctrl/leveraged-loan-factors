# Full pipeline: SEC N-PORT data sets -> factor database release (Windows PowerShell).
# Usage: .\run_pipeline.ps1 -UserAgent "Your Name your.email@example.org" -EndQuarter 2026q2 -Version 2026.11
param(
    [Parameter(Mandatory = $true)][string]$UserAgent,
    [Parameter(Mandatory = $true)][string]$EndQuarter,
    [Parameter(Mandatory = $true)][string]$Version
)
function Step($cmd) {
    Write-Host ">> $cmd"
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) { Write-Error "Step failed: $cmd"; exit $LASTEXITCODE }
}
Step "python pipeline/nport_loans.py --start 2019q4 --end $EndQuarter --user-agent `"$UserAgent`""
Step "python pipeline/nport_rekey.py"
Step "python pipeline/nport_loan_returns.py --panel nport_out/loan_price_panel_v2.parquet --base-source sofr"
Step "python pipeline/loan_characteristics.py --freq M"
Step "python pipeline/export_database.py --version $Version --base-rate `"90-day average SOFR (FRED SOFR90DAYAVG), +26.161 bp until 2023-06`" --zip"
