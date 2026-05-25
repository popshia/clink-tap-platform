# OcSort Tracking Parameters

Parameters are split between `BaseTracker` (shared across all boxmot trackers) and `OcSort`-specific ones.

## BaseTracker Parameters

| Param | Current | Effect |
|---|---|---|
| `det_thresh` | `0.3` | Min confidence to accept a detection |
| `max_age` | `30` | Frames a track survives without a match before being dropped |
| `min_hits` | `3` | Frames a track must be seen before it's confirmed/output |
| `iou_threshold` | `0.3` | Min IoU overlap to associate detection → track |
| `per_class` | `True` | Prevents cross-class ID merging |
| `max_obs` | `50` | Max observations stored per track (Kalman history) |
| `asso_func` | `"iou"` | Association metric — options: `"iou"`, `"giou"`, `"ciou"`, `"diou"`, `"hmiou"` |

## OcSort-Specific Parameters

| Param | Default | Effect |
|---|---|---|
| `min_conf` | `0.1` | Secondary confidence gate inside OcSort's re-association step |
| `delta_t` | `3` | Lookback window (frames) for velocity estimation |
| `inertia` | `0.2` | How much the previous velocity direction is trusted (0=none, 1=full) |
| `use_byte` | `False` | Enable two-stage ByteTrack-style matching (uses low-conf dets for recovery) |
| `Q_xy_scaling` | `0.01` | Kalman process noise for position |
| `Q_s_scaling` | `0.0001` | Kalman process noise for scale |

## Common Tuning Scenarios

| Symptom | Fix |
|---|---|
| IDs switching too often | Increase `inertia`, lower `iou_threshold` |
| Short-lived objects getting dropped | Lower `min_hits` to 1–2, raise `max_age` |
| Ghost tracks lingering | Lower `max_age` |
| Missing detections mid-track | Enable `use_byte=True` to re-link via low-confidence detections |
| Fast-moving objects losing track | Raise `delta_t` for longer velocity estimation history |
