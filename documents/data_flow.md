# Activity Map Data Flow and Performance Architecture

This document describes the desktop map architecture, first reviewed on
2026-06-23 and updated for the state described under
[Status as of 2026-08-14](#status-as-of-2026-08-14). The measured results of
each performance phase are in
[speed_improvements20260623.md](speed_improvements20260623.md), and the module
overview is in [architecture.md](architecture.md). It covers local JSON ingestion, render preparation, interaction,
painting, map tiles, threading, and the boundaries that determine performance.

## End-to-End Data Flow

```mermaid
flowchart LR
  U[User selects export directory]
  FS[(Garmin JSON files)]
  LD[MainWindow.load_path]
  LP[loading.load_and_prepare_directory]
  PC[(Prepared snapshot cache)]
  L[loader.load_directory_parallel]
  P[JSON parsing and recursive mapping walk]
  V[Timestamp, distance, speed, and bounds validation]
  M[(ActivityTrack batches of 50)]
  PR[render.prepare_tracks_parallel]
  LOD[Projected multi-level LOD geometry]
  MK[Mean-position marker]
  C[(MapCanvas render_tracks)]
  E[Mouse drag or wheel event]
  VP[Viewport pan or zoom update]
  PE[Qt paint event on GUI thread]
  Z{Zoom above MARKER_MAX_ZOOM?}
  SL[lod.select_lod under a point budget]
  T[Tile lookup and drawing]
  D[Track drawing]
  O[Labels, scale, attribution]
  S[Desktop surface]

  U --> LD --> LP
  LP -->|fingerprint matches| PC
  PC --> C
  LP -->|cache miss| L
  FS --> L
  L --> P --> V --> M
  M --> PR
  PR --> LOD
  PR --> MK
  PR -->|after the last batch| PC
  LOD --> C
  MK --> C
  E --> VP --> PE
  C --> PE
  PE --> T
  PE --> Z
  Z -->|no| MK
  Z -->|yes| SL --> LOD
  MK --> D
  LOD --> D
  T --> O
  D --> O
  O --> S
```

Loading and pure render preparation run asynchronously through a single
background load executor. The GUI thread immediately displays loading state,
continues processing input and paint events, and accepts the immutable
`PreparedLoad` result through a queued Qt signal. Retained `QPainterPath`
creation remains on the GUI thread but is deferred until a prepared level is
first painted.

## Current Runtime Sequence

```mermaid
sequenceDiagram
  actor User
  participant Window as MainWindow / GUI thread
  participant Worker as Background load executor
  participant Loader as activity_map.loader
  participant Cache as prepared snapshot cache
  participant Render as activity_map.render
  participant Canvas as MapCanvas / GUI thread
  participant Tiles as tile worker pool
  participant Qt as QPainter

  User->>Window: Open directory
  Window->>Worker: submit load_and_prepare_directory(path)
  Worker->>Cache: look up source fingerprint
  alt Valid prepared snapshot exists
    Cache-->>Worker: parsed tracks and prepared geometry
  else Cache miss or source files changed
    Worker->>Loader: load_directory_parallel(path, progress)
    loop Every batch of 50 tracks
      Loader->>Loader: read, decode, inspect structured containers
      Loader->>Loader: validate every adjacent GPS segment
      Loader-->>Worker: progress(report, track batch)
      Worker->>Render: prepare_tracks_parallel(batch)
      Render-->>Worker: projected LOD geometry, markers, bounds
      Worker-->>Window: queued PreparedLoad batch signal
      Window->>Canvas: append prepared batch and extend spatial index
    end
    Worker->>Cache: atomically store versioned snapshot
  end
  Worker-->>Window: queued final PreparedLoad signal
  Window->>Canvas: set_prepared_tracks(tracks, render_tracks)
  Canvas->>Canvas: install lazy path holders and fit viewport
  Canvas-->>Window: first repaint requested

  User->>Canvas: drag or wheel event
  Canvas->>Canvas: capture current full-quality raster once
  Canvas->>Canvas: update immutable Viewport
  Canvas->>Qt: update() schedules paint
  Qt->>Canvas: paintEvent()
  alt Gesture is active
    Canvas->>Qt: affine-transform cached raster
  else Gesture settled
    Canvas->>Tiles: request missing tiles asynchronously
    Canvas->>Canvas: query spatial index
    Canvas->>Canvas: select screen-space LOD and point budget
    Canvas->>Canvas: materialize uncached visible paths for selected LOD
    Canvas->>Qt: draw backdrop and cached tiles
    loop Every visible retained track
      Canvas->>Qt: draw retained QPainterPath
    end
    Canvas->>Qt: draw labels, scale, attribution
  end
  Qt-->>User: completed frame
```

Track loading and pure render preparation now execute away from the GUI thread.
Choosing a different directory signals the active load to stop between files or
preparation batches, allowing its replacement to begin on the single load
executor without waiting for the entire superseded dataset.
Repeat loads first validate a lightweight relative-path/size/mtime fingerprint
and reuse a versioned, compressed binary prepared snapshot when it matches.
Corrupt, missing, or stale cache entries fall back to the ordinary loader
without failing the GUI.
The loader and process-preparation APIs support multiple workers, but measured
defaults remain one worker because four threads did not improve local SSD JSON
loading and four processes were slower after serialization. Tile network and
disk work continues in an independent two-worker pool whose downloads share a
minimum interval, so the provider sees a paced request stream instead of a
burst.

## Module and Thread Boundaries

```mermaid
flowchart TB
  subgraph GUI["GUI thread"]
    APP[activity_map.app]
    W[activity_map.widgets.MainWindow]
    C[activity_map.widgets.MapCanvas]
    R[activity_map.render]
    G[activity_map.geo]
    Q[Qt raster paint engine]
  end

  subgraph WORKERS["ThreadPoolExecutor: two paced tile workers"]
    TC[activity_map.tiles.TileCache.fetch_tile]
  end

  subgraph LOAD["Background load executor"]
    LC[activity_map.loading]
    LP[activity_map.loader and pure render preparation]
    PCM[activity_map.prepared_cache]
  end

  subgraph STORAGE["Local storage"]
    J[(Activity JSON)]
    TI[(OSM tile cache)]
    ST[(Settings JSON)]
    PS[(Prepared snapshots)]
  end

  APP --> W
  W --> LC
  LC --> LP
  LC --> PCM
  PCM --> PS
  J --> LP
  W --> C
  C --> R
  LP --> G
  R --> G
  C --> G
  C --> Q
  C --> TC
  TC --> TI
  W --> ST
```

Qt requires `QPixmap` creation and widget painting to remain on the GUI thread.
Pure data work can move off-thread: file parsing, validation, projection,
simplification, bounds, spatial indexing, and construction of immutable
render-command data. Worker results should be delivered back through queued Qt
signals and swapped atomically between frames.

## Cost Model

Let:

- `F` be JSON files;
- `T` be retained tracks;
- `P` be total GPS points;
- `S` be total selected points for the current level of detail;
- `V` be tracks intersecting the current viewport.

The current major costs are:

| Phase | Current complexity | Thread | Important behavior |
|---|---:|---|---|
| Recursive file discovery and JSON parsing | `O(F + payload size)` | load worker | Sequential by measured default; does not block the window |
| Segment validation and full projection | `O(P)` | load worker | Loader-computed segment distances are reused during render preparation |
| Simplification | Typical `O(P log P)`, worst `O(P²)` | load worker | Multiple retained levels; process mode remains optional |
| Fit to tracks | `O(T)` | GUI | Combines cached projected track bounds |
| Broad/intermediate paint | `O(V + S)` | GUI | Spatial query, adaptive LOD, and retained path calls |
| Detailed paint | `O(V + S)` | GUI | Visible geometry only; selected points are budgeted |
| Labels | `O(V)` when enabled | GUI | Cached label anchors for visible tracks |
| Tile fetch | Network/disk dependent | workers | Already asynchronous |

## Historical Bottleneck (before 2026-06-23)

Before the performance work, the dominant interaction cost was
`MapCanvas._draw_tracks`, specifically:

1. transforming every selected projected point with
   `Viewport.world_to_screen`;
2. allocating a Python `ScreenPoint` per transformed point;
3. allocating `QPointF` objects;
4. issuing one `QPainter.drawLine` call per adjacent point pair;
5. repeating all work for every pan or zoom frame;
6. drawing every track without viewport or segment culling.

At broad and intermediate zoom, the marker/simplified caches were effective. At
deep zoom the renderer abruptly switched to full geometry, so a large dataset
could jump from thousands to hundreds of thousands or millions of draw
operations. The threshold was based only on global zoom, not projected pixel
error or visible density.

Today `_draw_tracks` issues one `drawPath` per visible retained path at the
level chosen by `select_lod`, after a spatial-index viewport query; only the
scale bar still uses `drawLine`.

Map tilt is not implemented. It should only be introduced together with
GPU-backed transforms, as decided in the speed improvement review.

## Status as of 2026-08-14

The commit-by-commit notes that used to live here described the state before
the performance work packages landed and are superseded by
[speed_improvements20260623.md](speed_improvements20260623.md), which records the measured result of each
phase. The current state of this pipeline is:

- retained `QPainterPath` levels, viewport culling through a uniform grid
  index, screen-space level-of-detail selection under a vertex budget, and a
  gesture raster cache are all in place; refined 2,000-track frames measure a
  few milliseconds on the reference machine;
- loading and pure render preparation run on a background executor and publish
  prepared batches of 50 tracks, so tracks appear while the archive is still
  being read;
- parsed tracks and prepared geometry are reused from a versioned disk cache
  keyed by the source fingerprint and the geometry parameters that produced the
  snapshot;
- retained Qt paths are materialised lazily, per level, the first time a level
  is painted;
- the spatial index is extended in place as batches arrive rather than rebuilt
  per batch, and each frame performs exactly one viewport query that both the
  track and label passes consume;
- `localPipeline.sh` gates load-to-first-display for 1,000 synthetic tracks at
  eight seconds, and the same script runs in GitHub Actions.

The architecture remains clean at the package-dependency level, but
`activity_map.widgets` still owns data loading orchestration, tile lifecycle,
interaction policy, render traversal, and low-level painting. That
concentration remains the main obstacle to profiling, parallelizing, or
replacing the renderer independently, and is the natural next work package if
the renderer has to change again.
