Below is a consolidated markdown document that can be given directly to an agentic software development system.

# Garmin Activity Exporter and Activity Map Renderer

## Master Development Specification

# Project Overview

This project consists of two major subsystems:

1. **Garmin Activity Exporter**

   * Responsible for downloading and managing Garmin activity data.

2. **Activity Map Renderer**

   * Responsible for loading, processing, analyzing, and rendering activity tracks on a map.

The objective is to produce a high-quality, maintainable, well-tested, production-grade application that can be extended by both human developers and agentic software development systems.

---

# General Engineering Requirements

The following requirements apply to all work packages.

## Quality Standards

* Follow clean architecture principles where practical.
* Minimize coupling between modules.
* Maximize testability.
* Prefer explicitness over hidden behavior.
* Use strong typing wherever supported by the language.
* Avoid duplicated logic.
* Keep public APIs stable and documented.

## Testing Requirements

All newly introduced functionality must include:

* Unit tests
* Regression tests where appropriate
* Failure-path tests
* Edge-case tests

Coverage should be measured and enforced.

## Documentation Requirements

All major modules should contain:

* High-level architecture documentation
* Public API documentation
* Usage examples where applicable

## Reliability Requirements

The application must:

* Fail gracefully
* Recover where possible
* Preserve user data
* Avoid data corruption
* Log actionable diagnostics

---

# WP1 — Robust Garmin Activity Export Pipeline

## Goal

Implement a reliable export pipeline for downloading Garmin activity data back to 2017 while respecting server limitations.

## Requirements

### Export Rate Limiting

Implement controlled request pacing.

Baseline target:

* 1 request per second
* 60 requests per minute
* 3,600 requests per hour

The implementation must allow configuration of the request rate.

### Retry and Backoff

Handle:

* HTTP 429
* HTTP 403
* HTTP 5xx
* Timeouts
* Network interruptions

Apply exponential backoff and retry logic.

### Resume Support

Persist export state.

Support:

* interrupted runs
* restart after crash
* restart after machine reboot

Avoid duplicate exports.

### Progress Tracking

Track:

* completed activities
* pending activities
* failures
* retries
* estimated completion time

### Acceptance Criteria

* Historical exports back to 2017 are supported.
* Long-running exports complete reliably.
* Exports can resume after interruption.
* Server throttling is handled gracefully.

---

# WP2 — GPS Validation and Track Rendering Corrections

## Goal

Remove rendering spikes and invalid geometry from displayed activity tracks.

## Requirements

### Coordinate Validation

Verify:

* latitude range
* longitude range
* timestamp validity

Confirm correct coordinate interpretation.

### Projection Validation

Verify conversion between:

* Garmin coordinate representation
* WGS84 coordinates
* OpenStreetMap map coordinates

### Segment Validation

For every segment:

Compute:

* distance
* time delta
* implied speed

### Outlier Detection

Implement configurable filtering.

Initial threshold:

* 30 km/h

Segments exceeding the threshold should be flagged.

### Rendering Validation

Verify:

* timestamp ordering
* duplicate timestamps
* missing timestamps
* invalid coordinates
* broken segments

### Acceptance Criteria

* Wild rendering spikes are removed.
* Corrupt segments are detected.
* Raw source data remains preserved.

---

# WP3 — Track Data Model and Rendering Optimization

## Goal

Improve rendering performance and scalability.

## Requirements

### Track Data Model

Store:

* activity ID
* GPS points
* timestamps
* altitude (if available)
* segment distance
* segment speed
* total distance
* duration
* bounding box

### Bounding Boxes

Compute:

* min latitude
* max latitude
* min longitude
* max longitude
* width
* height

### Speed Calculations

Compute per-segment speed using geodesic distance calculations.

### Zoom-Aware Rendering

When zoomed out:

* avoid drawing full geometry
* use simplified representations

### Simplified Geometry

Support:

* markers
* dots
* simplified polylines
* cached geometry

### Acceptance Criteria

* Large datasets remain interactive.
* Rendering scales efficiently.
* Detailed rendering remains available when zoomed in.

---

# WP4 — Local Quality Pipeline and Static Analysis

## Goal

Create a comprehensive local validation pipeline.

## Requirements

### Pipeline Script

Create a single entry-point script.

### Formatting Checks

Run formatter validation.

### Linting

Run all applicable linters.

### Static Analysis

Run available tools for:

* dead code
* cyclic dependencies
* type safety
* complexity analysis
* dependency analysis
* architecture validation

### Unit Tests

Execute all tests.

### Coverage

Generate coverage reports.

Enforce a minimum coverage threshold.

### Status Summary

Print a final summary showing:

* formatting
* linting
* static analysis
* tests
* coverage
* architecture checks

### Exit Codes

Return:

* 0 on success
* non-zero on failure

### Acceptance Criteria

* Pipeline can be executed locally.
* Failures are clearly reported.
* Quality gates are enforced.

---

# WP5 — Persistent User Settings

## Goal

Persist application settings across restarts.

## Requirements

### Settings Storage

Store settings in a structured configuration file.

Possible formats:

* JSON
* TOML
* YAML

### Persisted Properties

Include:

* last loaded track directory
* last run timestamp
* user-selected colors
* application preferences
* future configuration fields

### Startup Loading

Load settings automatically on startup.

### Runtime Updates

Persist changes automatically.

### Robustness

Handle:

* missing files
* invalid files
* corrupted files
* unknown fields
* version upgrades

### Recovery

Fallback to safe defaults when necessary.

### Acceptance Criteria

* Settings survive restarts.
* Corrupted files do not crash the application.
* Configuration is backward compatible.

---

# WP6 — Agentic Development Workflow and Commit Discipline

## Goal

Ensure safe, auditable, high-quality operation when agentic software development tools modify the codebase.

## Requirements

### Mandatory Commit Before Major Actions

Before any major automated operation, the agent must:

1. Verify repository status.
2. Commit current work.
3. Create a meaningful commit message.

Major actions include:

* cloud execution
* remote code generation
* external AI-assisted modifications
* repository-wide refactoring
* dependency upgrades
* architecture migrations

### Small Incremental Changes

Prefer:

* small commits
* focused commits
* reviewable commits

Avoid large unreviewable changes.

### Traceability

Every automated change should be traceable through commit history.

### Verification Before Commit

Before creating a commit:

Run:

* formatting
* linting
* static analysis
* tests

when practical.

### Recovery

Agent workflows must support:

* rollback
* bisecting
* incremental recovery

### Documentation

Record:

* work package being executed
* major decisions
* architectural changes

### Acceptance Criteria

* Every significant automated modification is committed.
* Commits are reviewable and traceable.
* Rollback is straightforward.
* Development history remains understandable.

---

# Final Success Criteria

The finished product should:

* Export Garmin activity data reliably.
* Render tracks accurately.
* Detect and suppress invalid GPS artifacts.
* Scale to large historical datasets.
* Preserve user preferences.
* Maintain a strong automated quality pipeline.
* Be safe for autonomous and semi-autonomous software agents.
* Be maintainable by future developers.
* Meet production-quality engineering standards.
