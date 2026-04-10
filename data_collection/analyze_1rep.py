#!/usr/bin/env python3
"""
IMU Barbell Single-Rep Analysis — First Rep Bar Path
=====================================================
Extracts the first rep from a bench press session and generates a focused
HTML dashboard showing bar path, velocity phases, and summary stats.

Designed for 1RM / heavy single analysis where you care about one rep.

Usage:
    python3 analyze_1rep.py <csv_file> [--exercise "Bench Press"] [--load 135]
    python3 analyze_1rep.py <csv_file> --output my_report.html
"""

import sys, os
import argparse
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import plotly.io as pio

# ── PARSE ARGS ──────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Analyze first rep bar path from IMU data")
parser.add_argument("csv", help="Path to session CSV file")
parser.add_argument("--exercise", "-e", type=str, default="Bench Press",
                    help="Exercise type (default: Bench Press)")
parser.add_argument("--load", "-l", type=float, default=45,
                    help="Load in lbs including bar weight (default: 45)")
parser.add_argument("--output", "-o", type=str, default=None,
                    help="Output HTML path (default: <csv_name>_1rep.html)")
parser.add_argument("--rate", type=int, default=200,
                    help="Sample rate in Hz (default: 200)")
args = parser.parse_args()

CSV_PATH = args.csv
EXERCISE = args.exercise
LOAD_LBS = args.load
SAMPLE_RATE = args.rate
GRAVITY = 9.81

# Output path
if args.output:
    OUTPUT_PATH = args.output
else:
    base = os.path.splitext(os.path.basename(CSV_PATH))[0]
    OUTPUT_PATH = os.path.join(os.path.dirname(CSV_PATH) or ".", f"{base}_1rep.html")

# Filter params
LP_CUTOFF = 15     # Hz
FILTER_ORDER = 4
HP_CUTOFF = 0.3    # Hz, for drift removal on velocity

# ── HELPERS ─────────────────────────────────────────────────────────

def butter_filter(data, cutoff, fs, order=4, btype='low'):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff / nyq, btype=btype)
    return filtfilt(b, a, data)


def _import_ekf(csv_path):
    """Find and import the EKF module relative to the project structure."""
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    search = csv_dir
    for _ in range(5):
        candidate = os.path.join(search, 'src')
        if os.path.isdir(os.path.join(candidate, 'bar_path')):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            from bar_path.ekf import estimate_per_rep_bar_path
            return estimate_per_rep_bar_path
        search = os.path.dirname(search)
    raise ImportError("Could not find src/bar_path/ekf.py")


estimate_per_rep_bar_path = _import_ekf(CSV_PATH)

# ── LOAD DATA ──────────────────────────────────────────────────────

print(f"Loading {CSV_PATH}...")
df = pd.read_csv(CSV_PATH)
n_samples = len(df)
print(f"  {n_samples} samples, {n_samples/SAMPLE_RATE:.1f}s duration")

t_ms = df['timestamp_ms'].values.astype(float)
t_s = t_ms / 1000.0
dt = 1.0 / SAMPLE_RATE

ax_raw = df['a1x'].values.astype(float)
ay_raw = df['a1y'].values.astype(float)
az_raw = df['a1z'].values.astype(float)
gx_raw = df['g1x'].values.astype(float)
gy_raw = df['g1y'].values.astype(float)
gz_raw = df['g1z'].values.astype(float)

# ── SIGNAL PROCESSING ──────────────────────────────────────────────

print("Processing signals...")

# Low-pass filter
ax_f = butter_filter(ax_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
ay_f = butter_filter(ay_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
az_f = butter_filter(az_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
gx_f = butter_filter(gx_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
gy_f = butter_filter(gy_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
gz_f = butter_filter(gz_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)

# Remove gravity (calibration-based)
cal_n = min(SAMPLE_RATE, len(ax_raw))
grav_vec = np.array([np.mean(ax_raw[:cal_n]), np.mean(ay_raw[:cal_n]), np.mean(az_raw[:cal_n])])
grav_axis = np.argmax(np.abs(grav_vec))
grav_sign = np.sign(grav_vec[grav_axis])

gx_cal = np.mean(ax_f[:cal_n])
gy_cal = np.mean(ay_f[:cal_n])
gz_cal = np.mean(az_f[:cal_n])
ax_lin = ax_f - gx_cal
ay_lin = ay_f - gy_cal
az_lin = az_f - gz_cal

# ── DETECT FIRST REP ──────────────────────────────────────────────

print("Detecting first rep...")

# Vertical velocity via HP integration (for rep detection)
from scipy.integrate import cumulative_trapezoid

lin_accels = [ax_lin, ay_lin, az_lin]
v_vert_raw = cumulative_trapezoid(lin_accels[grav_axis], dx=dt, initial=0)
v_vert_hp = butter_filter(v_vert_raw, HP_CUTOFF, SAMPLE_RATE, btype='high')
v_vert_smooth = butter_filter(v_vert_hp, 5.0, SAMPLE_RATE, 2)

# Concentric = upward velocity along gravity axis
concentric_sign = grav_sign
detect_signal = v_vert_smooth * concentric_sign

min_dist_samples = int(1.5 * SAMPLE_RATE)
peaks, peak_props = find_peaks(
    detect_signal,
    distance=min_dist_samples,
    prominence=0.05,
    height=0.1
)

if len(peaks) == 0:
    print("ERROR: No reps detected in the data.")
    sys.exit(1)

# Zero crossings of vertical velocity
zero_crossings = np.where(np.diff(np.sign(v_vert_smooth)))[0]

# Build all rep candidates (same logic as analyze_session.py)
candidates = []
for pk in peaks:
    before_zc = zero_crossings[zero_crossings < pk]
    after_zc = zero_crossings[zero_crossings > pk]
    if len(before_zc) > 0 and len(after_zc) > 0:
        start = before_zc[-1]
        end = after_zc[0]
        duration = (end - start) / SAMPLE_RATE
        peak_v = float(detect_signal[pk])
        candidates.append({
            'conc_start': start, 'conc_end': end,
            'peak_idx': pk, 'peak_v': peak_v, 'duration': duration,
        })

# Remove overlapping candidates
deduped = []
for c in candidates:
    if not deduped or c['conc_start'] > deduped[-1]['conc_end']:
        deduped.append(c)

# Adaptive threshold: reject unrack/rerack (peak velocity < 40% of median)
if len(deduped) >= 3:
    median_peak_v = float(np.median(sorted([c['peak_v'] for c in deduped])))
    vel_threshold = median_peak_v * 0.40
    real_reps = [c for c in deduped if c['peak_v'] >= vel_threshold]
    rejected = len(deduped) - len(real_reps)
    if rejected > 0:
        print(f"  Rejected {rejected} candidate(s) (unrack/rerack/partial)")
else:
    real_reps = deduped

if len(real_reps) == 0:
    print("ERROR: No valid reps detected after filtering.")
    sys.exit(1)

print(f"  Found {len(real_reps)} total reps, using first")

# Use the first real rep
first = real_reps[0]
conc_start = first['conc_start']
conc_end = first['conc_end']

# Extend backward to find eccentric start (previous zero crossing before conc_start)
ecc_starts = zero_crossings[zero_crossings < conc_start]
if len(ecc_starts) > 0:
    full_start = ecc_starts[-1]
else:
    full_start = conc_start

# The full rep: eccentric start -> concentric end
rep_start = full_start
rep_end = conc_end
turnaround_idx = conc_start  # transition from eccentric to concentric

rep_t_start = t_s[rep_start]
rep_t_end = t_s[rep_end]
rep_duration = rep_t_end - rep_t_start

print(f"  First rep: {rep_t_start:.2f}s - {rep_t_end:.2f}s ({rep_duration:.2f}s)")
print(f"  Eccentric: {rep_t_start:.2f}s - {t_s[turnaround_idx]:.2f}s")
print(f"  Concentric: {t_s[turnaround_idx]:.2f}s - {rep_t_end:.2f}s")

# ── RUN EKF BAR PATH ──────────────────────────────────────────────

print("Running EKF for bar path reconstruction...")

accel_data = np.column_stack([ax_f, ay_f, az_f])
gyro_data = np.column_stack([gx_f, gy_f, gz_f])

ekf_results = estimate_per_rep_bar_path(
    accel_data, gyro_data, SAMPLE_RATE,
    [rep_start], [rep_end]
)

ekf_rep = ekf_results[0]
pos = ekf_rep['position']   # (N, 3) in meters
vel = ekf_rep['velocity']   # (N, 3) in m/s

# Extract axes: X = horizontal (negate for forward = positive), Y = vertical
h_m = -pos[:, 0]   # horizontal: -X in sensor frame = forward
v_m = pos[:, 1]     # vertical: Y in sensor frame = up
h_cm = h_m * 100
v_cm = v_m * 100

# Time array for the rep
rep_n = rep_end - rep_start
rep_t = np.linspace(0, rep_duration, rep_n)

# Velocity components
vel_vert = vel[:, 1]                  # vertical velocity (m/s)
vel_horiz = -vel[:, 0]               # horizontal velocity (m/s)

# Turnaround = lowest vertical point (chest contact)
chest_idx = np.argmin(v_cm)
ecc_duration = chest_idx / SAMPLE_RATE
conc_duration = (rep_n - chest_idx) / SAMPLE_RATE
chest_pct = chest_idx / rep_n * 100

# ── COMPUTE METRICS ───────────────────────────────────────────────

vertical_rom = float(np.ptp(v_cm))
horizontal_rom = float(np.ptp(h_cm))
peak_ecc_vel = float(np.min(vel_vert[:chest_idx])) if chest_idx > 0 else 0.0
peak_conc_vel = float(np.max(vel_vert[chest_idx:])) if chest_idx < rep_n else 0.0
mean_conc_vel = float(np.mean(np.abs(vel_vert[chest_idx:]))) if chest_idx < rep_n else 0.0

# Chest position relative to start
chest_h = float(h_cm[chest_idx])
chest_v = float(v_cm[chest_idx])

# End position (should be near start)
end_h = float(h_cm[-1])
end_v = float(v_cm[-1])

print(f"  Vertical ROM: {vertical_rom:.1f} cm")
print(f"  Horizontal ROM: {horizontal_rom:.1f} cm")
print(f"  Peak eccentric velocity: {peak_ecc_vel:.3f} m/s")
print(f"  Peak concentric velocity: {peak_conc_vel:.3f} m/s")
print(f"  Chest contact at {chest_pct:.0f}% of rep ({ecc_duration:.2f}s)")

# ── RAW ACCEL FOR THE REP ─────────────────────────────────────────

rep_ax = ax_f[rep_start:rep_end]
rep_ay = ay_f[rep_start:rep_end]
rep_az = az_f[rep_start:rep_end]

# ── BUILD DASHBOARD ────────────────────────────────────────────────

print("Building dashboard...")

# Theme (matches analyze_session.py)
BG = "#0f1117"
CARD_BG = "#1a1d27"
TEXT = "#e0e0e0"
ACCENT = "#4ecdc4"
ACCENT2 = "#ff6b6b"
ACCENT3 = "#ffe66d"
ACCENT4 = "#a8e6cf"
GRID = "#2a2d37"

ECC_COLOR = ACCENT2     # red for eccentric (descent)
CONC_COLOR = ACCENT     # teal for concentric (press)
MARKER_COLOR = ACCENT3  # yellow for markers

fig = make_subplots(
    rows=3, cols=2,
    subplot_titles=(
        "Bar Path (Front View)",
        "Vertical Position over Time",
        "Horizontal Position over Time",
        "Vertical Velocity over Time",
        "Raw Accelerometer (Filtered)",
        "",  # summary stats go in annotation
    ),
    specs=[
        [{"rowspan": 1}, {}],
        [{}, {}],
        [{}, {}],
    ],
    vertical_spacing=0.08,
    horizontal_spacing=0.08,
)

# ── 1. Bar Path (X vs Y) ──────────────────────────────────────────

# Eccentric phase (start to chest)
fig.add_trace(go.Scatter(
    x=h_cm[:chest_idx+1], y=v_cm[:chest_idx+1],
    mode='lines', name='Eccentric (descent)',
    line=dict(width=3, color=ECC_COLOR),
    hovertemplate='H: %{x:.1f} cm<br>V: %{y:.1f} cm<extra>Eccentric</extra>',
), row=1, col=1)

# Concentric phase (chest to lockout)
fig.add_trace(go.Scatter(
    x=h_cm[chest_idx:], y=v_cm[chest_idx:],
    mode='lines', name='Concentric (press)',
    line=dict(width=3, color=CONC_COLOR),
    hovertemplate='H: %{x:.1f} cm<br>V: %{y:.1f} cm<extra>Concentric</extra>',
), row=1, col=1)

# Markers: lockout start, chest, lockout end
fig.add_trace(go.Scatter(
    x=[h_cm[0]], y=[v_cm[0]], mode='markers+text',
    marker=dict(size=12, color=MARKER_COLOR, symbol='circle'),
    text=['Lockout'], textposition='top right',
    textfont=dict(color=MARKER_COLOR, size=11),
    name='Lockout (start)', showlegend=False,
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=[chest_h], y=[chest_v], mode='markers+text',
    marker=dict(size=12, color=ACCENT2, symbol='diamond'),
    text=['Chest'], textposition='bottom center',
    textfont=dict(color=ACCENT2, size=11),
    name='Chest', showlegend=False,
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=[h_cm[-1]], y=[v_cm[-1]], mode='markers+text',
    marker=dict(size=12, color=CONC_COLOR, symbol='star'),
    text=['Lockout'], textposition='top left',
    textfont=dict(color=CONC_COLOR, size=11),
    name='Lockout (end)', showlegend=False,
), row=1, col=1)

# ── 2. Vertical Position over Time ────────────────────────────────

fig.add_trace(go.Scatter(
    x=rep_t[:chest_idx+1], y=v_cm[:chest_idx+1],
    mode='lines', name='Ecc', line=dict(width=2, color=ECC_COLOR),
    showlegend=False,
), row=1, col=2)

fig.add_trace(go.Scatter(
    x=rep_t[chest_idx:], y=v_cm[chest_idx:],
    mode='lines', name='Conc', line=dict(width=2, color=CONC_COLOR),
    showlegend=False,
), row=1, col=2)

# Mark chest contact
fig.add_vline(
    x=rep_t[chest_idx], line_dash="dash", line_color=ACCENT3, opacity=0.6,
    row=1, col=2, annotation_text="Chest",
    annotation_font_color=ACCENT3, annotation_font_size=10,
)

# ── 3. Horizontal Position over Time ──────────────────────────────

fig.add_trace(go.Scatter(
    x=rep_t[:chest_idx+1], y=h_cm[:chest_idx+1],
    mode='lines', name='Ecc H', line=dict(width=2, color=ECC_COLOR),
    showlegend=False,
), row=2, col=1)

fig.add_trace(go.Scatter(
    x=rep_t[chest_idx:], y=h_cm[chest_idx:],
    mode='lines', name='Conc H', line=dict(width=2, color=CONC_COLOR),
    showlegend=False,
), row=2, col=1)

fig.add_vline(
    x=rep_t[chest_idx], line_dash="dash", line_color=ACCENT3, opacity=0.6,
    row=2, col=1,
)

# ── 4. Vertical Velocity over Time ────────────────────────────────

fig.add_trace(go.Scatter(
    x=rep_t, y=vel_vert,
    mode='lines', name='Vertical Velocity',
    line=dict(width=2, color=TEXT),
    showlegend=False,
), row=2, col=2)

# Shade eccentric (negative velocity) and concentric (positive)
fig.add_vrect(
    x0=rep_t[0], x1=rep_t[chest_idx],
    fillcolor=ECC_COLOR, opacity=0.1, line_width=0,
    row=2, col=2, annotation_text="Eccentric",
    annotation_position="top left",
    annotation_font_color=ECC_COLOR, annotation_font_size=10,
)
fig.add_vrect(
    x0=rep_t[chest_idx], x1=rep_t[-1],
    fillcolor=CONC_COLOR, opacity=0.1, line_width=0,
    row=2, col=2, annotation_text="Concentric",
    annotation_position="top right",
    annotation_font_color=CONC_COLOR, annotation_font_size=10,
)

fig.add_hline(y=0, line_dash="dot", line_color=GRID, opacity=0.5, row=2, col=2)

# ── 5. Raw Accelerometer ──────────────────────────────────────────

for data, name, color in [(rep_ax, 'Accel X', ACCENT), (rep_ay, 'Accel Y', ACCENT2), (rep_az, 'Accel Z', ACCENT3)]:
    fig.add_trace(go.Scatter(
        x=rep_t, y=data, mode='lines', name=name,
        line=dict(width=1, color=color),
    ), row=3, col=1)

fig.add_vline(
    x=rep_t[chest_idx], line_dash="dash", line_color=ACCENT3, opacity=0.6,
    row=3, col=1,
)

# ── 6. Summary Stats (as a table in the last subplot area) ────────

stats_text = (
    f"<b>Rep Summary</b><br>"
    f"<br>"
    f"<span style='color:{ACCENT}'>Duration:</span> {rep_duration:.2f}s<br>"
    f"<span style='color:{ACCENT}'>  Eccentric:</span> {ecc_duration:.2f}s<br>"
    f"<span style='color:{ACCENT}'>  Concentric:</span> {conc_duration:.2f}s<br>"
    f"<span style='color:{ACCENT}'>  Chest at:</span> {chest_pct:.0f}% of rep<br>"
    f"<br>"
    f"<span style='color:{ACCENT2}'>Vertical ROM:</span> {vertical_rom:.1f} cm<br>"
    f"<span style='color:{ACCENT2}'>Horizontal ROM:</span> {horizontal_rom:.1f} cm<br>"
    f"<br>"
    f"<span style='color:{ACCENT3}'>Peak Ecc Vel:</span> {abs(peak_ecc_vel):.3f} m/s<br>"
    f"<span style='color:{ACCENT3}'>Peak Conc Vel:</span> {peak_conc_vel:.3f} m/s<br>"
    f"<span style='color:{ACCENT3}'>Mean Conc Vel:</span> {mean_conc_vel:.3f} m/s<br>"
    f"<br>"
    f"<span style='color:{ACCENT4}'>Chest Position:</span><br>"
    f"  H={chest_h:+.1f} cm, V={chest_v:.1f} cm"
)

fig.add_annotation(
    text=stats_text,
    xref="x6", yref="y6",
    x=0.5, y=0.5,
    showarrow=False,
    font=dict(size=13, color=TEXT, family="monospace"),
    align="left",
    bgcolor=CARD_BG,
    bordercolor=ACCENT,
    borderwidth=1,
    borderpad=15,
    row=3, col=2,
)

# Hide axes for stats panel
fig.update_xaxes(visible=False, row=3, col=2)
fig.update_yaxes(visible=False, row=3, col=2)

# ── LAYOUT ─────────────────────────────────────────────────────────

fig.update_layout(
    height=1000,
    width=1200,
    paper_bgcolor=BG,
    plot_bgcolor=CARD_BG,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
    title=dict(
        text=(
            f"<b>First Rep Analysis</b> — {EXERCISE} @ {LOAD_LBS:.0f} lbs"
            f"<br><span style='font-size:13px; color:{ACCENT}'>"
            f"t = {rep_t_start:.2f}s - {rep_t_end:.2f}s | "
            f"ROM = {vertical_rom:.1f} cm | "
            f"Peak Conc = {peak_conc_vel:.3f} m/s</span>"
        ),
        font=dict(size=20),
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0.3)",
        bordercolor=GRID,
        borderwidth=1,
        font=dict(size=11),
    ),
    showlegend=True,
)

# Axis labels
fig.update_xaxes(title_text="Horizontal (cm, + = forward)", gridcolor=GRID, row=1, col=1)
fig.update_yaxes(title_text="Vertical (cm)", gridcolor=GRID, row=1, col=1)
fig.update_xaxes(title_text="Time (s)", gridcolor=GRID, row=1, col=2)
fig.update_yaxes(title_text="Vertical (cm)", gridcolor=GRID, row=1, col=2)
fig.update_xaxes(title_text="Time (s)", gridcolor=GRID, row=2, col=1)
fig.update_yaxes(title_text="Horizontal (cm)", gridcolor=GRID, row=2, col=1)
fig.update_xaxes(title_text="Time (s)", gridcolor=GRID, row=2, col=2)
fig.update_yaxes(title_text="Velocity (m/s)", gridcolor=GRID, row=2, col=2)
fig.update_xaxes(title_text="Time (s)", gridcolor=GRID, row=3, col=1)
fig.update_yaxes(title_text="Accel (m/s²)", gridcolor=GRID, row=3, col=1)

# Equal aspect ratio for bar path plot
fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)

# ── WRITE HTML ─────────────────────────────────────────────────────

plot_div = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>First Rep Analysis — {EXERCISE} @ {LOAD_LBS:.0f} lbs</title>
<style>
  body {{ margin: 0; background: {BG}; }}
</style>
</head>
<body>
<div style="font-family: Inter, system-ui, sans-serif; background: {BG}; color: {TEXT}; padding: 30px;">
<h1 style="color: {ACCENT}; text-align: center;">First Rep Analysis — {EXERCISE} @ {LOAD_LBS:.0f} lbs</h1>

<div style="display: flex; gap: 15px; justify-content: center; margin: 20px 0; flex-wrap: wrap;">
  <div style="background: {CARD_BG}; padding: 18px 25px; border-radius: 12px; text-align: center;">
    <div style="font-size: 32px; font-weight: bold; color: {ACCENT};">{rep_duration:.2f}s</div>
    <div style="color: {TEXT}; opacity: 0.7;">Duration</div>
  </div>
  <div style="background: {CARD_BG}; padding: 18px 25px; border-radius: 12px; text-align: center;">
    <div style="font-size: 32px; font-weight: bold; color: {ACCENT2};">{vertical_rom:.1f} cm</div>
    <div style="color: {TEXT}; opacity: 0.7;">Vertical ROM</div>
  </div>
  <div style="background: {CARD_BG}; padding: 18px 25px; border-radius: 12px; text-align: center;">
    <div style="font-size: 32px; font-weight: bold; color: {ACCENT3};">{horizontal_rom:.1f} cm</div>
    <div style="color: {TEXT}; opacity: 0.7;">Horizontal ROM</div>
  </div>
  <div style="background: {CARD_BG}; padding: 18px 25px; border-radius: 12px; text-align: center;">
    <div style="font-size: 32px; font-weight: bold; color: {ACCENT4};">{peak_conc_vel:.3f} m/s</div>
    <div style="color: {TEXT}; opacity: 0.7;">Peak Conc Velocity</div>
  </div>
  <div style="background: {CARD_BG}; padding: 18px 25px; border-radius: 12px; text-align: center;">
    <div style="font-size: 32px; font-weight: bold; color: {ACCENT};">{chest_pct:.0f}%</div>
    <div style="color: {TEXT}; opacity: 0.7;">Chest Contact</div>
  </div>
</div>

{plot_div}

<p style="text-align: center; opacity: 0.4; margin-top: 20px; font-size: 12px;">
  Generated from {os.path.basename(CSV_PATH)} | {n_samples} samples @ {SAMPLE_RATE} Hz |
  EKF + Mahony orientation + constrained integration
</p>
</div>
</body>
</html>"""

with open(OUTPUT_PATH, 'w') as f:
    f.write(html)

print(f"\nDashboard saved to {OUTPUT_PATH}")
print("Done.")
