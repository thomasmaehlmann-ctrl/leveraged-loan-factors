#!/usr/bin/env bash
# Full pipeline: SEC N-PORT data sets -> factor database release.
# Usage: ./run_pipeline.sh "Your Name your.email@example.org" 2026q2 2026.11
set -euo pipefail
UA="$1"; END_Q="$2"; VERSION="$3"
python pipeline/nport_loans.py --start 2019q4 --end "$END_Q" --user-agent "$UA"
python pipeline/nport_rekey.py
python pipeline/nport_loan_returns.py --panel nport_out/loan_price_panel_v2.parquet --base-source sofr
python pipeline/loan_characteristics.py --freq M
python pipeline/export_database.py --version "$VERSION" \
  --base-rate "90-day average SOFR (FRED SOFR90DAYAVG), +26.161 bp until 2023-06" --zip
