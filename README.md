# Garmin Activity Exporter

A private-first archive tool for turning a Garmin Connect account into a local, reusable activity dataset. It pulls activity summaries and detail payloads into JSON files so future analysis, dashboards, and visualizations can work from your own disk instead of repeatedly touching the Garmin service.

## Project Information

- Author: `mail@marcelpetrick.it`
- License: GPLv3
- Version: `0.0.8`
- Runtime: Python 3.11+

## Usage Terms

This project is distributed under the GNU General Public License v3.0. You may use, study, modify, and redistribute it under the terms of GPLv3.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set `GARMIN_EMAIL` in your shell or in ignored local `.env`. The password is always entered manually at runtime and is not read from files or environment variables.

```bash
read -r GARMIN_EMAIL
export GARMIN_EMAIL
```

## Export

```bash
python -m garmin_export
```

By default, exported data is written under `data/garmin/activities/`, which is ignored by git. Authentication tokens are stored outside the repository by the `garminconnect` package unless `GARMIN_TOKENSTORE` is set. Do not point `GARMIN_TOKENSTORE` at a tracked repository path.

Useful options:

```bash
python -m garmin_export --output-dir data/garmin/activities --page-size 100
python -m garmin_export --no-details
python -m garmin_export --activity-type running
python -m garmin_export --start-date 2026-05-13 --end-date 2026-06-13
```

## Visualize

```bash
python -m activity_map data/garmin/activities
```

The desktop app loads Garmin JSON exports from an ignored local directory and renders tracks plus heat density on an offline world map. Drag to pan, use the mouse wheel to zoom, and use reset view to fit loaded tracks again.

## Local Pipeline

```bash
./localPipeline.sh
```

The pipeline creates or reuses `.venv`, installs dependencies, runs linting and static analysis, builds the package, runs tests, performs CLI and GUI smoke runs, and prints a summary.

## Privacy

Garmin activity exports can contain names, locations, timestamps, device IDs, and route data. Keep generated files under ignored paths such as `data/` or `exports/`, and check `git status --short` before committing.
