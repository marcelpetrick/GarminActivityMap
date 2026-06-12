# Garmin Activity Exporter

Export all Garmin Connect activities to local JSON files for later analysis.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in your shell or in a local `.env` loader of your choice. Do not commit `.env`.

```bash
read -r GARMIN_EMAIL
read -rs GARMIN_PASSWORD
export GARMIN_EMAIL GARMIN_PASSWORD
```

## Export

```bash
python -m garmin_export
```

By default, exported data is written under `data/garmin/activities/`, which is ignored by git. Authentication tokens are stored outside the repository by the `garminconnect` package unless `GARMIN_TOKENSTORE` is set.

Useful options:

```bash
python -m garmin_export --output-dir data/garmin/activities --page-size 100
python -m garmin_export --no-details
python -m garmin_export --activity-type running
```

## Privacy

Garmin activity exports can contain names, locations, timestamps, device IDs, and route data. Keep generated files under ignored paths such as `data/` or `exports/`, and check `git status --short` before committing.
