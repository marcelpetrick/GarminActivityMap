#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

data_dir="${1:-data/garmin}"

if [ ! -d .venv ]; then
  printf 'Missing .venv. Create it first with ./localPipeline.sh or python -m venv .venv.\n' >&2
  exit 1
fi

if [ ! -d "$data_dir" ]; then
  printf 'Missing data directory: %s\n' "$data_dir" >&2
  printf 'Export activities first with ./exportGarminYears.sh, or pass a directory as argument.\n' >&2
  exit 1
fi

. .venv/bin/activate

printf 'Garmin activity map\n'
printf '  Repository   : %s\n' "$script_dir"
printf '  Python       : %s\n' "$(python --version 2>&1)"
printf '  Data folder  : %s (override by passing a directory as first argument)\n' "$data_dir"
printf '  Activities   : %s JSON files\n' "$(find "$data_dir" -name '*.json' | wc -l)"
extra="${*:2}"
printf '  Extra flags  : %s\n\n' "${extra:-none}"

exec python -m activity_map "$data_dir" "${@:2}"
