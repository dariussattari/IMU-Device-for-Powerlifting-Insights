import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.signal import butter, filtfilt

# ── Load data ──────────────────────────────────────────────────────────────────
df = pd.read_csv("session_20260414_102551.csv")
ann = pd.read_csv("session_20260414_102551_annotations.csv")

t = df["timestamp_ms"].values / 1000.0  # seconds

# ── Raw acceleration magnitude (subtract gravity baseline) ──────────────────────
raw_mag = np.sqrt(df["a1x"]**2 + df["a1y"]**2 + df["a1z"]**2).values
# Estimate gravity as median over the full session
g_est = np.median(raw_mag)
accel_net = raw_mag - g_est  # net vertical-ish acceleration (m/s²)

# ── Low-pass Butterworth filter ─────────────────────────────────────────────────
fs = 1.0 / np.median(np.diff(t))  # sample rate (Hz)
cutoff = 5.0  # Hz — keeps rep motion, removes vibration
b, a_coef = butter(4, cutoff / (fs / 2), btype="low")
accel_filt = filtfilt(b, a_coef, accel_net)

# ── Velocity via cumulative trapezoidal integration ─────────────────────────────
dt = np.diff(t, prepend=t[0])
velocity = np.cumsum(accel_filt * dt)
# Zero-mean drift correction: remove linear trend between first and last point
trend = np.linspace(velocity[0], velocity[-1], len(velocity))
velocity = velocity - trend

# ── Annotation helpers ──────────────────────────────────────────────────────────
ann_t = ann["timestamp_ms"].values / 1000.0
ann_label = ann["label"].values

label_style = {
    "lockout": dict(color="#2ecc71", ls="--", lw=1.8, marker="^"),
    "chest":   dict(color="#e74c3c", ls="--", lw=1.8, marker="v"),
    "rack":    dict(color="#9b59b6", ls="--", lw=1.8, marker="s"),
}
rep_color = "#f39c12"  # rep tops (numbered labels)

def is_rep_top(lbl):
    try:
        int(lbl)
        return True
    except ValueError:
        return False

# ── Figure ──────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
fig.patch.set_facecolor("#1a1a2e")
for ax in axes:
    ax.set_facecolor("#16213e")
    ax.tick_params(colors="white")
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.spines["bottom"].set_color("#444466")
    ax.spines["top"].set_color("#444466")
    ax.spines["left"].set_color("#444466")
    ax.spines["right"].set_color("#444466")

def draw_annotations(ax, ymin, ymax):
    for ts, lbl in zip(ann_t, ann_label):
        if is_rep_top(lbl):
            ax.axvline(ts, color=rep_color, ls=":", lw=1.5, alpha=0.85)
            ax.text(ts + 0.03, ymax * 0.85, f"top {lbl}", color=rep_color,
                    fontsize=7, rotation=90, va="top", alpha=0.9)
        else:
            style = label_style.get(lbl, dict(color="white", ls="--", lw=1.5))
            ax.axvline(ts, color=style["color"], ls=style["ls"], lw=style["lw"], alpha=0.85)
            ax.text(ts + 0.03, ymax * 0.85, lbl, color=style["color"],
                    fontsize=7, rotation=90, va="top", alpha=0.9)

# ── Panel 1: Raw acceleration ───────────────────────────────────────────────────
ax0 = axes[0]
ax0.plot(t, accel_net, color="#74b9ff", lw=0.7, alpha=0.6, label="raw net accel")
ax0.axhline(0, color="#555577", lw=0.8, ls="-")
ax0.set_ylabel("Net Accel (m/s²)")
ax0.set_title("Raw Acceleration", color="white", fontsize=10, pad=4)
draw_annotations(ax0, accel_net.min(), accel_net.max())
ax0.legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
           facecolor="#1a1a2e", edgecolor="#444466")

# ── Panel 2: Filtered acceleration ─────────────────────────────────────────────
ax1 = axes[1]
ax1.plot(t, accel_filt, color="#00cec9", lw=1.4, label=f"filtered ({cutoff} Hz LP)")
ax1.axhline(0, color="#555577", lw=0.8, ls="-")
ax1.set_ylabel("Net Accel (m/s²)")
ax1.set_title("Filtered Acceleration", color="white", fontsize=10, pad=4)
draw_annotations(ax1, accel_filt.min(), accel_filt.max())
ax1.legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
           facecolor="#1a1a2e", edgecolor="#444466")

# ── Panel 3: Velocity ───────────────────────────────────────────────────────────
ax2 = axes[2]
ax2.plot(t, velocity, color="#fd79a8", lw=1.4, label="velocity (integrated)")
ax2.axhline(0, color="#555577", lw=0.8, ls="-")
ax2.fill_between(t, velocity, 0, where=(velocity > 0),
                 color="#fd79a8", alpha=0.15, label="concentric")
ax2.fill_between(t, velocity, 0, where=(velocity < 0),
                 color="#74b9ff", alpha=0.15, label="eccentric")
ax2.set_ylabel("Velocity (m/s)")
ax2.set_xlabel("Time (s)")
ax2.set_title("Velocity", color="white", fontsize=10, pad=4)
draw_annotations(ax2, velocity.min(), velocity.max())
ax2.legend(loc="upper right", fontsize=8, framealpha=0.3, labelcolor="white",
           facecolor="#1a1a2e", edgecolor="#444466")

# ── Legend for annotation lines ─────────────────────────────────────────────────
legend_patches = [
    mpatches.Patch(color="#2ecc71", label="unrack (lockout)"),
    mpatches.Patch(color="#e74c3c", label="chest (bottom)"),
    mpatches.Patch(color="#f39c12", label="rep top"),
    mpatches.Patch(color="#9b59b6", label="rack"),
]
fig.legend(handles=legend_patches, loc="lower center", ncol=4, fontsize=9,
           framealpha=0.4, labelcolor="white", facecolor="#1a1a2e",
           edgecolor="#444466", bbox_to_anchor=(0.5, 0.0))

fig.suptitle("Session 20260414_102551 — Bench Press (3 Reps)",
             color="white", fontsize=13, fontweight="bold", y=1.01)
plt.tight_layout(rect=[0, 0.04, 1, 1])

out = "session_20260414_102551_plot.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved → {out}")
plt.show()
