# Repository Guidelines

## Commands

- Run the activity exporter: `python -m garmin_export`
- Install runtime dependencies: `python -m pip install -r requirements.txt`
- Run tests: `python -m pytest`
- Run tests with coverage: `python -m pytest --cov=garmin_export --cov-report=term-missing --cov-fail-under=85`
- Run linting: `python -m ruff check .`
- Run static analysis: `python -m mypy garmin_export tests`
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
- The map view must support pan, wheel zoom, and visible track/heat rendering before a feature is considered runnable.

## Quality Gates

- Every commit must pass `./localPipeline.sh`.
- Unit tests must cover parser behavior, malformed input handling, coordinate projection, bounds calculation, and heat aggregation.
- Add GUI smoke tests where practical without requiring private Garmin data.
- Maintain coverage at or above the configured threshold unless the threshold is raised.

## Versioning

- Use semantic versioning.
- Start at `0.0.0`.
- Increase the patch version for every new commit.

## Commits

- Use conventional commit messages, for example `feat: add garmin activity exporter`.
- Run the full local pipeline before every commit and fix failures before committing.
- Commit each implementation step separately after the pipeline passes.
- Do not mention the use of any assistant, automation tool, or model in commits, docs, comments, or release notes.
