#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if [ ! -d .venv ]; then
  printf 'Missing .venv. Create it first with ./localPipeline.sh or python -m venv .venv.\n' >&2
  exit 1
fi

. .venv/bin/activate

printf 'Garmin year export\n'
printf '  Repository   : %s\n' "$script_dir"
printf '  Python       : %s\n' "$(python --version 2>&1)"
printf '  Output root  : %s (override with --output-root)\n' "$script_dir/data/garmin"
printf '  Pacing       : --detail-delay 2 --detail-jitter 2, verbose logging on\n'
printf '  Resume       : already downloaded activities are skipped, only gaps are fetched\n'
printf '  Extra flags  : %s\n' "${*:-none}"
printf '  Credentials  : email from GARMIN_EMAIL or prompt, password and MFA typed at runtime\n\n'

python -m garmin_export.year_range \
  --start-year 2025 \
  --end-year 2017 \
  --output-root data/garmin \
  --detail-delay 2 \
  --detail-jitter 2 \
  --verbose \
  "$@"
