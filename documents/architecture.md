# Architecture

This document describes the project using C4-style views. It focuses on the software boundaries, runtime containers, and core components needed to export private Garmin activity data and visualize local tracks.

## Level 1: System Context

```mermaid
flowchart LR
  user[Personal user]
  garmin[Garmin Connect]
  app[Garmin Visualize All Activities]
  disk[(Local ignored data directory)]

  user -->|starts export and enters password manually| app
  app -->|authenticated activity reads| garmin
  app -->|writes JSON exports| disk
  user -->|opens local export directory| app
  app -->|reads JSON tracks| disk
```

The system is a local desktop and command-line application. It authenticates only when exporting, stores activity JSON under ignored local paths, and visualizes existing local files without sending track coordinates to map providers.

## Level 2: Container View

```mermaid
flowchart TB
  cli[Exporter CLI container]
  gui[PyQt desktop GUI container]
  docs[Documentation build container]
  tests[Quality pipeline container]
  local[(Ignored local storage)]

  cli -->|activity summaries and details| local
  gui -->|recursive JSON reads| local
  docs -->|validates and bundles markdown| local_docs[(Ignored build/docs output)]
  tests --> cli
  tests --> gui
  tests --> docs
```

- Exporter CLI: `garmin_export`, responsible for Garmin login, activity pagination, detail retrieval, and JSON writing.
- PyQt desktop GUI: `activity_map`, responsible for loading exports, parsing GPS tracks, projecting coordinates, aggregating heat, and rendering the interactive map.
- Documentation build: `scripts/build_docs.py`, responsible for validating required C4 sections and producing a local documentation bundle.
- Quality pipeline: `localPipeline.sh`, responsible for bootstrap, linting, static analysis, docs build, package build, tests, and smoke runs.

## Level 3: Component View

```mermaid
flowchart LR
  loader[activity_map.loader]
  models[activity_map.models]
  geo[activity_map.geo]
  heat[activity_map.heat]
  render[activity_map.render]
  widgets[activity_map.widgets]
  app[activity_map.app]

  app --> widgets
  widgets --> loader
  loader --> models
  widgets --> geo
  widgets --> heat
  widgets --> render
  render --> geo
  heat --> models
```

- `activity_map.loader` recursively reads Garmin JSON files and extracts usable GPS tracks while collecting warnings for malformed or coordinate-free files.
- `activity_map.geo` owns coordinate bounds, Web Mercator projection, viewport transforms, pan, zoom, and fit behavior.
- `activity_map.heat` converts projected points into deterministic density cells.
- `activity_map.render` prepares cached render data so painting can stay responsive on larger exports.
- `activity_map.widgets` owns the PyQt window, controls, canvas drawing, and user interaction.
- `activity_map.app` provides `python -m activity_map` and the non-interactive smoke entry point.

## Level 4: Code View

The code-level design keeps private-data handling and UI rendering separated:

- Export credentials are accepted at runtime by `garmin_export.cli` and passwords are never read from files or environment variables.
- Raw Garmin payloads stay under ignored local directories such as `data/` or `exports/`.
- Parser, projection, heat, and render-cache logic use typed pure Python objects so they can be unit tested without private data.
- PyQt widgets consume already parsed models and render caches, keeping GUI smoke tests practical in offscreen mode.
- Tests use synthetic GPS fixtures only.

## Runtime Data Flow

```mermaid
sequenceDiagram
  participant U as Personal user
  participant E as Exporter CLI
  participant G as Garmin Connect
  participant D as Ignored local data
  participant M as PyQt map app

  U->>E: Start export and type password
  E->>G: Authenticate and request activities
  G-->>E: Activity summaries and detail payloads
  E->>D: Write JSON files and manifest
  U->>M: Open ignored export directory
  M->>D: Load JSON files
  M->>M: Parse, project, aggregate heat, cache render data
  M-->>U: Interactive offline map
```

## Operational Constraints

- Generated docs, package builds, test caches, Garmin exports, and GUI output remain ignored.
- Documentation must build with `python scripts/build_docs.py`.
- The full local pipeline must pass before each commit.
- Any new user-facing workflow should include synthetic tests or an offscreen smoke check where practical.
