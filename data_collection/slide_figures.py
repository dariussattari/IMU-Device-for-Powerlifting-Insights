"""Generate the 4 slide figures (rep counting, velocity/sticking, 1RM, bar path).

Pulls data from the existing 8 clean bench sessions and re-renders each figure
in the slide deck's olive/cream/lime palette so the methods slides have real
results, not stock illustrations. One figure per slide; each one shows the
journey from raw IMU signal to the result that the front-end UI displays.

    python3 data_collection/slide_figures.py

Outputs:
    data_collection/slide_figures/01_rep_counting.png
    data_collection/slide_figures/02_velocity_sticking.png
    data_collection/slide_figures/03_one_rm.png
    data_collection/slide_figures/04_bar_path.png
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch

# ──────────────────────────────────────────────────────────────────────
# Path bootstrapping so we can import the project's analysis modules
# ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
for sub in ("rep_counting", "velocity", "sticking_point", "one_rm"):
    p = os.path.join(ROOT, "src", sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from sign_change_rep_counter import (  # noqa: E402
    build_reps,
    compute_vy,
    filter_by_post_motion,
    filter_by_rerack_gyro,
    find_sign_changes,
)
from velocity_metrics import compute_metrics  # noqa: E402
from sticking_point import compute_sticking  # noqa: E402

from src.bar_path.reconstruct import reconstruct_csv  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# Slide palette — sampled from BarbellLab.pptx
# ──────────────────────────────────────────────────────────────────────
BG_DARK     = "#0a1207"   # slide background
BG_PANEL    = "#131b0e"   # axis facecolor (one notch lighter for separation)
INK         = "#e8e6d6"   # primary text / curves
INK_DIM     = "#8a8b7a"   # muted labels
GRID        = "#28301f"   # subtle grid
SIG         = "#c5d96a"   # lime accent — primary signal
SIG_DIM     = "#859144"   # muted lime
COOL        = "#6b9aaf"   # desaturated cool — eccentric phase
WARM        = "#e8a05a"   # orange — sticking / rejection
HIGHLIGHT   = "#f0e890"   # pale yellow — rep numbers / callouts

DATA_DIR = os.path.join(ROOT, "data_collection")
OUT_DIR = os.path.join(DATA_DIR, "slide_figures")
os.makedirs(OUT_DIR, exist_ok=True)


def slide_axes(ax):
    """Apply slide styling to an axis."""
    ax.set_facecolor(BG_PANEL)
    ax.tick_params(colors=INK_DIM, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(GRID)
        spine.set_linewidth(0.8)
    ax.grid(True, color=GRID, lw=0.5, alpha=0.6)
    ax.xaxis.label.set_color(INK_DIM)
    ax.yaxis.label.set_color(INK_DIM)
    ax.title.set_color(INK)
    return ax


def slide_figure(figsize=(14, 6.5)):
    fig = plt.figure(figsize=figsize, dpi=180, facecolor=BG_DARK)
    return fig


def save(fig, name):
    out = os.path.join(OUT_DIR, name)
    fig.savefig(out, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  → {out}")


# ──────────────────────────────────────────────────────────────────────
# Figure 1 — Rep counting
# Schmitt-trigger hysteresis on vy with rerack/post-motion gating.
# ──────────────────────────────────────────────────────────────────────
def fig_rep_counting():
    print("Figure 1 · Rep counting")
    csv = os.path.join(DATA_DIR, "M_135_10_session_20260416_131259.csv")
    df = pd.read_csv(csv)
    t, vy, gyro_mag, fs = compute_vy(df)

    raw_crossings = find_sign_changes(vy)

    V_HI = 0.25
    candidates = build_reps(vy, V_HI, fs)
    after_rerack = filter_by_rerack_gyro(candidates, gyro_mag, fs, 1.5)
    kept = filter_by_post_motion(after_rerack, vy, gyro_mag, fs, 2.0, 0.7)
    rejected = [r for r in candidates if r not in kept]
    for i, r in enumerate(kept):
        r["rep_num"] = i + 1

    fig = slide_figure(figsize=(14, 6.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.18,
                          top=0.88, bottom=0.09, left=0.06, right=0.97)
    ax0 = slide_axes(fig.add_subplot(gs[0]))
    ax1 = slide_axes(fig.add_subplot(gs[1], sharex=ax0))

    # Top: vertical velocity with hysteresis rails and rep boundaries
    ax0.fill_between(t, vy, 0, where=(vy > 0), color=SIG, alpha=0.18,
                     linewidth=0, label="concentric (+)")
    ax0.fill_between(t, vy, 0, where=(vy < 0), color=COOL, alpha=0.20,
                     linewidth=0, label="eccentric (−)")
    ax0.plot(t, vy, color=INK, lw=1.3, label="vertical velocity vy")
    ax0.axhline(0, color=GRID, lw=0.8)
    ax0.axhline(V_HI, color=SIG, lw=0.7, ls=":", alpha=0.7,
                label=f"Schmitt rails  ±{V_HI:.2f} m/s")
    ax0.axhline(-V_HI, color=SIG, lw=0.7, ls=":", alpha=0.7)

    # Raw zero-crossings (faint) — the noisy baseline before the gate
    for cr in raw_crossings:
        ax0.axvline(t[cr], color=INK_DIM, lw=0.4, ls=":", alpha=0.25)

    for r in kept:
        ax0.axvline(t[r["chest_idx"]], color=SIG, lw=1.1, alpha=0.85)
        ax0.axvline(t[r["lockout_idx"]], color=SIG, lw=1.1, ls="--",
                    alpha=0.85)
        ax0.text(t[r["peak_idx"]], r["peak_v"] + 0.06,
                 str(r["rep_num"]), color=HIGHLIGHT, fontsize=10,
                 ha="center", va="bottom", fontweight="bold")

    for r in rejected:
        ax0.axvline(t[r["chest_idx"]], color=WARM, lw=1.0, alpha=0.85)
        ax0.axvline(t[r["lockout_idx"]], color=WARM, lw=1.0, ls="--",
                    alpha=0.85)
        ax0.text(t[r["peak_idx"]], r["peak_v"] + 0.06,
                 "rerack", color=WARM, fontsize=9,
                 ha="center", va="bottom", fontweight="bold")

    ax0.set_ylabel("vy  (m/s)")
    fig.suptitle(
        f"Rep counting  ·  M · 135 lb × 10  ·  "
        f"{len(kept)} reps kept   ·   {len(rejected)} rerack-rejected   ·   "
        f"{len(raw_crossings)} raw zero-crossings",
        color=INK, fontsize=12, x=0.06, y=0.94, ha="left")

    leg = ax0.legend(loc="lower left", fontsize=9, ncol=4,
                     framealpha=0.0, labelcolor=INK)
    for txt in leg.get_texts():
        txt.set_color(INK)

    # Bottom: gyro magnitude — shows the rerack signature that gates the last rep
    ax1.plot(t, gyro_mag, color=WARM, lw=1.1, label="|gyro|  (LP 2 Hz)")
    if len(gyro_mag):
        gpk = int(np.argmax(gyro_mag))
        ax1.scatter([t[gpk]], [gyro_mag[gpk]], color=WARM, s=40,
                    zorder=5, edgecolor=BG_DARK, lw=0.8)
        ax1.annotate("rerack peak",
                     xy=(t[gpk], gyro_mag[gpk]),
                     xytext=(t[gpk] - 3, gyro_mag[gpk] - 0.4),
                     color=WARM, fontsize=9,
                     arrowprops=dict(arrowstyle="-", color=WARM, lw=0.8))
    ax1.set_ylabel("|ω|  (rad/s)")
    ax1.set_xlabel("time  (s)")
    leg2 = ax1.legend(loc="upper left", fontsize=9, framealpha=0.0,
                      labelcolor=INK)
    for txt in leg2.get_texts():
        txt.set_color(INK)

    save(fig, "01_rep_counting.png")


# ──────────────────────────────────────────────────────────────────────
# Figure 2 — Velocity + sticking point
# Per-rep vy with PCV peak, sticking valley, and the recovery resurgence.
# ──────────────────────────────────────────────────────────────────────
def fig_velocity_sticking():
    print("Figure 2 · Velocity-based metrics + sticking point")
    # 175 × 5 has the cleanest sticking-point signature (heaviest with reps).
    csv = os.path.join(DATA_DIR, "M_175_5_session_20260416_132053.csv")
    ann = csv.replace(".csv", "_annotations.csv")
    result = compute_sticking(csv, ann if os.path.exists(ann) else None,
                              method="B")
    t = result["t"]
    vy = result["vy"]
    sticking = result["sticking"]
    boundaries = result["boundaries"]

    # Pick the first 3 reps with a confirmed sticking point.
    chosen = [(s, b) for s, b in zip(sticking, boundaries) if s.has_sticking][:3]
    if len(chosen) < 3:
        chosen = list(zip(sticking, boundaries))[:3]

    fig = slide_figure(figsize=(14, 6.5))
    gs = fig.add_gridspec(1, 3, wspace=0.20,
                          top=0.86, bottom=0.10, left=0.05, right=0.98)
    axes = [slide_axes(fig.add_subplot(gs[0, i])) for i in range(3)]

    for ax, (sp, (ci, li)) in zip(axes, chosen):
        # Pad a bit before chest and after lockout for context.
        pad = int(0.25 * 1.0 / np.median(np.diff(t)))
        lo = max(0, ci - pad)
        hi = min(len(t), li + pad)
        ts = t[lo:hi] - t[ci]
        vs = vy[lo:hi]

        ax.fill_between(ts, vs, 0, where=(vs > 0), color=SIG, alpha=0.20,
                        linewidth=0)
        ax.fill_between(ts, vs, 0, where=(vs < 0), color=COOL, alpha=0.18,
                        linewidth=0)
        ax.plot(ts, vs, color=INK, lw=1.4)
        ax.axhline(0, color=GRID, lw=0.7)

        # Mark chest and lockout boundaries
        ax.axvline(0, color=SIG, lw=1.0, alpha=0.85)
        ax.axvline(t[li] - t[ci], color=SIG, lw=1.0, ls="--", alpha=0.85)

        # PCV peak
        ax.scatter([sp.pcv_t - t[ci]], [sp.pcv], color=HIGHLIGHT, s=70,
                   zorder=5, edgecolor=BG_DARK, lw=1.2, label="drive peak (PCV)")
        ax.annotate(f"PCV {sp.pcv:.2f} m/s",
                    xy=(sp.pcv_t - t[ci], sp.pcv),
                    xytext=(sp.pcv_t - t[ci] + 0.15, sp.pcv + 0.18),
                    color=HIGHLIGHT, fontsize=9,
                    arrowprops=dict(arrowstyle="-", color=HIGHLIGHT, lw=0.7))

        # Sticking point
        if sp.has_sticking:
            ax.scatter([sp.sp_t - t[ci]], [sp.sp_v], color=WARM, s=70,
                       zorder=5, edgecolor=BG_DARK, lw=1.2,
                       label="sticking point")
            # Arrow showing depth between PCV and sp
            ax.annotate("", xy=(sp.sp_t - t[ci], sp.sp_v),
                        xytext=(sp.sp_t - t[ci], sp.pcv),
                        arrowprops=dict(arrowstyle="<->", color=WARM, lw=1.0,
                                        alpha=0.8))
            ax.text(sp.sp_t - t[ci] + 0.05,
                    0.5 * (sp.pcv + sp.sp_v),
                    f"depth {sp.sp_depth:.2f}",
                    color=WARM, fontsize=9, va="center")

            ax.text(sp.sp_t - t[ci], sp.sp_v - 0.20,
                    f"{sp.sp_frac*100:.0f}% of CD",
                    color=WARM, fontsize=8.5, ha="center")

        ax.set_ylim(-1.0, 1.2)
        ax.set_xlabel("time since chest  (s)")
        ax.set_ylabel("vy  (m/s)")
        ax.set_title(f"rep {sp.num}", loc="left", pad=6, fontsize=11)

    leg = axes[0].legend(loc="lower right", fontsize=9, framealpha=0.0,
                         labelcolor=INK)
    for txt in leg.get_texts():
        txt.set_color(INK)

    fig.suptitle(
        "Velocity-based metrics & sticking point  ·  M · 175 lb × 5  ·  "
        "find_peaks → drive peak, deepest valley, depth ≥ 0.04 m/s",
        color=INK, fontsize=12, x=0.05, y=0.94, ha="left")

    save(fig, "02_velocity_sticking.png")


# ──────────────────────────────────────────────────────────────────────
# Figure 3 — 1RM via load-velocity profile
# Best MPV per set + OLS line + bootstrap 95% CI band, projected to MVT.
# ──────────────────────────────────────────────────────────────────────
def fig_one_rm():
    print("Figure 3 · 1RM via load-velocity profile")
    LOADS = [(135, 10), (155, 8), (175, 5), (185, 3)]
    LIFTERS = {"D": "Lifter D", "M": "Lifter M"}
    MVT = 0.17  # m/s

    fig = slide_figure(figsize=(14, 6.5))
    gs = fig.add_gridspec(1, 2, wspace=0.22,
                          top=0.86, bottom=0.10, left=0.05, right=0.98)

    for col, (code, label) in enumerate(LIFTERS.items()):
        ax = slide_axes(fig.add_subplot(gs[0, col]))

        all_loads_kg = []
        all_mpv = []
        best_per_set = []

        for load_lb, reps in LOADS:
            import glob
            pattern = os.path.join(
                DATA_DIR, f"{code}_{load_lb}_{reps}_session_*.csv")
            matches = [m for m in glob.glob(pattern)
                       if "annotations" not in m and "_bad_" not in m]
            if not matches:
                continue
            csv = matches[0]
            ann = csv.replace(".csv", "_annotations.csv")
            res = compute_metrics(csv, ann if os.path.exists(ann) else None,
                                  method="B", use_detector=True,
                                  snap=os.path.exists(ann))
            mpv_vals = [r.mpv for r in res["reps"]
                        if r.mpv is not None and not np.isnan(r.mpv)]
            if not mpv_vals:
                continue
            load_kg = load_lb * 0.453592
            all_loads_kg.extend([load_kg] * len(mpv_vals))
            all_mpv.extend(mpv_vals)
            best_per_set.append((load_kg, max(mpv_vals)))

            # Plot every rep faintly
            ax.scatter([load_kg] * len(mpv_vals), mpv_vals,
                       color=SIG_DIM, s=20, alpha=0.55, zorder=2)

        if not best_per_set:
            continue

        bx = np.array([p[0] for p in best_per_set])
        by = np.array([p[1] for p in best_per_set])

        # OLS on (load, best MPV)
        slope, intercept = np.polyfit(bx, by, 1)
        # 1RM @ MVT
        one_rm_kg = (MVT - intercept) / slope if slope != 0 else np.nan
        # R²
        pred = slope * bx + intercept
        ss_res = np.sum((by - pred) ** 2)
        ss_tot = np.sum((by - np.mean(by)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Bootstrap CI on the 1RM estimate (resample per-rep MPV pool by load).
        # Reject pathological fits (near-zero slope blows up the projection).
        rng = np.random.default_rng(7)
        all_loads_kg_arr = np.array(all_loads_kg)
        all_mpv_arr = np.array(all_mpv)
        bs_one_rm = []
        for _ in range(2000):
            samp_best = []
            for L in np.unique(all_loads_kg_arr):
                pool = all_mpv_arr[all_loads_kg_arr == L]
                draws = rng.choice(pool, size=len(pool), replace=True)
                samp_best.append((L, np.max(draws)))
            xb = np.array([p[0] for p in samp_best])
            yb = np.array([p[1] for p in samp_best])
            s, b = np.polyfit(xb, yb, 1)
            pred_b = s * xb + b
            ss_res_b = np.sum((yb - pred_b) ** 2)
            ss_tot_b = np.sum((yb - np.mean(yb)) ** 2)
            r2_b = 1 - ss_res_b / ss_tot_b if ss_tot_b > 0 else 0.0
            if s < -0.0015 and r2_b >= 0.50:
                bs_one_rm.append((MVT - b) / s)
        bs_one_rm = np.array(bs_one_rm)
        if len(bs_one_rm):
            ci_lo, ci_hi = np.percentile(bs_one_rm, [2.5, 97.5])
        else:
            ci_lo = ci_hi = one_rm_kg

        # Plot the regression line out to projected 1RM
        x_max = max(one_rm_kg, bx.max()) * 1.05
        x_min = min(bx.min() * 0.85, 40)
        xs = np.linspace(x_min, x_max, 200)
        ys = slope * xs + intercept
        ax.plot(xs, ys, color=SIG, lw=1.6, label=f"OLS  R² = {r2:.2f}")

        # Bootstrap CI band — sample slope/intercept pairs (only well-formed)
        bs_lines = []
        for _ in range(800):
            samp_best = []
            for L in np.unique(all_loads_kg_arr):
                pool = all_mpv_arr[all_loads_kg_arr == L]
                draws = rng.choice(pool, size=len(pool), replace=True)
                samp_best.append((L, np.max(draws)))
            xb = np.array([p[0] for p in samp_best])
            yb = np.array([p[1] for p in samp_best])
            s, b = np.polyfit(xb, yb, 1)
            pred_b = s * xb + b
            ss_res_b = np.sum((yb - pred_b) ** 2)
            ss_tot_b = np.sum((yb - np.mean(yb)) ** 2)
            r2_b = 1 - ss_res_b / ss_tot_b if ss_tot_b > 0 else 0.0
            if s < -0.0015 and r2_b >= 0.50:
                bs_lines.append(s * xs + b)
        if len(bs_lines) < 20:
            bs_lines = [slope * xs + intercept]
        bs_lines = np.array(bs_lines)
        lo = np.percentile(bs_lines, 2.5, axis=0)
        hi = np.percentile(bs_lines, 97.5, axis=0)
        ax.fill_between(xs, lo, hi, color=SIG, alpha=0.10, linewidth=0,
                        label="95% bootstrap CI")

        # Best-per-set markers
        ax.scatter(bx, by, color=SIG, s=70, zorder=5,
                   edgecolor=BG_DARK, lw=1.2, label="best MPV per set")

        # MVT line and projected 1RM
        ax.axhline(MVT, color=WARM, lw=1.0, ls="--", alpha=0.85,
                   label=f"MVT  {MVT} m/s")
        ax.scatter([one_rm_kg], [MVT], color=HIGHLIGHT, s=110, marker="*",
                   zorder=6, edgecolor=BG_DARK, lw=1.2,
                   label="projected 1RM")
        xerr_lo = max(0.0, one_rm_kg - ci_lo)
        xerr_hi = max(0.0, ci_hi - one_rm_kg)
        ax.errorbar([one_rm_kg], [MVT],
                    xerr=[[xerr_lo], [xerr_hi]],
                    fmt="none", ecolor=HIGHLIGHT, elinewidth=1.5,
                    capsize=4, alpha=0.85)

        one_rm_lb = one_rm_kg / 0.453592
        ci_lo_lb = ci_lo / 0.453592
        ci_hi_lb = ci_hi / 0.453592
        ax.text(one_rm_kg, MVT - 0.10,
                f"1RM ≈ {one_rm_lb:.0f} lb\n95% CI [{ci_lo_lb:.0f}, {ci_hi_lb:.0f}]",
                color=HIGHLIGHT, fontsize=10, ha="center", va="top",
                fontweight="bold")

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(0.0, max(by.max(), 1.0) * 1.2)
        ax.set_xlabel("load  (kg)")
        ax.set_ylabel("MPV  (m/s)")
        ax.text(0.02, 0.96, label, transform=ax.transAxes,
                color=INK, fontsize=12, fontweight="bold", va="top")

        leg = ax.legend(loc="upper right", fontsize=8.5, framealpha=0.0,
                        labelcolor=INK)
        for txt in leg.get_texts():
            txt.set_color(INK)

    fig.suptitle(
        "1RM via load-velocity profile  ·  best MPV per set  →  OLS  →  "
        "extrapolate to MVT 0.17 m/s  ·  95% bootstrap CI",
        color=INK, fontsize=12, x=0.05, y=0.94, ha="left")

    save(fig, "03_one_rm.png")


# ──────────────────────────────────────────────────────────────────────
# Figure 4 — Bar path regeneration
# Per-rep 2D (forward, vertical) trajectories with reference J-curve overlay.
# ──────────────────────────────────────────────────────────────────────
def fig_bar_path():
    print("Figure 4 · Bar path regeneration")
    csv = os.path.join(DATA_DIR, "M_175_5_session_20260416_132053.csv")
    result = reconstruct_csv(csv)
    reps = result.reps

    fig = slide_figure(figsize=(14, 6.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 2], wspace=0.22,
                          top=0.86, bottom=0.10, left=0.05, right=0.98)
    ax0 = slide_axes(fig.add_subplot(gs[0]))
    ax1 = slide_axes(fig.add_subplot(gs[1]))

    # ---- Left: every rep's trajectory overlaid on common axes ----
    # Convention: x = forward(+) / back(−), z = up(+) / down(−).
    # The reconstruct returns each rep as 0-anchored at lockout, descending
    # ECC into chest, then ascending CON back to lockout. We plot meters → cm.
    cmap = plt.cm.viridis(np.linspace(0.30, 0.95, max(1, len(reps))))
    for i, rep in enumerate(reps):
        x = np.asarray(rep.x_m) * 100.0   # forward/back, cm
        z = np.asarray(rep.z_m) * 100.0   # vertical, cm  (z up positive)
        ax0.plot(x, z, color=SIG, lw=1.2, alpha=0.55,
                 label="recorded reps" if i == 0 else None)

    # Mean path
    if reps:
        xs = np.stack([np.asarray(r.x_m) for r in reps]) * 100.0
        zs = np.stack([np.asarray(r.z_m) for r in reps]) * 100.0
        ax0.plot(xs.mean(0), zs.mean(0), color=INK, lw=2.0,
                 label="session mean")

        # Overlay a "reference J-curve" template (eccentric arc only, sized
        # to the recorded ROM and forward excursion). Same parametric form
        # as the front-end overlay — a half-ellipse with a small lateral
        # bulge, normalized to the lifter's own geometry. Not derived from
        # population data; it's a coaching reference shape.
        rom = abs(zs.mean(0).min())                  # cm
        x_at_chest = float(xs.mean(0)[np.argmin(zs.mean(0))])
        xmax = x_at_chest                            # signed; carries direction
        x_sign = 1.0 if xmax >= 0 else -1.0
        xs_t, zs_t = [], []
        N = 80
        for k in range(N):
            tau = (k / (N - 1)) * np.pi   # J-curve only (eccentric portion)
            along = (1 - np.cos(tau)) / 2
            perp = np.sin(tau) / 2
            xs_t.append(along * xmax + perp * 0.05 * rom * x_sign)
            zs_t.append(-along * rom + perp * 0.05 * abs(xmax))
        ax0.plot(xs_t, zs_t, color=WARM, lw=1.4, ls="--", alpha=0.9,
                 label="reference J-curve")

    ax0.set_xlabel("forward / back  (cm)")
    ax0.set_ylabel("vertical  (cm,  0 = lockout)")
    ax0.text(0.02, 0.96, "trajectory overlay", transform=ax0.transAxes,
             color=INK, fontsize=11, fontweight="bold", va="top")
    leg = ax0.legend(loc="lower right", fontsize=9.5, framealpha=0.0,
                     labelcolor=INK)
    for txt in leg.get_texts():
        txt.set_color(INK)
    ax0.set_aspect("equal", adjustable="datalim")

    # ---- Right: per-rep ROM consistency ----
    # Endpoint anchoring forces |end − start| = 0 by construction, so it's
    # not a useful diagnostic. ROM (vertical excursion) IS — its tightness
    # across the set is what tells us the integration is internally
    # consistent, and it directly maps to "did the lifter actually press
    # to lockout". Forward excursion at chest is the second axis.
    if reps:
        rom_cm = [abs(r.rom_m) * 100.0 for r in reps]
        x_cm = [r.peak_x_dev_m * 100.0 for r in reps]
        nums = [r.num for r in reps]

        width = 0.38
        offsets = np.arange(len(nums))
        ax1.bar(offsets - width/2, rom_cm, width, color=SIG, alpha=0.90,
                edgecolor=BG_DARK, linewidth=1.0, label="vertical ROM")
        ax1.bar(offsets + width/2, x_cm, width, color=COOL, alpha=0.85,
                edgecolor=BG_DARK, linewidth=1.0, label="forward excursion")
        ax1.set_xticks(offsets)
        ax1.set_xticklabels(nums)
        ax1.set_xlabel("rep #")
        ax1.set_ylabel("cm")
        ax1.set_ylim(0, max(max(rom_cm), max(x_cm)) * 1.45)

        rom_mean = float(np.mean(rom_cm))
        rom_std = float(np.std(rom_cm))
        ax1.text(0.02, 0.97, "per-rep geometry consistency",
                 transform=ax1.transAxes, color=INK, fontsize=11,
                 fontweight="bold", va="top")
        ax1.text(0.02, 0.89,
                 f"ROM = {rom_mean:.1f} ± {rom_std:.1f} cm",
                 transform=ax1.transAxes, color=INK_DIM, fontsize=9.5,
                 va="top")

        leg2 = ax1.legend(loc="upper right", fontsize=9.5, framealpha=0.0,
                          labelcolor=INK)
        for txt in leg2.get_texts():
            txt.set_color(INK)

    fig.suptitle(
        "Bar path  ·  M · 175 lb × 5  ·  "
        f"{len(reps)} reps  ·  full-cycle integration with endpoint anchoring",
        color=INK, fontsize=12, x=0.05, y=0.94, ha="left")

    save(fig, "04_bar_path.png")


def main():
    fig_rep_counting()
    fig_velocity_sticking()
    fig_one_rm()
    fig_bar_path()
    print("\nDone. Figures in", OUT_DIR)


if __name__ == "__main__":
    main()
