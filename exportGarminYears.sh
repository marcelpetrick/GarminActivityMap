#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if [ ! -d .venv ]; then
  printf 'Missing .venv. Create it first with ./localPipeline.sh or python -m venv .venv.\n' >&2
  exit 1
fi

. .venv/bin/activate

python -m garmin_export.year_range \
  --start-year 2025 \
  --end-year 2017 \
  --output-root data/garmin \
  --detail-delay 2 \
  --detail-jitter 2 \
  --verbose \
  "$@"
