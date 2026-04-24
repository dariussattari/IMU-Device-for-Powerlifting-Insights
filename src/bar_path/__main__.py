"""CLI entry point: ``python -m src.bar_path <csv> [--out path.json]``.

Runs the reconstruction pipeline on a session CSV and prints a short
summary. Optionally writes the full per-rep paths to JSON for
visualization or downstream analysis.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .reconstruct import reconstruct_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.bar_path",
        description="Reconstruct per-rep bar paths from a single-IMU session CSV.",
    )
    ap.add_argument("csv", help="Path to session CSV (timestamp_ms, a1*, g1*)")
    ap.add_argument("--out", "-o", default=None,
                    help="Optional JSON output path for full per-rep paths")
    args = ap.parse_args(argv)

    result = reconstruct_csv(args.csv)

    print(f"Session:   {args.csv}")
    print(f"Duration:  {result.duration_s:.2f} s   "
          f"@ {result.fs_hz:.1f} Hz")
    print(f"Reps:      {result.n_reps}")
    print("-" * 60)
    print(f"{'#':>3}  {'t_start':>8}  {'dur':>6}  "
          f"{'ROM':>7}  {'|x|max':>7}  {'|y|max':>7}")
    for r in result.reps:
        print(f"{r.num:>3}  "
              f"{r.start_s:>8.2f}  {r.duration_s:>6.2f}  "
              f"{r.rom_m*100:>6.1f}cm  "
              f"{r.peak_x_dev_m*100:>6.1f}cm  "
              f"{r.peak_y_dev_m*100:>6.1f}cm")

    if args.out:
        payload = {
            "fs_hz": result.fs_hz,
            "duration_s": result.duration_s,
            "n_reps": result.n_reps,
            "notes": result.notes,
            "reps": [asdict(r) for r in result.reps],
        }
        with open(args.out, "w") as f:
            json.dump(payload, f)
        print(f"\nWrote: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
