# Garmin Activity Map

[![Local Pipeline](https://github.com/marcelpetrick/GarminActivityMap/actions/workflows/local-pipeline.yml/badge.svg?branch=master)](https://github.com/marcelpetrick/GarminActivityMap/actions/workflows/local-pipeline.yml)
[![Python](https://img.shields.io/badge/python-3.14-blue)](https://www.python.org/)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen)](localPipeline.sh)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

A private-first archive tool for turning a Garmin Connect account into a local, reusable activity dataset. It pulls activity summaries and detail payloads into JSON files so future analysis, dashboards, and visualizations can work from your own disk instead of repeatedly touching the Garmin service.

## TL;DR

After completing the setup below, export all activities from 2017 through 2026:

```bash
export GARMIN_EMAIL='garmin-user@example.com'
./exportGarminYears.sh --start-year 2026 --end-year 2017
```

Enter your Garmin password and MFA code when prompted. The export is resumable,
so the same command can be run again after an interruption.

Open all exported years in the map:

```bash
source .venv/bin/activate
python -m activity_map data/garmin
```

![](media/currentState.png)

## Project Information

**Author: Marcel Petrick <mail@marcelpetrick.it>**

**Note: projected is generated with AI.**

**License: GPLv3 or later. See `LICENSE`.**

- Version: `0.0.71`
- Runtime: Python 3.14 (the version used for development, the local pipeline, and CI)

## Usage Terms

This project is distributed under the GNU General Public License v3.0. You may use, study, modify, and redistribute it under the terms of GPLv3. The full license text is in `LICENSE`, and the package metadata declares the SPDX expression `GPL-3.0-or-later`, so the license ships inside the built wheel and source distribution.

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

The exporter is intentionally conservative for detailed activity downloads:

- Existing activity JSON files are skipped by default so interrupted exports can resume without repeating calls.
- All Garmin requests are paced at one request per second by default; configure this with `--request-interval`.
- Detail downloads can add an extra `--detail-delay` plus random `--detail-jitter`.
- HTTP 403, 429, 5xx, timeout, and network failures use bounded exponential backoff controlled by `--max-retries`, `--backoff-initial`, and `--backoff-max`.
- `export-state.json` is atomically updated with completed, pending, failed, retry, and estimated-completion data. Failed activities remain absent and are retried on the next run.

Every run reports what it is doing without needing `--verbose`:

```text
Collecting Garmin activity list for 2025-01-01 to 2025-12-31 ...
Export plan for 2025-01-01 to 2025-12-31
  Output directory  : data/garmin/activities-2025
  Activities listed : 312 from 2025-01-02 to 2025-12-30
  Already on disk   : 300 (skipped)
  Still to download : 12
  Estimated runtime : 1m 24s
  12/312 activities processed; 10 downloaded, 300 already present, 0 failed; estimated completion 2026-08-14T18:22:41+00:00
Export finished for data/garmin/activities-2025 in 1m 31s
  Downloaded        : 12
  Already present   : 300
  Failed            : 0 (retried 0 times)
  Manifest entries  : 312
```

The activity list is always re-queried, because that is how new activities are
detected, but only activities whose `activities/<activity-id>.json` file is
missing are downloaded. A rerun of the same command therefore fills gaps -
newly recorded activities and activities that failed earlier - instead of
downloading the archive again. `--no-skip-existing` opts out and re-downloads
everything. Add `--verbose` for a timestamped line per Garmin request, retry,
and file write.

A detailed run also completes activities that were previously exported with
`--no-details`: a stored file that contains only the `summary` payload is
reported as `Summary only` in the plan and its `activity` and `details` payloads
are fetched, so switching from a summary-only export to a full export fills the
missing detail data instead of leaving those activities incomplete forever. A
summary-only run leaves such files untouched.

For a cautious 2026 export:

```bash
python -m garmin_export \
  --start-date 2026-01-01 \
  --end-date 2026-12-31 \
  --output-dir data/garmin/activities-2026 \
  --detail-delay 5 \
  --detail-jitter 5
```

To export full years from the current calendar year back through 2017 into
separate ignored folders, enter the Garmin password once at startup and run:

```bash
./exportGarminYears.sh
```

The script writes to `data/garmin/activities-YYYY/` folders, uses
`--detail-delay 2`, `--detail-jitter 2`, and `--verbose`, and accepts extra
exporter flags at the end. For example, `./exportGarminYears.sh --no-details`
exports summaries only.

The first year is the current calendar year, so the running year's activities
are always included; `--start-year` and `--end-year` override the range. If the
map is missing recent activities, check that a folder for the current year
exists under `data/garmin/` and that its export completed - an interrupted run
leaves `export-state.json` with a non-zero `pending` count and writes no
`manifest.json`.

Before the first Garmin request the script prints the repository path, the
interpreter it activated, the output root, the pacing flags, the extra flags it
received, and a reminder that existing activity files are skipped. Each year
then prints its own plan and completion block, and the run ends with a per-year
summary of new, already present, and failed activities including the detected
date range per year.

Year export layout:

```text
data/
  garmin/
    activities-2025/
      manifest.json
      activities/
        123456789.json
    activities-2024/
      manifest.json
      activities/
        987654321.json
```

The unique activity file key is Garmin's activity id from `activityId`,
`activity_id`, or `id`. Existing `activities/<activity-id>.json` files are
skipped by default, so interrupted year exports can be rerun without
overwriting already downloaded activity payloads. Each year-level
`manifest.json` is regenerated to summarize the latest run. Activity and
manifest JSON files are written through a temporary file and atomically moved
into place, which avoids keeping partial files after an interrupted write.
Date-based exports are split into calendar-month Garmin queries and then
deduplicated by activity id, which avoids relying on a single full-year query
that may be capped by Garmin.

## Visualize

```bash
python -m activity_map data/garmin/activities
```

The desktop app loads Garmin JSON exports from an ignored local directory and renders activity tracks over an OpenStreetMap base layer. Downloaded map tiles are cached under the platform cache directory (`~/.cache/GarminActivityMap/map_tiles/osm` by default, or `$XDG_CACHE_HOME`); repeat views use the local cache, and panning or zooming automatically requests newly visible tiles. Set `ACTIVITY_MAP_TILE_CACHE_DIR` to relocate that cache. Following the OpenStreetMap tile usage policy, tiles are fetched by at most two workers and downloads are paced to at most five per second across all of them; tiles already in the cache are served without any delay. The location no longer depends on the working directory the app was started from, so tiles cannot land in an unrelated project folder.

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
- Track Color: choose one shared color for all rendered activity tracks.
- Track Opacity: make individual routes lighter or stronger.
- Show track names: draw each Garmin activity name near its rendered track.
- Map Opacity: make the OpenStreetMap base layer subtle or prominent.
- OpenStreetMap layer: toggle the map base layer while keeping tracks visible.
- Drag the map to pan, use the mouse wheel to zoom deeply around the cursor, and double-click the map to reset.
- While a directory is still loading, the map keeps fitting each newly arriving batch of tracks until you pan or zoom. After that the view stays where you put it, and Reset View or a double-click hands control back to automatic fitting.
- The bottom-right scale shows one rounded 1/2/5-style distance in kilometers for the current map latitude and zoom.

The app persists the last loaded directory, last run timestamp, track color,
track-name visibility, track/map opacity, map-layer state, and future preference
fields in `~/.config/GarminActivityMap/settings.json`. Missing or corrupt files
fall back to safe defaults. Set `ACTIVITY_MAP_SETTINGS_PATH` to use a different
location.

Map colors:

The selected track color is used for all activity tracks.

Supported Garmin export shapes include activity detail files with `geoPolylineDTO.polyline`, `activityDetailMetrics` coordinate metrics, and coordinate-like nested records. Files without usable coordinates are skipped and summarized in the app instead of stopping the load.

When timestamps are available, the loader validates their ordering and computes
geodesic segment speeds. Segments above 30 km/h are flagged and disconnected
from rendered geometry to suppress GPS spikes; the source JSON is never changed.
Use `load_directory(path, max_speed_kmh=...)` to configure the threshold.

Loaded tracks retain timestamps and altitude where available, plus per-segment
distance and speed, total distance, duration, and geographic bounds. Rendering
uses cached markers at broad zoom, simplified polylines at intermediate zoom,
and full validated geometry when zoomed in.

Parsed tracks and prepared geometry are cached under the platform cache
directory for faster repeat startup. Cache entries are keyed by the resolved
dataset path, the geometry parameters that produced the snapshot (level-of-detail
tolerances, simplification tolerance, segment-split distance, minimum rendered
points, and the speed threshold), plus every activity file's relative path, size,
and modification time, and are written atomically with user-only permissions.
Changing any of those parameters produces a new cache entry instead of silently
reusing geometry prepared by an older build, and superseded entries for the same
dataset are removed. Set
`ACTIVITY_MAP_PREPARED_CACHE_DIR` to relocate this cache or
`ACTIVITY_MAP_DISABLE_PREPARED_CACHE=1` to disable it.

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

The pipeline creates or reuses `.venv`, installs dependencies, checks formatting,
linting, strict typing, dead code, complexity, installed dependencies, package
architecture, documentation, package builds, unit tests, coverage, and CLI/GUI
smoke runs. It also loads, prepares, indexes, and renders 1,000 synthetic tracks
with 300 points each, failing if the load-to-first-display time exceeds eight
seconds. Coverage must remain at or above 95%. The pipeline finishes with an
aligned per-gate summary that shows PASS or FAIL plus a one-line detail for each
gate (file counts, test totals, coverage percentage, built artifacts) and exits
non-zero if any gate fails.

The GUI is also covered by offscreen end-to-end tests. These tests launch the
real main window with fabricated Garmin-shaped activity files, drive the
directory selection workflow, verify incremental loading progress, exercise map
pan/zoom interaction, and check recovery after malformed synthetic input. To run
the focused GUI coverage check:

```bash
source .venv/bin/activate

QT_QPA_PLATFORM=offscreen ACTIVITY_MAP_DISABLE_TILES=1 \
  python -m pytest tests/test_gui_e2e.py tests/test_widgets.py \
  --cov=activity_map.widgets --cov-report=term-missing --cov-fail-under=0
```

Current result for that focused check: `10 passed`; `activity_map/widgets.py`
reports 95% coverage. The total shown by that scoped command is lower because
the project-wide coverage configuration still includes non-UI modules.

## Continuous Integration

`.github/workflows/local-pipeline.yml` runs the same `./localPipeline.sh` on
GitHub Actions for pushes to `master`, `main`, and `mpe/**`, for pull requests,
and on manual dispatch. The job runs on Python 3.14, the same version used for
local development, installs the Qt runtime libraries needed for
offscreen PyQt6, exports `QT_QPA_PLATFORM=offscreen` and
`ACTIVITY_MAP_DISABLE_TILES=1` so no OpenStreetMap tiles are requested from CI,
and uploads the built packages and the generated documentation as artifacts.
The Local Pipeline badge at the top of this file reflects that workflow on
`master`. Because CI runs the identical script, a green badge means the same
formatting, lint, typing, dead-code, complexity, architecture, docs, package
build, test, coverage, performance, and smoke gates that run locally passed. The
badge stays grey until the workflow has completed a run on `master`, and GitHub
caches badge images for a short while, so it can lag a minute behind a finished
run.

Before a major automated operation, create a verified checkpoint and confirm
the worktree is clean:

```bash
./localPipeline.sh
git commit
./scripts/agentPreflight.sh
```

The detailed incremental-change, rollback, and traceability rules are in
`documents/AGENTS.md`.

## Architecture Documentation

The C4-style architecture views live in `documents/architecture.md`. Build and validate the local documentation bundle with:

```bash
python scripts/build_docs.py
```

Generated documentation output is written to ignored `build/docs/`.

The detailed map runtime flow and the 2026-06-23 performance review are in
`documents/data_flow.md` and `documents/speed_improvements20260623.md`.
Reproduce the synthetic 1,000-track rendering benchmark with:

```bash
QT_QPA_PLATFORM=offscreen ACTIVITY_MAP_DISABLE_TILES=1 \
  python benchmarks/benchmark_map_render.py --tracks 1000
```

Measure synthetic file loading through the first offscreen display with:

```bash
QT_QPA_PLATFORM=offscreen ACTIVITY_MAP_DISABLE_TILES=1 \
  python benchmarks/benchmark_loading.py \
    --tracks 1000 \
    --points-per-track 300 \
    --samples 3
```

Use `--loader-workers` and `--prepare-workers` to compare concurrency settings,
`--use-prepared-cache` to report repeat-snapshot loading, or
`--max-load-to-display-ms` to turn the cold measurement into a regression gate.

## Privacy

Garmin activity exports can contain names, locations, timestamps, device IDs, and route data. Keep generated files under ignored paths such as `data/` or `exports/`, and check `git status --short` before committing.
