"""
Validation harness — runs the Schmitt-trigger rep counter over every
session in data_collection/ that has a matching _annotations.csv and
reports per-session accuracy vs. the ground-truth label count.

Also cross-checks per-rep timing: each detected rep's concentric peak
should fall within TIMING_TOL_S of an annotated rep-top timestamp.
"""

import argparse
import glob
import os
import re
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from sign_change_rep_counter import (  # noqa
    compute_vy, build_reps, filter_by_rerack_gyro, filter_by_post_motion,
)

TIMING_TOL_S = 0.40


def parse_ground_truth(ann_path):
    """Return list of (rep_num, top_time_s) tuples and rack_time_s."""
    ann = pd.read_csv(ann_path)
    reps = []
    rack_s = None
    for _, row in ann.iterrows():
        lbl = str(row["label"]).strip()
        t_s = float(row["timestamp_ms"]) / 1000.0
        if lbl == "rack":
            rack_s = t_s
        elif re.fullmatch(r"\d+", lbl):
            reps.append((int(lbl), t_s))
    reps.sort(key=lambda x: x[0])
    return reps, rack_s


def evaluate(csv_path, ann_path, v_hi,
             rerack_ratio=1.5, post_window_s=2.0, post_min_gyro=0.7,
             window_start_s=None, window_end_s=None):
    df = pd.read_csv(csv_path)
    t, vy, gyro_mag, fs = compute_vy(df)

    candidates = build_reps(vy, v_hi, fs)
    if window_start_s is not None:
        candidates = [r for r in candidates if r["chest_s"] >= window_start_s]
    if window_end_s is not None:
        candidates = [r for r in candidates if r["lockout_s"] <= window_end_s]

    after_rerack = filter_by_rerack_gyro(candidates, gyro_mag, fs, rerack_ratio)
    kept = filter_by_post_motion(after_rerack, vy, gyro_mag, fs,
                                 post_window_s, post_min_gyro)

    gt_reps, rack_s = parse_ground_truth(ann_path)
    expected = len(gt_reps)
    detected = len(kept)

    # Match detected reps to ground-truth top times. The "top N" label
    # is placed at the lockout (vy crossing back to zero at the end of
    # the concentric), so match against lockout_s rather than peak_t.
    matches, misses, extras = [], [], []
    gt_times = [t_s for _, t_s in gt_reps]
    used = set()
    for rep in kept:
        ref_t = rep["lockout_s"]
        best_i, best_dt = None, None
        for i, gt_t in enumerate(gt_times):
            if i in used:
                continue
            dt = abs(ref_t - gt_t)
            if best_dt is None or dt < best_dt:
                best_i, best_dt = i, dt
        if best_i is not None and best_dt <= TIMING_TOL_S:
            used.add(best_i)
            matches.append((rep, gt_reps[best_i][0], best_dt))
        else:
            extras.append((rep, best_dt))
    for i, gt in enumerate(gt_reps):
        if i not in used:
            misses.append(gt)

    return {
        "csv": csv_path,
        "expected": expected,
        "detected": detected,
        "matches": matches,
        "misses": misses,
        "extras": extras,
        "candidates": candidates,
        "kept": kept,
        "fs": fs,
        "vy": vy,
        "t": t,
        "gyro_mag": gyro_mag,
        "gt_reps": gt_reps,
        "rack_s": rack_s,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--v-hi", type=float, default=0.25)
    p.add_argument("--rerack-ratio", type=float, default=1.5)
    p.add_argument("--post-window-s", type=float, default=2.0)
    p.add_argument("--post-min-gyro", type=float, default=0.7)
    p.add_argument("--use-annotations-window", action="store_true",
                   help="Clip detection to [first lockout, rack] from annotations")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    ann_files = sorted(glob.glob(os.path.join(args.dir, "*_annotations.csv")))
    results = []
    for ann in ann_files:
        csv = ann.replace("_annotations.csv", ".csv")
        if not os.path.exists(csv):
            continue
        # Build optional annotation window
        ws, we = None, None
        if args.use_annotations_window:
            anndf = pd.read_csv(ann)
            lockouts = anndf[anndf["label"] == "lockout"]["timestamp_ms"].values / 1000.0
            racks = anndf[anndf["label"] == "rack"]["timestamp_ms"].values / 1000.0
            if len(lockouts):
                ws = float(lockouts[0])
            if len(racks):
                we = float(racks[-1])
        res = evaluate(csv, ann, args.v_hi, args.rerack_ratio,
                       args.post_window_s, args.post_min_gyro, ws, we)
        results.append(res)

    # Print summary table
    print(f"Params: v_hi={args.v_hi}  rerack_ratio={args.rerack_ratio}  "
          f"post_window_s={args.post_window_s}  "
          f"post_min_gyro={args.post_min_gyro}  "
          f"annotations_window={args.use_annotations_window}")
    print(f"{'file':<60} {'exp':>4} {'det':>4} {'match':>5} {'miss':>4} {'extra':>5}  {'verdict'}")
    total_exp = total_det = total_match = total_miss = total_extra = 0
    all_perfect = True
    for r in results:
        name = os.path.basename(r["csv"]).replace(".csv", "")
        m, mi, ex = len(r["matches"]), len(r["misses"]), len(r["extras"])
        exp, det = r["expected"], r["detected"]
        total_exp += exp
        total_det += det
        total_match += m
        total_miss += mi
        total_extra += ex
        ok = (mi == 0 and ex == 0 and det == exp)
        all_perfect = all_perfect and ok
        verdict = "PASS" if ok else "FAIL"
        print(f"{name:<60} {exp:>4} {det:>4} {m:>5} {mi:>4} {ex:>5}  {verdict}")
    print(f"{'TOTAL':<60} {total_exp:>4} {total_det:>4} {total_match:>5} {total_miss:>4} {total_extra:>5}")
    print()

    if args.verbose:
        for r in results:
            if r["misses"] or r["extras"]:
                print(f"\n--- {os.path.basename(r['csv'])} ---")
                for rep, dt in r["extras"]:
                    print(f"  EXTRA  peak@{rep['peak_idx']/r['fs']:.2f}s "
                          f"v={rep['peak_v']:.3f}  nearest-gt-dt={dt}")
                for num, t_s in r["misses"]:
                    print(f"  MISS   gt rep #{num} top@{t_s:.2f}s")

    return 0 if all_perfect else 1


if __name__ == "__main__":
    sys.exit(main())
