# Repository Guidelines

## Commands

- Run the activity exporter: `python -m garmin_export`
- Install runtime dependencies: `python -m pip install -r requirements.txt`
- Run tests: `python -m pytest`
- Check repository status before every commit: `git status --short`

## Privacy Rules

- Never commit Garmin credentials, session files, activity exports, raw API responses, downloaded health data, or generated local caches.
- Keep private runtime data under `data/`, `exports/`, or another ignored local-only path.
- Use `.env` for local secrets and keep `.env` ignored.
- Before committing, verify that staged files do not contain names, email addresses, exact home/work locations, access tokens, cookies, or activity payloads.

## Versioning

- Use semantic versioning.
- Start at `0.0.0`.
- Increase the patch version for every new commit.

## Commits

- Use conventional commit messages, for example `feat: add garmin activity exporter`.
- Do not mention the use of any assistant, automation tool, or model in commits, docs, comments, or release notes.
