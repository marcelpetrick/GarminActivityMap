# PyQt Activity Map Plan

## Goal

Build a local PyQt desktop application that loads ignored Garmin JSON exports from a selected directory, extracts GPS tracks, and renders them on an interactive world map. The user must be able to pan, zoom, and visually inspect activity density without exposing private activity data to the repository.

## Safety Principles

- Never commit exported Garmin files, route payloads, generated caches, screenshots with real tracks, credentials, tokens, or local config.
- Use synthetic activity fixtures for tests.
- Treat all real coordinates as private.
- Handle malformed, empty, or partial export files by skipping them and surfacing a readable summary.
- Keep the app offline-first; no map tile downloads are required for the first runnable version.

## Architecture

- `garmin_export`: existing Garmin download/export package.
- `activity_map`: new GUI and map-processing package.
- `activity_map.loader`: read activity JSON files, extract track points, collect load warnings.
- `activity_map.geo`: coordinate validation, bounds, Web Mercator projection, viewport transforms.
- `activity_map.heat`: grid/bin aggregation for activity density.
- `activity_map.widgets`: PyQt widgets for directory selection, map canvas, status summary, and controls.
- `python -m activity_map`: runnable GUI entry point.

## UI Direction

- Build a modern PyQt interface that feels like a polished desktop analysis tool, not a script wrapper.
- Use a restrained dark map workspace with high-contrast cyan, amber, and magenta route/heat accents.
- Keep controls obvious and close to the task: directory picker, reload, reset view, track opacity, heat intensity, and activity count summary.
- Use a left-side control rail for filters and load status, with the map as the dominant full-window surface.
- Use clear visual hierarchy: compact title/status area, large interactive map, subtle grid/coastline context, and small badges for loaded files, tracks, points, and warnings.
- Provide responsive feedback while loading large directories: progress text, disabled reload while busy, and a clear skipped-file warning area.
- Make pan and zoom feel direct: drag to pan, wheel to zoom around cursor, double-click or toolbar action to reset view.
- Use anti-aliased track rendering, alpha blending, and heat intensity normalization so dense areas are visually appealing without hiding individual tracks.
- Avoid real map tile downloads for the first version; draw an offline world backdrop and projection grid so private tracks are never sent to a remote map provider.
- Keep all colors, spacing, and visual constants centralized so the UI can be refined without touching parsing or map math.

## Work Items

1. Planning and quality gates [done]
   - Add this plan.
   - Update repository guidance for GUI work, privacy, tests, and per-step commits.
   - Add coverage enforcement to the local pipeline.
   - Run `./localPipeline.sh` and commit after it passes.

2. Data model and parser [done]
   - Add typed models for `TrackPoint`, `ActivityTrack`, and `LoadReport`.
   - Parse exported JSON structures from `summary`, `activity`, and `details`.
   - Support likely Garmin detail shapes such as `geoPolylineDTO.polyline`, `activityDetailMetrics`, and coordinate-like metric records.
   - Skip invalid coordinates and report skipped files.
   - Unit test valid files, empty files, malformed JSON, missing tracks, and mixed valid/invalid points.

3. Map math and heat aggregation [done]
   - Implement coordinate bounds, world wrapping rules, Web Mercator projection, viewport transforms, and zoom scaling.
   - Implement a deterministic heat grid from projected points.
   - Unit test projection edge cases, bounds, pan/zoom transforms, and aggregation.

4. Minimal runnable PyQt app [done]
   - Add exact pinned PyQt dependency after checking the latest stable release.
   - Add `python -m activity_map`.
   - Implement directory picker, file load summary, interactive map canvas, pan, wheel zoom, and reset view.
   - Render a simple offline world background, tracks, and heat overlay.
   - Add GUI smoke tests that instantiate widgets in offscreen mode.

5. Modern UI polish [done]
   - Implement the dark analysis workspace, left control rail, compact toolbar, and status badges.
   - Add opacity and heat controls that update rendering without reloading files.
   - Add loading and warning states that stay readable on small and large windows.
   - Add visual regression smoke checks that render the map widget offscreen and verify it is non-empty.
   - Profile rendering with synthetic large-track fixtures and keep interaction responsive.

6. Pipeline hardening [done]
   - Extend `localPipeline.sh` to include GUI smoke tests and coverage for `activity_map`.
   - Keep linting and static analysis strict for both packages.
   - Ensure the run smoke check exercises both `python -m garmin_export --help` and a non-interactive app import/entrypoint check.

7. Documentation [done]
   - Update README with GUI run instructions, privacy notes, supported Garmin export shapes, and troubleshooting.
   - Document expected local directory structure under ignored `data/`.
   - Maintain C4-style architecture views and validate them in the local pipeline.

8. Manual verification [done]
   - Run the app against the local private export directory.
   - Verify pan, zoom, track rendering, heat rendering, malformed-file handling, and no tracked private files.
   - Do not commit screenshots or generated map outputs from private data.
   - Verified with the ignored local export directory using count-only parser output and an offscreen GUI smoke load.

9. OpenStreetMap base layer [done]
   - Add OpenStreetMap tile rendering below heat and tracks.
   - Add an in-app legend explaining track colors and pink/red heat-density dots.
   - Load newly visible map tiles after pan and zoom.
   - Cache downloaded tiles under ignored local storage for faster repeat loads.
   - Add a base-layer opacity control so the map can sit quietly under the activity data.
   - Keep tests and pipeline deterministic by disabling live tile downloads during automated checks.
   - Document the map layer, cache location, and offline fallback.

10. Deep map zoom [done]
   - Raise the internal viewport zoom ceiling so users can inspect tracks at much higher detail.
   - Keep provider tile requests capped to the supported tile zoom and scale cached tiles beyond that point.
   - Add regression tests for deep viewport zoom and tile-request capping.

## Done Criteria

- `./localPipeline.sh` passes from a clean local environment.
- Unit tests and coverage are enforced in the pipeline.
- The GUI runs with `python -m activity_map`.
- The app can load a directory of Garmin JSON files and render tracks plus heat density.
- The map can render cached OpenStreetMap tiles as a base layer with tracks and heat painted on top.
- Private Garmin data remains ignored and unstaged.
- Each implementation step lands as a separate conventional commit with a patch version bump.
