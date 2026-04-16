"""
plot_session.py — plot IMU session with annotation overlays
Usage:
    python3 plot_session.py <csv> <annotations_csv> [title] [--end <seconds>]
"""
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.signal import butter, filtfilt

# ── Args ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("csv")
parser.add_argument("ann")
parser.add_argument("title", nargs="?", default=None)
parser.add_argument("--end", type=float, default=None, help="Truncate to this many seconds")
args = parser.parse_args()

csv_path = args.csv
ann_path = args.ann
title    = args.title or csv_path

# ── Load ────────────────────────────────────────────────────────────────────────
df  = pd.read_csv(csv_path)
ann = pd.read_csv(ann_path)

t = df["timestamp_ms"].values / 1000.0  # seconds

# Truncate to --end seconds if requested
if args.end is not None:
    mask = t <= args.end
    df = df[mask].reset_index(drop=True)
    t  = t[mask]

fs = 1.0 / np.median(np.diff(t))

# ── Per-axis linear acceleration (remove gravity on each axis from calibration) ─
cal_n = min(int(fs), len(df))   # first ~1 s as calibration window
ax_raw = df["a1x"].values.astype(float)
ay_raw = df["a1y"].values.astype(float)
az_raw = df["a1z"].values.astype(float)

ax_lin = ax_raw - np.mean(ax_raw[:cal_n])
ay_lin = ay_raw - np.mean(ay_raw[:cal_n])
az_lin = az_raw - np.mean(az_raw[:cal_n])

# ── Low-pass filter ─────────────────────────────────────────────────────────────
cutoff = 5.0   # Hz
b, a_coef = butter(4, cutoff / (fs / 2), btype="low")
ax_f = filtfilt(b, a_coef, ax_lin)
ay_f = filtfilt(b, a_coef, ay_lin)

# ── Velocity via integration + high-pass drift removal ─────────────────────────
hp_cut = 0.3   # Hz — removes DC drift that accumulates between reps
b_hp, a_hp = butter(4, hp_cut / (fs / 2), btype="high")

dt = np.diff(t, prepend=t[0])
vy = filtfilt(b_hp, a_hp, np.cumsum(ay_f * dt))   # vertical   (Y)
vx = filtfilt(b_hp, a_hp, np.cumsum(ax_f * dt))   # horizontal (X)

# ── Annotations ─────────────────────────────────────────────────────────────────
ann_t     = ann["timestamp_ms"].values / 1000.0
ann_label = ann["label"].values.astype(str)

if args.end is not None:
    ann_mask  = ann_t <= args.end
    ann_t     = ann_t[ann_mask]
    ann_label = ann_label[ann_mask]

label_style = {
    "lockout": dict(color="#2ecc71", ls="--", lw=1.8),
    "chest":   dict(color="#e74c3c", ls="--", lw=1.8),
    "rack":    dict(color="#9b59b6", ls="--", lw=1.8),
}
rep_color = "#f39c12"

def is_rep_top(lbl):
    try: int(lbl); return True
    except ValueError: return False

def draw_annotations(ax, ymin, ymax):
    span = ymax - ymin if ymax != ymin else 1.0
    for ts, lbl in zip(ann_t, ann_label):
        if is_rep_top(lbl):
            ax.axvline(ts, color=rep_color, ls=":", lw=1.5, alpha=0.85)
            ax.text(ts + 0.03, ymin + span * 0.85, f"top {lbl}",
                    color=rep_color, fontsize=7, rotation=90, va="top", alpha=0.9)
        else:
            style = label_style.get(lbl, dict(color="white", ls="--", lw=1.5))
            ax.axvline(ts, color=style["color"], ls=style["ls"], lw=style["lw"], alpha=0.85)
            ax.text(ts + 0.03, ymin + span * 0.85, lbl,
                    color=style["color"], fontsize=7, rotation=90, va="top", alpha=0.9)

# ── Figure: 4 rows — Y accel, Y velocity, X accel, X velocity ───────────────────
fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
fig.patch.set_facecolor("#1a1a2e")
for ax in axes:
    ax.set_facecolor("#16213e")
    ax.tick_params(colors="white")
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")
    for spine in ax.spines.values():
        spine.set_color("#444466")

# Row 0: Y accel (vertical)
axes[0].plot(t, ay_raw, color="#74b9ff", lw=0.6, alpha=0.5, label="Y raw")
axes[0].plot(t, ay_f,   color="#00cec9", lw=1.3, label="Y filtered (5 Hz LP)")
axes[0].axhline(0, color="#555577", lw=0.8)
axes[0].set_ylabel("Accel (m/s²)")
axes[0].set_title("Y Acceleration — Vertical (gravity removed)", color="white", fontsize=10, pad=4)
draw_annotations(axes[0], min(ay_raw.min(), ay_f.min()), max(ay_raw.max(), ay_f.max()))
axes[0].legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
               facecolor="#1a1a2e", edgecolor="#444466")

# Row 1: Y velocity (vertical)
axes[1].plot(t, vy, color="#fd79a8", lw=1.4, label="Y velocity")
axes[1].axhline(0, color="#555577", lw=0.8)
axes[1].fill_between(t, vy, 0, where=(vy > 0), color="#fd79a8", alpha=0.2, label="concentric (+)")
axes[1].fill_between(t, vy, 0, where=(vy < 0), color="#74b9ff", alpha=0.2, label="eccentric (−)")
axes[1].set_ylabel("Velocity (m/s)")
axes[1].set_title("Y Velocity — Vertical (integrated, HP drift removal)", color="white", fontsize=10, pad=4)
draw_annotations(axes[1], vy.min(), vy.max())
axes[1].legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
               facecolor="#1a1a2e", edgecolor="#444466")

# Row 2: X accel (horizontal / bar path)
axes[2].plot(t, ax_raw, color="#74b9ff", lw=0.6, alpha=0.5, label="X raw")
axes[2].plot(t, ax_f,   color="#fdcb6e", lw=1.3, label="X filtered (5 Hz LP)")
axes[2].axhline(0, color="#555577", lw=0.8)
axes[2].set_ylabel("Accel (m/s²)")
axes[2].set_title("X Acceleration — Horizontal (bar path forward/back)", color="white", fontsize=10, pad=4)
draw_annotations(axes[2], min(ax_raw.min(), ax_f.min()), max(ax_raw.max(), ax_f.max()))
axes[2].legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
               facecolor="#1a1a2e", edgecolor="#444466")

# Row 3: X velocity (horizontal)
axes[3].plot(t, vx, color="#fdcb6e", lw=1.4, label="X velocity")
axes[3].axhline(0, color="#555577", lw=0.8)
axes[3].fill_between(t, vx, 0, where=(vx > 0), color="#fdcb6e", alpha=0.2, label="forward (+)")
axes[3].fill_between(t, vx, 0, where=(vx < 0), color="#a29bfe", alpha=0.2, label="backward (−)")
axes[3].set_ylabel("Velocity (m/s)")
axes[3].set_xlabel("Time (s)")
axes[3].set_title("X Velocity — Horizontal (integrated, HP drift removal)", color="white", fontsize=10, pad=4)
draw_annotations(axes[3], vx.min(), vx.max())
axes[3].legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
               facecolor="#1a1a2e", edgecolor="#444466")

# ── Shared legend ───────────────────────────────────────────────────────────────
legend_patches = [
    mpatches.Patch(color="#2ecc71", label="lockout"),
    mpatches.Patch(color="#e74c3c", label="chest (bottom)"),
    mpatches.Patch(color="#f39c12", label="rep top"),
    mpatches.Patch(color="#9b59b6", label="rack"),
]
fig.legend(handles=legend_patches, loc="lower center", ncol=4, fontsize=9,
           framealpha=0.4, labelcolor="white", facecolor="#1a1a2e",
           edgecolor="#444466", bbox_to_anchor=(0.5, 0.0))

fig.suptitle(title, color="white", fontsize=13, fontweight="bold", y=1.005)
plt.tight_layout(rect=[0, 0.04, 1, 1])

out = csv_path.replace(".csv", "_plot.png")
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved → {out}")
