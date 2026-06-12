# Repository Guidelines

## Commands

- Run the activity exporter: `python -m garmin_export`
- Install runtime dependencies: `python -m pip install -r requirements.txt`
- Run tests: `python -m pytest`
- Run linting: `python -m ruff check .`
- Run static analysis: `python -m mypy garmin_export tests`
- Run the full local pipeline: `./localPipeline.sh`
- Check repository status before every commit: `git status --short`

## Privacy Rules

- Never commit Garmin credentials, session files, activity exports, raw API responses, downloaded health data, or generated local caches.
- Keep private runtime data under `data/`, `exports/`, or another ignored local-only path.
- Use ignored `.env` only for non-secret local defaults such as `GARMIN_EMAIL`.
- Never store Garmin passwords in files, environment variables, shell history, docs, tests, or commits; enter passwords manually when prompted.
- Before committing, verify that staged files do not contain names, email addresses, exact home/work locations, access tokens, cookies, or activity payloads.

## Versioning

- Use semantic versioning.
- Start at `0.0.0`.
- Increase the patch version for every new commit.

## Commits

- Use conventional commit messages, for example `feat: add garmin activity exporter`.
- Run the full local pipeline before every commit and fix failures before committing.
- Do not mention the use of any assistant, automation tool, or model in commits, docs, comments, or release notes.
