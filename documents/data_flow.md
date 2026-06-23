# Activity Map Data Flow and Performance Architecture

This document describes the current desktop map architecture as reviewed on
2026-06-23. It covers local JSON ingestion, render preparation, interaction,
painting, map tiles, threading, and the boundaries that determine performance.

## End-to-End Data Flow

```mermaid
flowchart LR
  U[User selects export directory]
  FS[(Garmin JSON files)]
  LD[MainWindow.load_path]
  L[loader.load_directory]
  P[JSON parsing and recursive mapping walk]
  V[Timestamp, distance, speed, and bounds validation]
  M[(ActivityTrack tuple)]
  PR[render.prepare_tracks]
  PG[Projected full geometry]
  SG[Ramer-Douglas-Peucker simplified geometry]
  MK[Mean-position marker]
  C[(MapCanvas render_tracks)]
  E[Mouse drag or wheel event]
  VP[Viewport pan or zoom update]
  PE[Qt paint event on GUI thread]
  Z{Zoom tier}
  T[Tile lookup and drawing]
  D[Track drawing]
  O[Labels, scale, attribution]
  S[Desktop surface]

  U --> LD
  FS --> L
  LD --> L
  L --> P --> V --> M
  M --> PR
  PR --> PG
  PR --> SG
  PR --> MK
  PG --> C
  SG --> C
  MK --> C
  E --> VP --> PE
  C --> PE
  PE --> T
  PE --> Z
  Z -->|broad| MK
  Z -->|intermediate| SG
  Z -->|deep| PG
  MK --> D
  SG --> D
  PG --> D
  T --> O
  D --> O
  O --> S
```

Loading and render preparation are synchronous. `MainWindow.load_path` calls
`load_directory`, then `MapCanvas.set_tracks`, on the GUI thread. The window
cannot process interaction or repaint events until both operations complete.

## Current Runtime Sequence

```mermaid
sequenceDiagram
  actor User
  participant Window as MainWindow / GUI thread
  participant Loader as activity_map.loader
  participant Render as activity_map.render
  participant Canvas as MapCanvas / GUI thread
  participant Tiles as tile worker pool
  participant Qt as QPainter

  User->>Window: Open directory
  Window->>Loader: load_directory(path)
  loop Every JSON file, sequentially
    Loader->>Loader: read, decode, recursively inspect
    Loader->>Loader: validate every adjacent GPS segment
  end
  Loader-->>Window: immutable ActivityTrack tuple
  Window->>Canvas: set_tracks(tracks)
  Canvas->>Render: prepare_tracks(tracks)
  loop Every retained track, sequentially
    Render->>Render: project points and split segments
    Render->>Render: recursively simplify each segment
    Render->>Render: calculate marker
  end
  Canvas->>Canvas: flatten all source points and fit viewport
  Canvas-->>Window: first repaint requested

  User->>Canvas: drag or wheel event
  Canvas->>Canvas: update immutable Viewport
  Canvas->>Qt: update() schedules paint
  Qt->>Canvas: paintEvent()
  Canvas->>Tiles: request missing tiles asynchronously
  Canvas->>Qt: draw backdrop and cached tiles
  loop Every render track
    Canvas->>Canvas: select geometry for zoom
    loop Every point in selected geometry
      Canvas->>Canvas: allocate ScreenPoint from world_to_screen
    end
    loop Every adjacent point pair
      Canvas->>Qt: drawLine()
    end
  end
  Canvas->>Qt: draw labels, scale, attribution
  Qt-->>User: completed frame
```

The tile network and disk work is the only current parallel work. Track
loading, projection, simplification, culling, screen transformation, and
painting all execute serially on the GUI thread.

## Module and Thread Boundaries

```mermaid
flowchart TB
  subgraph GUI["GUI thread"]
    APP[activity_map.app]
    W[activity_map.widgets.MainWindow]
    C[activity_map.widgets.MapCanvas]
    L[activity_map.loader]
    R[activity_map.render]
    G[activity_map.geo]
    Q[Qt raster paint engine]
  end

  subgraph WORKERS["ThreadPoolExecutor: four tile workers"]
    TC[activity_map.tiles.TileCache.fetch_tile]
  end

  subgraph STORAGE["Local storage"]
    J[(Activity JSON)]
    TI[(OSM tile cache)]
    ST[(Settings JSON)]
  end

  APP --> W
  W --> L
  J --> L
  W --> C
  C --> R
  L --> G
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
- `S` be total selected points for the current zoom tier;
- `V` be tracks intersecting the current viewport.

The current major costs are:

| Phase | Current complexity | Thread | Important behavior |
|---|---:|---|---|
| Recursive file discovery and JSON parsing | `O(F + payload size)` | GUI | Sequential; blocks the window |
| Segment validation and full projection | `O(P)` | GUI | Haversine distance is calculated during loading and again during render preparation |
| Simplification | Typical `O(P log P)`, worst `O(P²)` | GUI | Recursive Python implementation and tuple slicing |
| Fit to tracks | `O(P)` | GUI | Re-flattens all source points despite per-track bounds already existing |
| Broad/intermediate paint | `O(T + S)` | GUI | All tracks are visited even if off-screen |
| Detailed paint | `O(T + S)` | GUI | `S` can equal `P`; one Python transform and nearly one Qt call per point/edge |
| Labels | `O(T + P)` when enabled | GUI | `track_label_anchor` scans full detailed geometry every frame |
| Tile fetch | Network/disk dependent | workers | Already asynchronous |

## Bottleneck Location

The dominant interaction cost is `MapCanvas._draw_tracks`, specifically:

1. transforming every selected projected point with
   `Viewport.world_to_screen`;
2. allocating a Python `ScreenPoint` per transformed point;
3. allocating `QPointF` objects;
4. issuing one `QPainter.drawLine` call per adjacent point pair;
5. repeating all work for every pan or zoom frame;
6. drawing every track without viewport or segment culling.

At broad and intermediate zoom, the existing marker/simplified caches are
effective. At deep zoom the renderer abruptly switches to full geometry, so a
large dataset can jump from thousands to hundreds of thousands or millions of
draw operations. The threshold is based only on global zoom, not projected
pixel error or visible density.

Map tilt is not implemented. Adding it to the current CPU raster path would
require another per-point transform and would worsen the same bottleneck.
Tilt should only be introduced after the renderer has retained geometry,
culling, and preferably GPU-backed transforms.

## Recent Commit Effects

The latest commits reviewed were `9ff3430`, `d9fca57`, `785160e`, `303032f`,
`97e5a1d`, `36718d1`, `a291e8a`, `2c2accd`, and `93be602`.

- `2c2accd` added cached full, simplified, and marker geometry. This materially
  improves broad and intermediate zoom, but deep zoom still submits full
  geometry every frame.
- `93be602` added timestamp/speed validation and invalid-segment splitting. It
  improves correctness but adds an `O(P)` loading pass; render preparation then
  performs another geodesic-distance pass to split large jumps.
- `36718d1` added settings persistence. It is not a rendering bottleneck,
  although slider changes synchronously write settings and request repaints.
- `d9fca57` synchronized controls and legend state. It has no material map
  performance effect.
- `9ff3430` raised coverage and added branch-focused GUI tests. It does not add
  a sustained frame-time or interaction performance gate.
- `a291e8a` strengthened static and architecture checks but currently does not
  benchmark rendering regressions.

The architecture remains clean at the package-dependency level, but
`activity_map.widgets` owns data loading orchestration, tile lifecycle,
interaction policy, render traversal, and low-level painting. That
concentration makes it difficult to profile, parallelize, or replace the
renderer independently.
