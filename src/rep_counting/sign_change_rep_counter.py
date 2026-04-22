"""
Sign-Change Rep Counter
=======================
Counts bench-press reps from the vertical-velocity (Y) signal by tracking
sign changes, with noise filtering to reject the pre-first-lockout and
post-rack wobble that the raw zero-crossing approach picks up.

Pipeline
--------
  1. Load CSV, compute vy the same way as plot_session.py
     (gravity-removed Y accel → 5 Hz LP → cumsum → 0.3 Hz HP for drift).
  2. Find every zero crossing of vy.
  3. Run a Schmitt-trigger state machine over vy with rails at ±V_HI.
     A rep is registered the first time vy crosses +V_HI after having
     been below −V_HI (i.e. the eccentric→concentric turnaround at the
     chest). The trigger then must drop below −V_HI again before the
     next rep can count. Low-amplitude wobble (the pre-first-lockout
     and post-rack noise in the screenshot — typically ≤0.25 m/s) never
     reaches both rails, so it gets ignored by construction.
  4. Each registered rep's precise chest / lockout timestamps are
     recovered as the nearest true zero-crossings on either side of the
     concentric arm event.
  5. Gyro gating: unrack and re-rack involve large bar tilt (|gyro|
     spikes). A rep whose concentric peak sits inside a high-gyro
     window is dropped as an unrack/rerack artefact.

Usage
-----
    python3 src/rep_counting/sign_change_rep_counter.py <csv_path>
        [--v-hi 0.25] [--rerack-ratio 1.5] [--post-window-s 2.0]
        [--post-min-gyro 0.7] [--out <png>]

The script prints the rep count and saves a diagnostic PNG showing the
kept vs rejected crossings.
"""

import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# ────────────────────────────────────────────────────────────────────────
# Signal pipeline (matches data_collection/plot_session.py so the curve
# we analyse is the same one shown in the existing plots).
# ────────────────────────────────────────────────────────────────────────
LP_CUTOFF_HZ = 5.0
HP_CUTOFF_HZ = 0.3
FILTER_ORDER = 4


def compute_vy(df: pd.DataFrame):
    """Return (t_s, vy, gyro_mag, fs) for a session CSV."""
    t = df["timestamp_ms"].values.astype(float) / 1000.0
    fs = 1.0 / np.median(np.diff(t))

    # Calibration window = first 1 s (bar still before unrack)
    cal_n = min(int(fs), len(df))
    ay_raw = df["a1y"].values.astype(float)
    ay_lin = ay_raw - np.mean(ay_raw[:cal_n])

    # 5 Hz LP on Y accel
    b_lp, a_lp = butter(FILTER_ORDER, LP_CUTOFF_HZ / (fs / 2), btype="low")
    ay_f = filtfilt(b_lp, a_lp, ay_lin)

    # Integrate → HP to kill drift
    dt = np.diff(t, prepend=t[0])
    b_hp, a_hp = butter(FILTER_ORDER, HP_CUTOFF_HZ / (fs / 2), btype="high")
    vy = filtfilt(b_hp, a_hp, np.cumsum(ay_f * dt))

    # Gyro magnitude for the unrack/rerack gate
    gx = df["g1x"].values.astype(float)
    gy = df["g1y"].values.astype(float)
    gz = df["g1z"].values.astype(float)
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    # Smooth gyro so a single noisy sample doesn't flag a whole rep
    b_gl, a_gl = butter(2, 2.0 / (fs / 2), btype="low")
    gyro_mag = filtfilt(b_gl, a_gl, gyro_mag)

    return t, vy, gyro_mag, fs


# ────────────────────────────────────────────────────────────────────────
# Sign-change detection & Schmitt-trigger rep counter
# ────────────────────────────────────────────────────────────────────────
def find_sign_changes(vy: np.ndarray) -> np.ndarray:
    """Indices i where sign(vy[i]) != sign(vy[i-1]) (ignoring exact zeros)."""
    sig = np.sign(vy)
    for i in range(1, len(sig)):
        if sig[i] == 0:
            sig[i] = sig[i - 1]
    return np.where(np.diff(sig) != 0)[0] + 1


def schmitt_rep_events(vy: np.ndarray, v_hi: float):
    """
    Walk vy with a ±v_hi Schmitt trigger and return concentric-arm indices.

    Each returned index is the sample where vy first crosses ABOVE +v_hi
    after having been BELOW −v_hi — i.e. the moment the concentric push
    has clearly begun after a real eccentric descent. This is immune to
    the ≤0.25 m/s pre-lockout/post-rack chatter because that chatter
    never reaches even one rail, let alone both.

    A rep is NOT re-armed until vy drops below −v_hi again, so a bouncy
    lockout doesn't double-count.
    """
    events = []
    # States: "need_low" → waiting for eccentric to cross below −v_hi
    #         "armed"    → eccentric confirmed, waiting for concentric >+v_hi
    state = "need_low"
    for i in range(len(vy)):
        if state == "need_low":
            if vy[i] < -v_hi:
                state = "armed"
        else:  # armed
            if vy[i] > v_hi:
                events.append(i)
                state = "need_low"
    return np.array(events, dtype=int)


def locate_rep_boundaries(vy: np.ndarray, arm_idx: int):
    """
    Given a concentric-arm index (vy just crossed +v_hi), find the actual
    chest zero-crossing (− → +) before it and the lockout zero-crossing
    (+ → −) after it.
    """
    # Walk left from arm_idx until vy goes ≤ 0 — that's the chest crossing
    chest_idx = arm_idx
    while chest_idx > 0 and vy[chest_idx - 1] > 0:
        chest_idx -= 1

    # Walk right from arm_idx until vy goes ≤ 0 — that's the lockout
    lockout_idx = arm_idx
    n = len(vy)
    while lockout_idx < n - 1 and vy[lockout_idx + 1] > 0:
        lockout_idx += 1
    return chest_idx, lockout_idx


def filter_by_rerack_gyro(reps, gyro_mag: np.ndarray, fs: float,
                          rerack_ratio: float = 1.5):
    """
    Drop candidates whose lockout occurs AFTER the global gyro peak, IF
    that peak looks like a rerack event.

    Rationale: the rerack — swinging the bar forward onto J-hooks or onto
    the floor stack — generates substantially more rotation than a clean
    rep. When present, it is typically the single largest |gyro| spike in
    the recording. Any zero-crossing candidate whose peak lives to the
    right of that spike is post-rack settling and should be discarded.

    We only treat the max-gyro sample as a "rerack" if it is at least
    `rerack_ratio`× larger than the median of the per-rep gyro peaks
    across all candidates. This guards against sessions where the gyro
    is dominated by one noisy rep rather than the rack event.
    """
    if len(reps) == 0:
        return reps

    # Per-rep gyro peak (over chest..lockout)
    rep_gyros = []
    for rep in reps:
        lo, hi = rep["chest_idx"], rep["lockout_idx"] + 1
        rep_gyros.append(float(np.max(gyro_mag[lo:hi])) if hi > lo else 0.0)
    median_rep_gyro = float(np.median(rep_gyros)) if rep_gyros else 0.0

    global_peak_idx = int(np.argmax(gyro_mag))
    global_peak_val = float(gyro_mag[global_peak_idx])

    # If the global max isn't clearly a rerack-scale event, don't gate.
    if median_rep_gyro > 0 and global_peak_val < rerack_ratio * median_rep_gyro:
        return reps

    # Keep only reps whose lockout is at or before the global gyro peak.
    return [r for r in reps if r["lockout_idx"] <= global_peak_idx]


def filter_by_post_motion(reps, vy: np.ndarray, gyro_mag: np.ndarray,
                          fs: float, post_window_s: float = 2.0,
                          min_post_gyro: float = 0.7):
    """
    If the LAST candidate has no post-lockout motion, drop it — it is
    the re-rack event, not a rep.

    A real last rep is always followed by the re-rack (bar guided onto
    hooks or stack), which has a distinct |gyro| signature — peak
    0.99–2.14 rad/s across this dataset. The re-rack event itself, on
    the other hand, is followed by the bar sitting still on the hooks
    (post-lockout gyro peak ≤0.51 rad/s).

    We only apply this test to the last candidate in the list. Earlier
    candidates are always followed by another candidate's motion, so
    their "post-window" features are meaningless as a re-rack test
    (and with light weight like the deadlift pilot the bar barely tilts
    during normal reps — applying this gate mid-set would delete real
    reps).
    """
    if len(reps) == 0:
        return reps

    last = reps[-1]
    n = len(gyro_mag)
    win = int(post_window_s * fs)
    lo = last["lockout_idx"]
    hi = min(n, lo + win)
    post_seg = gyro_mag[lo:hi]

    # Not enough recording after lockout to judge → keep (avoid dropping
    # a legitimate last rep that happened near end-of-file).
    if len(post_seg) < int(0.5 * fs):
        return reps

    if float(np.max(post_seg)) >= min_post_gyro:
        return reps  # rerack is ahead → last candidate is a real rep
    return reps[:-1]  # bar is at rest → last candidate IS the rerack


def build_reps(vy: np.ndarray, v_hi: float, fs: float):
    """Run the Schmitt trigger and assemble rep records."""
    arm_events = schmitt_rep_events(vy, v_hi)
    reps = []
    for k, arm in enumerate(arm_events):
        chest_idx, lockout_idx = locate_rep_boundaries(vy, arm)
        conc = vy[chest_idx:lockout_idx + 1]
        if len(conc) == 0:
            continue
        peak_v = float(np.max(conc))
        peak_idx = chest_idx + int(np.argmax(conc))
        reps.append({
            "rep_num": k + 1,
            "chest_idx": int(chest_idx),
            "lockout_idx": int(lockout_idx),
            "peak_idx": peak_idx,
            "chest_s": chest_idx / fs,
            "lockout_s": lockout_idx / fs,
            "peak_v": peak_v,
            "duration_s": (lockout_idx - chest_idx) / fs,
        })
    return reps


# ────────────────────────────────────────────────────────────────────────
# Diagnostic plot
# ────────────────────────────────────────────────────────────────────────
def make_diagnostic_plot(t, vy, gyro_mag, all_crossings, reps, rejected_reps,
                         v_hi, out_path, title):
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    fig.patch.set_facecolor("#1a1a2e")
    for ax in axes:
        ax.set_facecolor("#16213e")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#444466")
        ax.yaxis.label.set_color("white")
        ax.xaxis.label.set_color("white")
        ax.title.set_color("white")

    ax0 = axes[0]
    ax0.plot(t, vy, color="#fd79a8", lw=1.3, label="Y velocity")
    ax0.fill_between(t, vy, 0, where=(vy > 0), color="#fd79a8", alpha=0.18,
                     label="concentric (+)")
    ax0.fill_between(t, vy, 0, where=(vy < 0), color="#74b9ff", alpha=0.18,
                     label="eccentric (−)")
    ax0.axhline(0, color="#555577", lw=0.8)
    ax0.axhline(v_hi, color="#2ecc71", lw=0.7, ls=":", alpha=0.6,
                label=f"±v_hi = {v_hi:.2f}")
    ax0.axhline(-v_hi, color="#2ecc71", lw=0.7, ls=":", alpha=0.6)

    # Show every raw zero-crossing in red for context
    for cr in all_crossings:
        ax0.axvline(t[cr], color="#e74c3c", lw=0.5, ls=":", alpha=0.35)

    # Draw each accepted rep as a pair of solid green lines at its
    # chest and lockout boundaries, with the rep number above the peak.
    for rep in reps:
        ax0.axvline(t[rep["chest_idx"]], color="#2ecc71", lw=1.3, alpha=0.9)
        ax0.axvline(t[rep["lockout_idx"]], color="#2ecc71", lw=1.3,
                    ls="--", alpha=0.9)
        ax0.text(t[rep["peak_idx"]], rep["peak_v"] + 0.05,
                 f"rep {rep['rep_num']}", color="#ffe66d", fontsize=9,
                 ha="center", va="bottom", fontweight="bold")

    # Rerack/post-motion rejected reps drawn in orange
    for rep in rejected_reps:
        ax0.axvline(t[rep["chest_idx"]], color="#f39c12", lw=1.0, alpha=0.7)
        ax0.axvline(t[rep["lockout_idx"]], color="#f39c12", lw=1.0,
                    ls="--", alpha=0.7)
        ax0.text(t[rep["peak_idx"]], rep["peak_v"] + 0.05,
                 "rerack-rej", color="#f39c12", fontsize=8,
                 ha="center", va="bottom")

    ax0.set_ylabel("Velocity (m/s)")
    ax0.set_title(
        f"{title}  |  {len(reps)} reps kept  |  "
        f"{len(rejected_reps)} rerack-rejected  |  "
        f"{len(all_crossings)} raw zero-crossings",
        pad=4)
    ax0.legend(loc="upper right", fontsize=8, framealpha=0.3,
               labelcolor="white", facecolor="#1a1a2e", edgecolor="#444466")

    # Bottom: gyro magnitude for context (no threshold line now)
    ax1 = axes[1]
    ax1.plot(t, gyro_mag, color="#fdcb6e", lw=1.0, label="|gyro| (LP 2 Hz)")
    ax1.set_ylabel("|Gyro| (rad/s)")
    ax1.set_xlabel("Time (s)")
    ax1.legend(loc="upper right", fontsize=8, framealpha=0.3,
               labelcolor="white", facecolor="#1a1a2e", edgecolor="#444466")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(),
                bbox_inches="tight")
    plt.close(fig)


# ────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="Session CSV path")
    p.add_argument("--v-hi", type=float, default=0.25,
                   help="Hysteresis rail — each segment must peak above this "
                        "|m/s| to count as a real half-rep (default 0.25)")
    p.add_argument("--rerack-ratio", type=float, default=1.5,
                   help="Treat the global gyro maximum as a rerack event if "
                        "it is at least this × the median per-rep gyro peak; "
                        "candidates after that point are dropped (default 1.5)")
    p.add_argument("--post-window-s", type=float, default=2.0,
                   help="Seconds of post-lockout signal to require motion in "
                        "(default 2.0)")
    p.add_argument("--post-min-gyro", type=float, default=0.7,
                   help="Required max |gyro| (rad/s) in the post-lockout "
                        "window. Candidates whose post-window stays below "
                        "this are the rerack event itself and are dropped "
                        "(default 0.7)")
    p.add_argument("--out", type=str, default=None,
                   help="Output diagnostic PNG path (default <csv>_reps.png)")
    args = p.parse_args()

    df = pd.read_csv(args.csv)
    t, vy, gyro_mag, fs = compute_vy(df)

    raw_crossings = find_sign_changes(vy)

    # Schmitt trigger → rep candidates
    candidates = build_reps(vy, args.v_hi, fs)

    # Gate A: drop anything after the global gyro peak (the rerack),
    # provided that peak is prominent relative to per-rep rotation.
    after_rerack = filter_by_rerack_gyro(candidates, gyro_mag, fs,
                                         args.rerack_ratio)

    # Gate B: if the LAST candidate's post-lockout window has no motion,
    # the bar has settled on the rack and this "rep" was the rerack itself.
    kept_reps = filter_by_post_motion(after_rerack, vy, gyro_mag, fs,
                                      args.post_window_s, args.post_min_gyro)
    rejected_reps = [r for r in candidates if r not in kept_reps]

    # Renumber kept reps 1..N
    for i, r in enumerate(kept_reps):
        r["rep_num"] = i + 1

    out_png = args.out or args.csv.replace(".csv", "_reps.png")
    title = os.path.basename(args.csv)
    make_diagnostic_plot(t, vy, gyro_mag, raw_crossings, kept_reps,
                         rejected_reps, args.v_hi, out_png, title)

    print(f"File:              {args.csv}")
    print(f"Sample rate:       {fs:.1f} Hz")
    print(f"Raw sign changes:  {len(raw_crossings)}")
    print(f"Schmitt reps:      {len(candidates)}  (v_hi = ±{args.v_hi} m/s)")
    print(f"Rerack-rejected:   {len(rejected_reps)}")
    print(f"Reps detected:     {len(kept_reps)}")
    for r in kept_reps:
        print(f"  rep {r['rep_num']:>2}:  chest={r['chest_s']:6.2f}s  "
              f"lockout={r['lockout_s']:6.2f}s  "
              f"peak_v={r['peak_v']:.3f} m/s  "
              f"dur={r['duration_s']:.2f}s")
    print(f"Diagnostic plot:   {out_png}")


if __name__ == "__main__":
    main()
