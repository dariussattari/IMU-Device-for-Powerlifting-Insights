# `src/bar_path/` — single-IMU bar-path reconstruction

Reconstructs per-rep 3-D bar path from the barbell-mounted IMU's
accel + gyro stream. Exports a FastAPI router that plugs into the
main branch's API, and a CLI for offline use.

## What this module produces

For each rep detected by the existing sign-change rep counter
(`src/rep_counting/sign_change_rep_counter.py`), one `BarPathRep`:

```
num          : 1-indexed rep number
start_s      : absolute session time at rep start (top of lift)
chest_s      : absolute time at chest turnaround
lockout_s    : absolute time at concentric lockout
end_s        : absolute time at rep end
duration_s   : rep window duration

t_s  x_m  y_m  z_m  : fixed-length (120) arrays; position in metres
                      relative to the rep start, at 120 equally-spaced
                      resampled times across the rep window.
chest_idx    : index into t_s/x_m/… at the chest turnaround
lockout_idx  : index into t_s/x_m/… at the concentric lockout

rom_m        : vertical range of motion (m)
peak_x_dev_m : max forward/back deviation from chest (m)
peak_y_dev_m : max lateral deviation from chest (m)
```

Coordinates are in a world frame fixed at the pre-lift calibration:

* `z_m` is vertical (up positive).
* `x_m` is the bar's forward/back direction at time zero (pseudo-
  forward — yaw is not observable with a single 6-DoF IMU, so this
  axis is only meaningful *within* a session).
* `y_m` is lateral (small magnitude on bench).

## Algorithm (fool-proof-ness comes from bounding drift)

The single-IMU bar-path problem is: a 6-DoF IMU lets you estimate
bar tilt and linear acceleration, but double-integrating acceleration
turns bias into quadratic drift. Over a long set that drift is
catastrophic. The fix is to bound the integration to short windows
where both endpoints are known to be stationary, then subtract the
linear ramp that joins them.

Pipeline:

1. **Filter** raw accel/gyro with a 15 Hz zero-phase Butterworth.
2. **Orientation** is fitted once from the pre-lift calibration window
   (first 1 s, bar at rest on the rack). Gravity vector in body
   coordinates → a body-to-world rotation that places +Z up. Yaw is
   left arbitrary (no magnetometer). This static rotation is held for
   the whole session; gyro integration across a set introduces more
   drift than it corrects (one bad unrack is enough to invert
   world-Z).
3. **World-frame linear acceleration** = `R · a_body − [0, 0, g]`.
   Residual calibration bias is subtracted from each axis.
4. **Rep detection** reuses the project's existing
   `sign_change_rep_counter.build_reps` + filters. Every rep comes
   with `chest_idx` (start of concentric) and `lockout_idx` (end of
   concentric).
5. **Per-rep integration** runs two *separate* sub-windows, each with
   `v ≈ 0` at both endpoints:
   * **Concentric** `[chest_idx → lockout_idx]` — always used.
   * **Eccentric** `[previous vy zero-crossing → chest_idx]` — used
     only if its duration (0.25–1.2 s) and integrated ROM
     (≈ concentric ROM within a factor of 2) pass sanity checks.
     Otherwise we fall back to mirroring the concentric, which gives
     a consistent, drift-free ROM estimate.
6. Each sub-window is integrated twice (trapezoidal) with linear
   endpoint anchoring applied to *both* velocity and position on
   every axis — the standard trick that keeps drift bounded inside
   one rep.
7. Position traces are resampled to 120 points for a consistent
   frontend payload.

What we deliberately don't do (and why):

* **No full AHRS across the session.** A Mahony/Madgwick filter with
  no magnetometer and a single loud unrack event was observed to
  flip world-Z by 180° on real data. Calibration-only orientation is
  strictly safer for the bench-press use case.
* **No long integration windows.** Concentric alone is ≤ ~1.2 s; even
  the eccentric + concentric combo stays under 2.5 s. Bias integrates
  as `½ b t²`, so halving the window cuts drift by 4×.
* **No absolute position claims.** This module reports *relative*
  per-rep displacement, not where the bar is in the gym. That matches
  what a single IMU can actually support (the guideline doc calls
  this out explicitly).

## Local usage

```bash
# From the repo root, with deps installed:
python -m src.bar_path data_collection/session_20260409_175030.csv
python -m src.bar_path data_collection/session_20260409_175030.csv --out path.json
```

## API integration (merge with `main`)

`src/bar_path/routes.py` exposes a `router` that mounts at
`/api/sessions/{session_id}/bar-path`. It uses the same
`SessionStore` from `src/api/storage.py` that `analyze` and `one-rm`
use, so no duplicate upload flow is needed.

After merging this branch into `main`, add **two lines** to
`src/api/app.py`:

```python
from ..bar_path.routes import router as bar_path_router      # add
...
app.include_router(sessions.router)
app.include_router(analyze.router)
app.include_router(one_rm.router)
app.include_router(bar_path_router)                          # add
```

That's it on the backend — no changes to existing routes.

## Frontend integration (merge with `frontend`)

The frontend currently shows a schematic SVG placeholder for bar path
(`frontend/src/pages/AnalysisTab.tsx`, chip label `"schematic"`). To
swap in real data, add these in the `frontend` branch:

`frontend/src/api/types.ts`:

```ts
export interface BarPathRep {
  num: number
  start_s: number
  chest_s: number
  lockout_s: number
  end_s: number
  duration_s: number
  t_s: number[]
  x_m: number[]
  y_m: number[]
  z_m: number[]
  chest_idx: number
  lockout_idx: number
  rom_m: number
  peak_x_dev_m: number
  peak_y_dev_m: number
}

export interface BarPathResponse {
  session_id: string
  fs_hz: number
  duration_s: number
  n_reps: number
  reps: BarPathRep[]
  notes: string
}
```

`frontend/src/api/client.ts`:

```ts
export async function getBarPath(session_id: string): Promise<BarPathResponse> {
  const res = await fetch(`/api/sessions/${session_id}/bar-path`, {
    method: "POST",
  })
  return jsonOrThrow<BarPathResponse>(res)
}
```

In `AnalysisTab.tsx`, replace the decorative `<path d={…}>` elements
in the `.barpath` panel with per-rep paths built from
`rep.x_m` / `rep.z_m`. `z_m` is vertical (Y in the SVG), `x_m` is
forward/back (X in the SVG). Suggested mapping for the existing
520×360 viewBox (auto-scaling to each session's max |x| / rom):

```ts
const S = 140            // cm per SVG unit scaling factor (tune)
const cx = 260           // x-origin (center of SVG)
const cy = 180           // y-origin (mid-height)
const svgPath = rep.x_m
  .map((x, i) => {
    const zcm = rep.z_m[i] * 100
    const xcm = x * 100
    const X = cx + xcm * 2
    const Y = cy - zcm * 2
    return `${i === 0 ? "M" : "L"} ${X.toFixed(1)},${Y.toFixed(1)}`
  })
  .join(" ")
```

…and drop the `schematic` chip and its tooltip. The rest of the
rendering (grid lines, lockout/chest markers at `chest_idx` and
`lockout_idx`) stays the same.
