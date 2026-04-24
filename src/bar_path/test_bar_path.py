"""Smoke tests for ``src.bar_path``.

These exercise the happy path on the committed pilot-session CSV so
the core reconstruction cannot silently regress on sanity limits
(drift bounds, ROM sign, array length contracts).

Run from the repo root with::

    python src/bar_path/test_bar_path.py

No external test runner required — the script exits non-zero on any
failure.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
))

from src.bar_path import reconstruct_csv
from src.bar_path.reconstruct import REP_PATH_SAMPLES


CSV = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "data_collection", "session_20260409_175030.csv",
))


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_pilot_session():
    result = reconstruct_csv(CSV)

    _check(result.n_reps >= 5,
           f"expected ≥5 reps in pilot session, got {result.n_reps}")
    _check(result.fs_hz > 100, f"unrealistic fs_hz: {result.fs_hz}")
    _check(result.duration_s > 10, "session too short")

    for r in result.reps:
        _check(len(r.t_s) == REP_PATH_SAMPLES, "t_s wrong length")
        _check(len(r.x_m) == REP_PATH_SAMPLES, "x_m wrong length")
        _check(len(r.y_m) == REP_PATH_SAMPLES, "y_m wrong length")
        _check(len(r.z_m) == REP_PATH_SAMPLES, "z_m wrong length")

        _check(0 <= r.chest_idx < REP_PATH_SAMPLES,
               f"rep {r.num}: chest_idx {r.chest_idx} out of range")
        _check(0 <= r.lockout_idx < REP_PATH_SAMPLES,
               f"rep {r.num}: lockout_idx {r.lockout_idx} out of range")
        _check(r.chest_idx < r.lockout_idx,
               f"rep {r.num}: chest_idx should precede lockout_idx")

        _check(r.duration_s > 0.3,
               f"rep {r.num}: duration {r.duration_s} too short")
        _check(r.duration_s < 5.0,
               f"rep {r.num}: duration {r.duration_s} too long")

        # Drift bounds — single-IMU bar path can't keep tight absolute
        # accuracy, but per-rep deviations above 20 cm indicate the
        # integrator has broken down.
        _check(r.rom_m < 0.60,
               f"rep {r.num}: ROM {r.rom_m:.2f} m suspiciously high")
        _check(r.peak_x_dev_m < 0.25,
               f"rep {r.num}: forward drift {r.peak_x_dev_m:.2f} m too high")
        _check(r.peak_y_dev_m < 0.25,
               f"rep {r.num}: lateral drift {r.peak_y_dev_m:.2f} m too high")

        # Path endpoints — start anchored to 0, concentric lockout ≈ 0
        _check(abs(r.z_m[0]) < 0.05,
               f"rep {r.num}: start z should be ~0, got {r.z_m[0]:.3f}")
        _check(abs(r.z_m[r.lockout_idx]) < 0.10,
               f"rep {r.num}: lockout z should be ~0, got "
               f"{r.z_m[r.lockout_idx]:.3f}")

        # Chest is the deepest point — z at chest should be negative
        # and more negative than any earlier sample
        _check(r.z_m[r.chest_idx] < 0,
               f"rep {r.num}: chest z should be negative (below start), "
               f"got {r.z_m[r.chest_idx]:.3f}")


if __name__ == "__main__":
    test_pilot_session()
    print("OK — all bar-path smoke tests passed")
