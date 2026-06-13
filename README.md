# Garmin Activity Exporter

A private-first archive tool for turning a Garmin Connect account into a local, reusable activity dataset. It pulls activity summaries and detail payloads into JSON files so future analysis, dashboards, and visualizations can work from your own disk instead of repeatedly touching the Garmin service.

## Project Information

- Author: `mail@marcelpetrick.it`
- License: GPLv3
- Version: `0.0.14`
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

The desktop app loads Garmin JSON exports from an ignored local directory and renders tracks plus heat density over an OpenStreetMap base layer. Downloaded map tiles are cached under ignored `data/map_tiles/`; repeat views use the local cache, and panning or zooming automatically requests newly visible tiles.

Expected local layout:

```text
data/
  garmin/
    activities/
      manifest.json
      activities/
        activity-123456789.json
        activity-987654321.json
```

Controls:

- Open Directory: choose a folder containing exported Garmin JSON files.
- Reset View: fit the visible map back to the loaded tracks.
- Track Opacity: make individual routes lighter or stronger.
- Heat Intensity: tune the density overlay.
- Map Opacity: make the OpenStreetMap base layer subtle or prominent.
- OpenStreetMap layer: toggle the map base layer while keeping tracks and heat visible.
- Drag the map to pan, use the mouse wheel to zoom deeply around the cursor, and double-click the map to reset.

Map colors:

- Cyan and amber lines are activity tracks; the app alternates these colors so overlapping routes are easier to separate.
- Pink/red dots are heat-density cells, not extra activities. Larger or stronger dots mean more GPS points were aggregated in that area.

Supported Garmin export shapes include activity detail files with `geoPolylineDTO.polyline`, `activityDetailMetrics` coordinate metrics, and coordinate-like nested records. Files without usable coordinates are skipped and summarized in the app instead of stopping the load.

For a headless smoke check:

```bash
QT_QPA_PLATFORM=offscreen python -m activity_map --smoke-test
```

Troubleshooting:

- If the map opens but no tracks appear, check the warning count in the left rail. The selected files may not contain GPS coordinates.
- If the GUI cannot start on a server or CI machine, use the offscreen smoke command above.
- To force the synthetic offline background for deterministic checks, run with `ACTIVITY_MAP_DISABLE_TILES=1`.
- Keep real activity directories under ignored paths such as `data/` or `exports/`; the repository uses synthetic fixtures for tests.

## Local Pipeline

```bash
./localPipeline.sh
```

The pipeline creates or reuses `.venv`, installs dependencies, runs linting and static analysis, builds the documentation, builds the package, runs tests, performs CLI and GUI smoke runs, and prints a summary.

## Architecture Documentation

The C4-style architecture views live in `documents/architecture.md`. Build and validate the local documentation bundle with:

```bash
python scripts/build_docs.py
```

Generated documentation output is written to ignored `build/docs/`.

## Privacy

Garmin activity exports can contain names, locations, timestamps, device IDs, and route data. Keep generated files under ignored paths such as `data/` or `exports/`, and check `git status --short` before committing.
