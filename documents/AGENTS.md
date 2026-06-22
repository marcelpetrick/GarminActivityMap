# Repository Guidelines

## Commands

- Run the activity exporter: `python -m garmin_export`
- Run the activity map GUI: `python -m activity_map data/garmin/activities`
- Run the GUI smoke check: `QT_QPA_PLATFORM=offscreen python -m activity_map --smoke-test`
- Install runtime dependencies: `python -m pip install -r requirements.txt`
- Run tests: `python -m pytest`
- Run tests with coverage: `python -m pytest --cov=activity_map --cov=garmin_export --cov-report=term-missing --cov-fail-under=85`
- Run linting: `python -m ruff check .`
- Run static analysis: `python -m mypy activity_map garmin_export tests`
- Build documentation: `python scripts/build_docs.py`
- Run the full local pipeline: `./localPipeline.sh`
- Check repository status before every commit: `git status --short`

## Privacy Rules

- Never commit Garmin credentials, session files, activity exports, raw API responses, downloaded health data, or generated local caches.
- Keep private runtime data under `data/`, `exports/`, or another ignored local-only path.
- Treat map tracks and derived location datasets as private unless they are small synthetic test fixtures.
- Use ignored `.env` only for non-secret local defaults such as `GARMIN_EMAIL`.
- Never store Garmin passwords in files, environment variables, shell history, docs, tests, or commits; enter passwords manually when prompted.
- Before committing, verify that staged files do not contain names, email addresses, exact home/work locations, access tokens, cookies, or activity payloads.

## GUI Development

- Keep parsing, projection, aggregation, and rendering-state logic in testable non-GUI modules.
- Keep PyQt widgets thin: they should delegate data loading and map math to pure Python helpers.
- Use only synthetic GPS fixtures in tests.
- The GUI must fail safely on malformed files by reporting skipped files instead of crashing.
- The map view must support pan, wheel zoom, and visible track rendering before a feature is considered runnable.
- Map tile features must cache downloaded tiles under ignored local storage and keep tests deterministic by disabling live tile downloads.
- PyQt tests must run with `QT_QPA_PLATFORM=offscreen` in the local pipeline.

## Quality Gates

- Every commit must pass `./localPipeline.sh`.
- Unit tests must cover parser behavior, malformed input handling, coordinate projection, bounds calculation, and render preparation.
- Add GUI smoke tests where practical without requiring private Garmin data.
- Keep the pipeline's run step non-interactive: CLI help plus GUI offscreen smoke only.
- Keep C4-style architecture documentation valid through the documentation build step.
- Maintain coverage at or above the configured threshold unless the threshold is raised.

## Versioning

- Use semantic versioning.
- Start at `0.0.0`.
- Increase the patch version for every new commit.

## Commits

- Use conventional commit messages, for example `feat: add garmin activity exporter`.
- Include a clear detail body for non-trivial commits, covering what changed and how it was verified.
- Run the full local pipeline before every commit and fix failures before committing.
- Commit each implementation step separately after the pipeline passes.
- Do not mention the use of any assistant, automation tool, or model in commits, docs, comments, or release notes.

## Major Automated Actions

Before cloud execution, remote generation, repository-wide refactoring,
dependency upgrades, or architecture migrations:

1. Inspect `git status --short --branch`.
2. Complete and verify the current focused change.
3. Commit it with a conventional message and verification detail.
4. Run `./scripts/agentPreflight.sh`; proceed only when it reports a clean
   repository checkpoint.

Do not combine unrelated work packages in one commit. Record the work package
and significant architectural decisions in the commit subject/body and update
the relevant architecture or usage documentation. Prefer additive migrations
and small reversible changes so `git revert`, `git bisect`, and incremental
recovery remain practical.

If a major action fails, preserve the failing evidence, return to the last clean
checkpoint with a non-destructive recovery strategy, and resume in a new
focused commit. Never discard unrelated user changes.
