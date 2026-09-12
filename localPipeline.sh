#!/usr/bin/env bash
set -u -o pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

PYTHON="${PYTHON:-python}"

tmp_dir="$(mktemp -d)" || exit 1
trap 'rm -rf "$tmp_dir"' EXIT

step_names=()
step_results=()
step_details=()
STEP_DETAIL=""

run_step() {
  local name="$1"
  shift

  printf '\n==> %s\n' "$name"
  step_names+=("$name")
  STEP_DETAIL=""
  if "$@"; then
    step_results+=("PASS")
    step_details+=("${STEP_DETAIL:-completed}")
    printf 'PASS: %s\n' "$name"
  else
    step_results+=("FAIL")
    step_details+=("${STEP_DETAIL:-see step output above}")
    printf 'FAIL: %s\n' "$name"
  fi
}

activate_venv() {
  if [ ! -f .venv/bin/activate ]; then
    STEP_DETAIL="missing .venv; virtualenv step must pass first"
    printf '%s\n' "$STEP_DETAIL" >&2
    return 1
  fi
  # shellcheck disable=SC1091
  . .venv/bin/activate
}

last_line() {
  sed -e 's/^[= ]*//' -e 's/[= ]*$//' "$1" | awk 'NF { line = $0 } END { print line }'
}

virtualenv_step() {
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    STEP_DETAIL="$PYTHON not found on PATH"
    return 1
  fi
  if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv || return 1
  fi
  local version
  version="$(.venv/bin/python --version 2>&1)" || return 1
  STEP_DETAIL=".venv is available ($version)"
}

dependencies() {
  activate_venv || return 1
  python -m pip install --upgrade pip==26.2.1 || return 1
  python -m pip install -r requirements.txt || return 1
  python -m pip install -e ".[dev]" || return 1
  STEP_DETAIL="Editable install with dev dependencies completed"
}

formatting() {
  activate_venv || return 1
  local log="$tmp_dir/format.log"
  if ! python -m ruff format --check . 2>&1 | tee "$log"; then
    STEP_DETAIL="$(last_line "$log")"
    return 1
  fi
  STEP_DETAIL="$(last_line "$log")"
}

lint() {
  activate_venv || return 1
  bash -n localPipeline.sh exportGarminYears.sh scripts/agentPreflight.sh || return 1
  local log="$tmp_dir/lint.log"
  if ! python -m ruff check . 2>&1 | tee "$log"; then
    STEP_DETAIL="$(grep -cE '^[^ ]+:[0-9]+:[0-9]+:' "$log" || true) violations"
    return 1
  fi
  STEP_DETAIL="0 violations; shell syntax OK"
}

static_analysis() {
  activate_venv || return 1
  local complexity_output
  python -m mypy activity_map garmin_export tests benchmarks || return 1
  python -m vulture activity_map garmin_export scripts tests \
    --min-confidence 90 \
    --ignore-names sortorder,prompt || return 1
  complexity_output="$(
    python -m radon cc activity_map garmin_export scripts -n D -s
  )" || return 1
  if [ -n "$complexity_output" ]; then
    printf '%s\n' "$complexity_output"
    STEP_DETAIL="functions with complexity grade D or worse found"
    return 1
  fi
  printf 'No functions with complexity grade D or worse\n'
  python -m pip check || return 1
  STEP_DETAIL="mypy, vulture, radon and pip check are clean"
}

architecture_checks() {
  activate_venv || return 1
  local log="$tmp_dir/architecture.log"
  if ! python scripts/check_architecture.py 2>&1 | tee "$log"; then
    STEP_DETAIL="$(last_line "$log")"
    return 1
  fi
  STEP_DETAIL="$(last_line "$log")"
}

docs_build() {
  activate_venv || return 1
  local log="$tmp_dir/docs.log"
  if ! python scripts/build_docs.py 2>&1 | tee "$log"; then
    STEP_DETAIL="$(last_line "$log")"
    return 1
  fi
  STEP_DETAIL="$(last_line "$log")"
}

build() {
  activate_venv || return 1
  python -m compileall activity_map garmin_export tests benchmarks || return 1
  local log="$tmp_dir/build.log"
  if ! python -m build 2>&1 | tee "$log"; then
    STEP_DETAIL="package build failed"
    return 1
  fi
  STEP_DETAIL="$(grep -E '^Successfully built' "$log" | tail -n 1)"
  STEP_DETAIL="${STEP_DETAIL:-package built}"
}

test_suite() {
  activate_venv || return 1
  export QT_QPA_PLATFORM=offscreen
  export ACTIVITY_MAP_DISABLE_TILES=1
  local log="$tmp_dir/pytest.log"
  local status=0
  python -m pytest 2>&1 | tee "$log" || status=1
  local summary
  summary="$(grep -E '[0-9]+ (passed|failed|error)' "$log" | tail -n 1 |
    sed -e 's/^[= ]*//' -e 's/[= ]*$//')"
  STEP_DETAIL="${summary:-no pytest summary found}"
  return "$status"
}

coverage_check() {
  activate_venv || return 1
  local log="$tmp_dir/coverage.log"
  local status=0
  python -m coverage report --fail-under=95 2>&1 | tee "$log" || status=1
  local total
  total="$(awk '$1 == "TOTAL" { print $NF }' "$log")"
  if [ "$status" -eq 0 ]; then
    STEP_DETAIL="${total:-unknown} (threshold 95%)"
  else
    STEP_DETAIL="${total:-unknown} is below the 95% threshold"
  fi
  return "$status"
}

performance_check() {
  activate_venv || return 1
  export QT_QPA_PLATFORM=offscreen
  export ACTIVITY_MAP_DISABLE_TILES=1
  local log="$tmp_dir/performance.log"
  if ! python benchmarks/benchmark_loading.py \
    --tracks 1000 \
    --points-per-track 300 \
    --samples 1 \
    --max-load-to-display-ms 8000 2>&1 | tee "$log"; then
    STEP_DETAIL="$(last_line "$log")"
    return 1
  fi
  local total
  total="$(
    grep 'Load to first display' "$log" |
      sed -E 's/.*\*\*([0-9.]+ ms)\*\*.*/\1/' |
      tail -n 1
  )"
  STEP_DETAIL="${total:-completed} for 1,000 tracks (limit 8,000 ms)"
}

run_smoke() {
  activate_venv || return 1
  export QT_QPA_PLATFORM=offscreen
  export ACTIVITY_MAP_DISABLE_TILES=1
  python -m garmin_export --help >/dev/null || return 1
  ./exportGarminYears.sh --help >/dev/null || return 1
  python -m activity_map --smoke-test >/dev/null || return 1
  STEP_DETAIL="garmin_export, exportGarminYears.sh and activity_map smoke runs succeeded"
}

run_step "Virtualenv" virtualenv_step
run_step "Dependencies" dependencies
run_step "Formatting" formatting
run_step "Lint" lint
run_step "Static Analysis" static_analysis
run_step "Architecture" architecture_checks
run_step "Docs" docs_build
run_step "Package Build" build
run_step "Tests" test_suite
run_step "Coverage" coverage_check
run_step "Performance" performance_check
run_step "Smoke Test" run_smoke

printf '\n========== Local Pipeline Summary ==========\n'

failed=0
for index in "${!step_names[@]}"; do
  printf '%-16s : %s %s\n' \
    "${step_names[$index]}" "${step_results[$index]}" "${step_details[$index]}"
  if [ "${step_results[$index]}" != "PASS" ]; then
    failed=1
  fi
done

printf '============================================\n'

exit "$failed"
