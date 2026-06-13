# Heatmap

The pink/red dots on the map are heat-density markers. They are not extra activities and they are not start or finish markers.

## Input Data

The heatmap uses the same GPS track points as the visible activity lines. These points are extracted from local Garmin JSON files, usually from:

- `geoPolylineDTO.polyline`
- `activityDetailMetrics` latitude and longitude metrics
- coordinate-like records such as `positionLat` and `positionLong`

The app does not use private Garmin data from anywhere else for the heatmap. It does not send coordinates to a remote heatmap service.

## How It Is Calculated

1. GPS coordinates are projected into Web Mercator map space.
2. The projected map is divided into fixed-size grid cells.
3. Each GPS point increments the count for its grid cell.
4. Cells with more GPS points get stronger red/pink opacity.

This means a red dot appears where many recorded GPS points fall into the same small map area. A larger or stronger-looking dot usually means repeated activity in that area, slower movement through that area, or many activities passing through the same grid cell.

## Why Only A Few Big Dots Can Appear

The heatmap is point-density based. A place where you pause, start, stop, or repeatedly pass through can collect many GPS samples and become visually prominent. This can happen even when the track lines themselves look thin.

The heatmap is useful for spotting activity concentration, but it is not a precise measurement tool. Use the track lines and the distance scale for route shape and approximate distance.
