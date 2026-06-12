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

lint() {
  . .venv/bin/activate
  python -m ruff check .
}

static_analysis() {
  . .venv/bin/activate
  python -m mypy activity_map garmin_export tests
}

build() {
  . .venv/bin/activate
  python -m compileall activity_map garmin_export tests
  python -m build
}

test_suite() {
  . .venv/bin/activate
  python -m pytest
}

run_smoke() {
  . .venv/bin/activate
  python -m garmin_export --help >/dev/null
}

run_step "bootstrap" bootstrap
run_step "lint" lint
run_step "static" static_analysis
run_step "build" build
run_step "test" test_suite
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
