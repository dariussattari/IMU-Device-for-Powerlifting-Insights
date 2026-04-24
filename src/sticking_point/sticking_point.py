"""
Sticking-point detector — per-rep kinematic extraction.

"Sticking point" is the region of a concentric lift where the bar slows to
its mechanical/physiological minimum between the initial drive and
lockout. It lives at the first meaningful velocity *minimum* after peak
concentric velocity (PCV). For bench press it typically sits ~30–60% of
the concentric duration and deepens monotonically with load.

This module re-uses the velocity pipeline in src/velocity/velocity_metrics.py
(Method B = per-rep endpoint detrend, the default used for the 8-session
figure) and adds per-rep sticking-point kinematics:

    SP_t       time of sticking point (s)
    SP_v       velocity at sticking point (m/s)
    SP_frac    position in concentric, (SP_t − chest_t) / CD   ∈ (0, 1)
    SP_depth   PCV − SP_v      (m/s, ≥ 0)   "valley depth"
    SP_rel     SP_depth / PCV  (unitless)   "valley depth relative to drive"
    post_amp   max(vy) after SP, minus SP_v  ≥ 0   "post-sticking resurgence"
               — a real sticking point requires both a drop after PCV AND
               a partial recovery before lockout, otherwise the signal is
               just monotonically decaying and there is no distinct
               valley.

A rep only gets a sticking-point label when
    SP_depth  >= SP_DEPTH_MIN  (default 0.08 m/s),
    post_amp  >= POST_AMP_MIN  (default 0.03 m/s),
    SP_frac   ∈ [SP_FRAC_MIN, SP_FRAC_MAX]  (default 0.10–0.90)

Reps that don't meet the gate are reported with sp_t = NaN.

CLI:
    python3 src/sticking_point/sticking_point.py <csv> <annotations_csv>
        [--method A|B|C|D] [--out <json>]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional

import numpy as np
from scipy.signal import find_peaks

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "velocity"))
from velocity_metrics import compute_metrics  # noqa: E402

# Thresholds tuned on the 8 clean sessions.
# Bench vy traces have a characteristic double-peak: an initial drive peak,
# a valley (the sticking region), and a recovery peak before lockout.
# Finding the INITIAL peak (not the higher of the two) is the critical
# step; we use scipy.find_peaks with a small prominence threshold so we
# pick up the first real rollover rather than integration wiggles.
SP_DEPTH_MIN = 0.04       # m/s — drive peak − valley drop required to count
POST_AMP_MIN = 0.02       # m/s — resurgence after the valley required
SP_FRAC_MIN = 0.10        # reject valleys in the first 10% of concentric
SP_FRAC_MAX = 0.90        # reject valleys in the last 10% of concentric
PEAK_PROMINENCE = 0.02    # m/s — minimum prominence to count a vy peak


@dataclass
class StickingPoint:
    num: int
    chest_s: float
    top_s: float
    pcv: float
    pcv_t: float
    sp_t: float            # NaN if no distinct sticking point
    sp_v: float            # NaN if no distinct sticking point
    sp_frac: float         # NaN if no distinct sticking point
    sp_depth: float        # 0.0 if no distinct sticking point
    sp_rel_depth: float    # 0.0 if no distinct sticking point
    post_amp: float        # 0.0 if no distinct sticking point
    has_sticking: bool


def find_sticking_point(t: np.ndarray, vy: np.ndarray, ci: int, li: int,
                        depth_min: float = SP_DEPTH_MIN,
                        post_amp_min: float = POST_AMP_MIN,
                        frac_min: float = SP_FRAC_MIN,
                        frac_max: float = SP_FRAC_MAX,
                        prominence: float = PEAK_PROMINENCE) -> dict:
    """Locate the sticking point inside a single concentric slice.

    Algorithm:
      1. Slice vy to [ci, li].
      2. Locate the INITIAL drive peak — the first local max of vy with
         prominence ≥ `prominence`. This avoids picking the recovery peak
         on heavy reps where the second peak is higher.
      3. Locate the deepest valley (local min, prominence ≥ `prominence`)
         between the drive peak and lockout.
      4. Accept only if depth ≥ depth_min, frac ∈ [frac_min, frac_max],
         and post-valley amplitude ≥ post_amp_min.

    PCV returned = the initial-drive peak (the value the bar actually
    accelerated to) so that SP_depth is always measured against drive
    energy, not against an artefact of post-sticking resurgence.
    """
    c_t = t[ci:li + 1]
    c_v = vy[ci:li + 1]
    cd = float(c_t[-1] - c_t[0])
    if len(c_v) < 4 or cd <= 0:
        return _no_sticking(c_v, c_t)

    peaks, _ = find_peaks(c_v, prominence=prominence)
    if len(peaks) == 0:
        # No true peak means monotonically rising or falling — no valley.
        pcv_rel = int(np.argmax(c_v))
        return _no_sticking(c_v, c_t, pcv=float(c_v[pcv_rel]),
                            pcv_t=float(c_t[pcv_rel]))
    pk_rel = int(peaks[0])
    pcv = float(c_v[pk_rel])
    pcv_t = float(c_t[pk_rel])

    if pk_rel >= len(c_v) - 2:
        return _no_sticking(c_v, c_t, pcv=pcv, pcv_t=pcv_t)

    # Find valleys between drive peak and lockout. Flip sign to reuse find_peaks.
    post_v = c_v[pk_rel:]
    post_t = c_t[pk_rel:]
    valleys, _ = find_peaks(-post_v, prominence=prominence)
    if len(valleys) == 0:
        return _no_sticking(c_v, c_t, pcv=pcv, pcv_t=pcv_t)
    # Deepest valley among the candidates
    valley_rel = int(valleys[int(np.argmin(post_v[valleys]))])

    if valley_rel <= 0 or valley_rel >= len(post_v) - 1:
        return _no_sticking(c_v, c_t, pcv=pcv, pcv_t=pcv_t)

    sp_v = float(post_v[valley_rel])
    sp_t = float(post_t[valley_rel])
    sp_frac = (sp_t - c_t[0]) / cd
    sp_depth = pcv - sp_v
    post_amp = float(np.max(post_v[valley_rel:]) - sp_v)

    has = (sp_depth >= depth_min and post_amp >= post_amp_min
           and frac_min <= sp_frac <= frac_max)

    return {
        "pcv": pcv,
        "pcv_t": pcv_t,
        "sp_t": sp_t if has else math.nan,
        "sp_v": sp_v if has else math.nan,
        "sp_frac": sp_frac if has else math.nan,
        "sp_depth": sp_depth if has else 0.0,
        "sp_rel_depth": (sp_depth / pcv) if (has and pcv > 0) else 0.0,
        "post_amp": post_amp if has else 0.0,
        "has_sticking": bool(has),
    }


def _no_sticking(c_v, c_t, pcv: Optional[float] = None,
                 pcv_t: Optional[float] = None) -> dict:
    pcv = pcv if pcv is not None else float(np.max(c_v))
    pcv_t = pcv_t if pcv_t is not None else float(c_t[int(np.argmax(c_v))])
    return {
        "pcv": pcv, "pcv_t": pcv_t,
        "sp_t": math.nan, "sp_v": math.nan, "sp_frac": math.nan,
        "sp_depth": 0.0, "sp_rel_depth": 0.0, "post_amp": 0.0,
        "has_sticking": False,
    }


def compute_sticking(csv_path: str, ann_path: Optional[str] = None,
                     method: str = "B"):
    """Run the velocity pipeline + sticking-point extraction for one session.

    Returns the upstream velocity result dict extended with a `sticking`
    list — one StickingPoint per kept rep, aligned 1:1 with result['reps'].

    `ann_path` is optional; when omitted, the detector provides rep
    boundaries and rep numbers are assigned 1..N.
    """
    result = compute_metrics(
        csv_path, ann_path, method=method, use_detector=True,
        snap=(ann_path is not None),
    )
    t = result["t"]
    vy = result["vy"]
    out: List[StickingPoint] = []
    for rep, (ci, li) in zip(result["reps"], result["boundaries"]):
        sp = find_sticking_point(t, vy, ci, li)
        out.append(StickingPoint(
            num=rep.num,
            chest_s=rep.chest_s,
            top_s=rep.top_s,
            pcv=sp["pcv"],
            pcv_t=sp["pcv_t"],
            sp_t=sp["sp_t"],
            sp_v=sp["sp_v"],
            sp_frac=sp["sp_frac"],
            sp_depth=sp["sp_depth"],
            sp_rel_depth=sp["sp_rel_depth"],
            post_amp=sp["post_amp"],
            has_sticking=sp["has_sticking"],
        ))
    result["sticking"] = out
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("ann")
    p.add_argument("--method", choices=["A", "B", "C", "D"], default="B")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    result = compute_sticking(args.csv, args.ann, args.method)
    rows = [asdict(s) for s in result["sticking"]]

    print(f"File:   {args.csv}")
    print(f"Method: {args.method}   reps={len(rows)}")
    hdr = (f"{'#':>3} {'chest':>6} {'top':>6} {'PCV':>6} "
           f"{'SP_t':>6} {'SP_v':>6} {'SP%':>5} {'depth':>6} "
           f"{'post':>6} {'sp?':>4}")
    print(hdr)
    for r in rows:
        sp_t = f"{r['sp_t']:.2f}" if not math.isnan(r["sp_t"]) else "  —"
        sp_v = f"{r['sp_v']:+.2f}" if not math.isnan(r["sp_v"]) else "  —"
        sp_f = (f"{r['sp_frac']*100:.0f}%" if not math.isnan(r["sp_frac"])
                else "  —")
        print(f"{r['num']:>3} {r['chest_s']:>6.2f} {r['top_s']:>6.2f} "
              f"{r['pcv']:>6.2f} {sp_t:>6} {sp_v:>6} {sp_f:>5} "
              f"{r['sp_depth']:>6.2f} {r['post_amp']:>6.2f} "
              f"{'Y' if r['has_sticking'] else 'n':>4}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"csv": args.csv, "method": args.method, "reps": rows},
                      f, indent=2)
        print(f"Wrote → {args.out}")


if __name__ == "__main__":
    main()
