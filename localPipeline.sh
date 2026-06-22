#!/usr/bin/env bash
set -u

steps=()
results=()

run_step() {
  local name="$1"
  shift

  printf '\n==> %s\n' "$name"
  steps+=("$name")
  if "$@"; then
    results+=("PASS")
    printf 'PASS: %s\n' "$name"
  else
    results+=("FAIL")
    printf 'FAIL: %s\n' "$name"
  fi
}

bootstrap() {
  if [ ! -d .venv ]; then
    python -m venv .venv
  fi

  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  python -m pip install -e ".[dev]"
}

formatting() {
  . .venv/bin/activate
  python -m ruff format --check .
}

lint() {
  . .venv/bin/activate
  bash -n localPipeline.sh exportGarminYears.sh
  python -m ruff check .
}

static_analysis() {
  local complexity_output
  . .venv/bin/activate
  python -m mypy activity_map garmin_export tests
  python -m vulture activity_map garmin_export scripts tests \
    --min-confidence 90 \
    --ignore-names sortorder,prompt
  complexity_output="$(
    python -m radon cc activity_map garmin_export scripts -n D -s
  )"
  if [ -n "$complexity_output" ]; then
    printf '%s\n' "$complexity_output"
    return 1
  fi
  printf 'No functions with complexity grade D or worse\n'
  python -m pip check
}

architecture_checks() {
  . .venv/bin/activate
  python scripts/check_architecture.py
}

docs_build() {
  . .venv/bin/activate
  python scripts/build_docs.py
}

build() {
  . .venv/bin/activate
  python -m compileall activity_map garmin_export tests
  python -m build
}

test_suite() {
  . .venv/bin/activate
  export QT_QPA_PLATFORM=offscreen
  export ACTIVITY_MAP_DISABLE_TILES=1
  python -m pytest
}

coverage_check() {
  . .venv/bin/activate
  python -m coverage report --fail-under=85
}

run_smoke() {
  . .venv/bin/activate
  export QT_QPA_PLATFORM=offscreen
  export ACTIVITY_MAP_DISABLE_TILES=1
  python -m garmin_export --help >/dev/null
  ./exportGarminYears.sh --help >/dev/null
  python -m activity_map --smoke-test >/dev/null
}

run_step "bootstrap" bootstrap
run_step "formatting" formatting
run_step "lint" lint
run_step "static" static_analysis
run_step "architecture" architecture_checks
run_step "docs" docs_build
run_step "build" build
run_step "test" test_suite
run_step "coverage" coverage_check
run_step "run" run_smoke

printf '\nSummary\n'
printf '%-12s %s\n' "Step" "Result"
printf '%-12s %s\n' "----" "------"

failed=0
for index in "${!steps[@]}"; do
  printf '%-12s %s\n' "${steps[$index]}" "${results[$index]}"
  if [ "${results[$index]}" != "PASS" ]; then
    failed=1
  fi
done

exit "$failed"
