#!/usr/bin/env python3
"""
IMU Barbell Session Analysis — Full Report
===========================================
Reads a single-IMU CSV (timestamp_ms, a1x, a1y, a1z, g1x, g1y, g1z),
detects reps, computes bar velocity/path, and generates an interactive
HTML dashboard with Plotly.

Usage:
    python3 analyze_session.py <csv_file> --exercise "Bench Press" --load 135
    python3 analyze_session.py <csv_file> --exercise Squat --load 225 --output my_report.html
"""

import sys, os
import argparse
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks
from scipy.integrate import cumulative_trapezoid
import plotly.graph_objects as go

# Defer EKF import until after argparse (need CSV path to find project root)
_ekf_imported = False
from plotly.subplots import make_subplots
import plotly.io as pio

# ── PARSE ARGS ──────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Analyze IMU barbell session data")
parser.add_argument("csv", help="Path to session CSV file")
parser.add_argument("--exercise", "-e", type=str, default="Bench Press",
                    help="Exercise type: 'Bench Press', 'Squat', or 'Deadlift' (default: Bench Press)")
parser.add_argument("--load", "-l", type=float, default=45,
                    help="Load in lbs including bar weight (default: 45)")
parser.add_argument("--output", "-o", type=str, default=None,
                    help="Output HTML path (default: <csv_name>_analysis.html)")
parser.add_argument("--rate", type=int, default=200,
                    help="Sample rate in Hz (default: 200)")
args = parser.parse_args()

CSV_PATH = args.csv
EXERCISE = args.exercise
LOAD_LBS = args.load
SAMPLE_RATE = args.rate
GRAVITY = 9.81  # m/s²

# MVT varies by exercise (Jidovtseff et al., Banyard et al.)
MVT_MAP = {
    "bench press": 0.17,
    "squat": 0.30,
    "deadlift": 0.15,
}
MVT = MVT_MAP.get(EXERCISE.lower(), 0.17)

# Output path
if args.output:
    OUTPUT_PATH = args.output
else:
    base = os.path.splitext(os.path.basename(CSV_PATH))[0]
    OUTPUT_PATH = os.path.join(os.path.dirname(CSV_PATH) or ".", f"{base}_analysis.html")

# Butterworth filter params
LP_CUTOFF = 15   # Hz, for accel smoothing
HP_CUTOFF = 0.3  # Hz, for drift removal on velocity
FILTER_ORDER = 4

# Rep detection params
REP_MIN_PROMINENCE = 1.5   # m/s² prominence for detecting reps
REP_MIN_DISTANCE_S = 1.0   # minimum seconds between reps
REP_MIN_DURATION_S = 0.5   # minimum rep duration

# ── HELPERS ─────────────────────────────────────────────────────────

def butter_filter(data, cutoff, fs, order=4, btype='low'):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff / nyq, btype=btype)
    return filtfilt(b, a, data)

def remove_gravity(ax, ay, az):
    """Estimate gravity direction from quiet periods and subtract."""
    # Use first 1 second as calibration (bar should be still)
    cal_n = min(SAMPLE_RATE, len(ax))
    gx = np.mean(ax[:cal_n])
    gy = np.mean(ay[:cal_n])
    gz = np.mean(az[:cal_n])
    return ax - gx, ay - gy, az - gz

def integrate_with_drift_removal(signal, dt, hp_cutoff, fs):
    """Integrate signal and high-pass filter to remove drift."""
    integrated = cumulative_trapezoid(signal, dx=dt, initial=0)
    return butter_filter(integrated, hp_cutoff, fs, btype='high')

# ── Import EKF (find src/ relative to CSV file location) ───────────

def _import_ekf(csv_path):
    """Find and import the EKF module relative to the project structure."""
    csv_dir = os.path.dirname(os.path.abspath(csv_path))
    # Walk up from CSV to find src/bar_path/
    search = csv_dir
    for _ in range(5):
        candidate = os.path.join(search, 'src')
        if os.path.isdir(os.path.join(candidate, 'bar_path')):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            from bar_path.ekf import estimate_per_rep_bar_path
            return estimate_per_rep_bar_path
        search = os.path.dirname(search)
    raise ImportError("Could not find src/bar_path/ekf.py — make sure it exists in the project")

estimate_per_rep_bar_path = _import_ekf(CSV_PATH)

# ── LOAD DATA ───────────────────────────────────────────────────────

print(f"Loading {CSV_PATH}...")
df = pd.read_csv(CSV_PATH)
print(f"  {len(df)} samples, {len(df)/SAMPLE_RATE:.1f}s duration")

t_ms = df['timestamp_ms'].values.astype(float)
t_s = t_ms / 1000.0
dt = 1.0 / SAMPLE_RATE

ax_raw = df['a1x'].values.astype(float)
ay_raw = df['a1y'].values.astype(float)
az_raw = df['a1z'].values.astype(float)
gx_raw = df['g1x'].values.astype(float)
gy_raw = df['g1y'].values.astype(float)
gz_raw = df['g1z'].values.astype(float)

# ── SIGNAL PROCESSING ───────────────────────────────────────────────

print("Processing signals...")

# Low-pass filter accelerometer
ax_f = butter_filter(ax_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
ay_f = butter_filter(ay_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
az_f = butter_filter(az_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)

# Low-pass filter gyroscope
gx_f = butter_filter(gx_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
gy_f = butter_filter(gy_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)
gz_f = butter_filter(gz_raw, LP_CUTOFF, SAMPLE_RATE, FILTER_ORDER)

# Acceleration magnitude (for rep detection)
accel_mag = np.sqrt(ax_f**2 + ay_f**2 + az_f**2)

# Remove gravity from filtered accel
ax_lin, ay_lin, az_lin = remove_gravity(ax_f, ay_f, az_f)
accel_lin_mag = np.sqrt(ax_lin**2 + ay_lin**2 + az_lin**2)

# Gyro magnitude
gyro_mag = np.sqrt(gx_f**2 + gy_f**2 + gz_f**2)

# ── VELOCITY ESTIMATION (with ZUPT) ───────────────────────────────

print("Estimating velocity...")

# Identify gravity axis and orientation from calibration period
cal_n = min(SAMPLE_RATE, len(ax_raw))
grav_vec = np.array([np.mean(ax_raw[:cal_n]), np.mean(ay_raw[:cal_n]), np.mean(az_raw[:cal_n])])
grav_axis = np.argmax(np.abs(grav_vec))
grav_sign = np.sign(grav_vec[grav_axis])
axis_names = ['X', 'Y', 'Z']
print(f"  Gravity axis: {axis_names[grav_axis]} (sign={grav_sign:+.0f})")

# IMU orientation (user-provided):
#   Y = up (gravity axis), -X = forward (towards lifter), Z = lateral
# For the horizontal bar path axis, X (forward/back) is most relevant.
# grav_axis=1 (Y), forward_axis=0 (X), lateral_axis=2 (Z)
forward_axis = 0  # X axis
lateral_axis = 2  # Z axis

lin_accels = [ax_lin, ay_lin, az_lin]

# ── Detect stationary (zero-velocity) periods for ZUPT ──
# When the bar is still, acceleration magnitude ≈ 0 and gyro magnitude ≈ 0.
# We use this to identify moments where we can reset velocity to zero.
accel_energy = np.sqrt(ax_lin**2 + ay_lin**2 + az_lin**2)
gyro_energy = np.sqrt(gx_f**2 + gy_f**2 + gz_f**2)

# Smooth the energy signals for stable detection
accel_energy_smooth = butter_filter(accel_energy, 2.0, SAMPLE_RATE, 2)
gyro_energy_smooth = butter_filter(gyro_energy, 2.0, SAMPLE_RATE, 2)

# Thresholds: bar is "still" when both accel and gyro energy are low
ZUPT_ACCEL_THRESH = 1.5   # m/s² — relaxed for bench (bar wobbles at lockout)
ZUPT_GYRO_THRESH = 0.15   # rad/s — minimal rotation
is_stationary = (accel_energy_smooth < ZUPT_ACCEL_THRESH) & (gyro_energy_smooth < ZUPT_GYRO_THRESH)

zupt_pct = np.sum(is_stationary) / len(is_stationary) * 100
print(f"  ZUPT: {zupt_pct:.1f}% of samples identified as stationary")

# ── Integrate acceleration → velocity with ZUPT corrections ──
# At each stationary sample, we force velocity back to zero.
# Between stationary periods, we integrate normally.
# This bounds drift to within each movement segment.
vx_zupt = np.zeros(len(ax_lin))
vy_zupt = np.zeros(len(ay_lin))
vz_zupt = np.zeros(len(az_lin))

for i in range(1, len(ax_lin)):
    if is_stationary[i]:
        # Zero-velocity update: reset to zero
        vx_zupt[i] = 0.0
        vy_zupt[i] = 0.0
        vz_zupt[i] = 0.0
    else:
        # Forward Euler integration
        vx_zupt[i] = vx_zupt[i-1] + ax_lin[i] * dt
        vy_zupt[i] = vy_zupt[i-1] + ay_lin[i] * dt
        vz_zupt[i] = vz_zupt[i-1] + az_lin[i] * dt

        # Linear drift correction: if we know when the next stationary
        # period starts, we can linearly detrend the velocity toward zero.
        # This is done in a second pass below.

# Second pass: for each moving segment between ZUPT points, linearly
# detrend the velocity so it reaches zero at the next ZUPT boundary.
# This distributes integration error evenly across the segment.
def detrend_segments(vel, stationary):
    """Remove linear drift within each moving segment."""
    result = vel.copy()
    i = 0
    n = len(vel)
    while i < n:
        # Find start of a moving segment
        if not stationary[i]:
            seg_start = i
            # Find end of moving segment
            while i < n and not stationary[i]:
                i += 1
            seg_end = i  # first stationary sample after the segment

            seg_len = seg_end - seg_start
            if seg_len > 1:
                # The velocity at seg_end should be zero (ZUPT).
                # Linearly subtract the accumulated error.
                end_vel = result[seg_end - 1]
                correction = np.linspace(0, end_vel, seg_len)
                result[seg_start:seg_end] -= correction
        else:
            i += 1
    return result

vx_zupt = detrend_segments(vx_zupt, is_stationary)
vy_zupt = detrend_segments(vy_zupt, is_stationary)
vz_zupt = detrend_segments(vz_zupt, is_stationary)

# These are our corrected velocities
vx = vx_zupt
vy = vy_zupt
vz = vz_zupt
v_mag = np.sqrt(vx**2 + vy**2 + vz**2)

# Vertical velocity (along gravity axis)
v_vertical = [vx, vy, vz][grav_axis]

# Also keep the old high-pass velocity for rep detection (more sensitive)
vx_hp = integrate_with_drift_removal(ax_lin, dt, HP_CUTOFF, SAMPLE_RATE)
vy_hp = integrate_with_drift_removal(ay_lin, dt, HP_CUTOFF, SAMPLE_RATE)
vz_hp = integrate_with_drift_removal(az_lin, dt, HP_CUTOFF, SAMPLE_RATE)
v_vertical_hp = [vx_hp, vy_hp, vz_hp][grav_axis]

# ── POSITION ESTIMATION (ZUPT-bounded integration) ─────────────────

print("Estimating bar path...")

# Integrate velocity → position, also with ZUPT resets
px = np.zeros(len(vx))
py = np.zeros(len(vy))
pz = np.zeros(len(vz))

for i in range(1, len(vx)):
    if is_stationary[i]:
        # Hold position during stationary periods
        px[i] = px[i-1]
        py[i] = py[i-1]
        pz[i] = pz[i-1]
    else:
        px[i] = px[i-1] + vx[i] * dt
        py[i] = py[i-1] + vy[i] * dt
        pz[i] = pz[i-1] + vz[i] * dt

# Detrend position within each moving segment to ensure return-to-start
px = detrend_segments(px, is_stationary)
py = detrend_segments(py, is_stationary)
pz = detrend_segments(pz, is_stationary)

# Vertical = Y (gravity axis), Horizontal = X (forward/back axis)
pos_vertical = [px, py, pz][grav_axis]
pos_horizontal = [px, py, pz][forward_axis]

# ── REP DETECTION ──────────────────────────────────────────────────

print("Detecting reps...")

# Strategy:
#   - HP velocity → rep detection (sensitive) AND per-rep metrics (stable magnitudes)
#   - ZUPT velocity → bar path / position only (drift-bounded)
# The ZUPT detrending distorts velocity magnitudes, so HP is better for metrics.
v_vert_smooth = butter_filter(v_vertical_hp, 5.0, SAMPLE_RATE, 2)

# These are the metric velocities (HP-based, stable across reps)
v_metric_x = vx_hp
v_metric_y = vy_hp
v_metric_z = vz_hp
v_metric_mag = np.sqrt(v_metric_x**2 + v_metric_y**2 + v_metric_z**2)
v_metric_vertical = [v_metric_x, v_metric_y, v_metric_z][grav_axis]

# Concentric-only detection: each rep has exactly one concentric peak (+Y velocity).
concentric_sign = grav_sign
if concentric_sign > 0:
    detect_signal = v_vert_smooth
else:
    detect_signal = -v_vert_smooth

min_dist_samples = int(1.5 * SAMPLE_RATE)

peaks, peak_props = find_peaks(
    detect_signal,
    distance=min_dist_samples,
    prominence=0.05,
    height=0.1
)

# Define concentric rep boundaries using zero-crossings around each peak
zero_crossings = np.where(np.diff(np.sign(v_vert_smooth)))[0]

candidates = []
for pk in peaks:
    before = zero_crossings[zero_crossings < pk]
    after = zero_crossings[zero_crossings > pk]

    if len(before) > 0 and len(after) > 0:
        start = before[-1]
        end = after[0]
        duration = (end - start) / SAMPLE_RATE
        peak_v = float(detect_signal[pk])

        candidates.append({
            'start_idx': start,
            'end_idx': end,
            'peak_idx': pk,
            'start_s': t_s[start],
            'end_s': t_s[end],
            'duration_s': duration,
            'peak_v': peak_v,
        })

# Remove overlapping candidates
deduped = []
for c in candidates:
    if not deduped or c['start_idx'] > deduped[-1]['end_idx']:
        deduped.append(c)

# Adaptive threshold: reject candidates with peak concentric velocity
# below 40% of the median. Filters unrack/rerack movements.
if len(deduped) >= 3:
    candidate_peaks = sorted([c['peak_v'] for c in deduped])
    median_peak_v = float(np.median(candidate_peaks))
    vel_threshold = median_peak_v * 0.40
    print(f"  Median concentric velocity: {median_peak_v:.4f} m/s, threshold: {vel_threshold:.4f} m/s")
    reps = [c for c in deduped if c['peak_v'] >= vel_threshold]
    rejected = len(deduped) - len(reps)
    if rejected > 0:
        print(f"  Rejected {rejected} candidate(s) (unrack/rerack/partial)")
else:
    reps = deduped

print(f"  Found {len(reps)} reps")

# ── PER-REP METRICS ────────────────────────────────────────────────

print("Computing per-rep metrics...")

for i, rep in enumerate(reps):
    s, e = rep['start_idx'], rep['end_idx']

    # Use HP velocity for metrics (stable magnitudes across reps)
    rep_v = v_metric_mag[s:e]
    rep_v_vert = np.abs(v_metric_vertical[s:e])

    # Mean concentric velocity (average of absolute vertical velocity)
    rep['mean_velocity'] = float(np.mean(rep_v_vert))

    # Peak velocity
    rep['peak_velocity'] = float(np.max(rep_v_vert))

    # Peak acceleration
    rep_a = accel_lin_mag[s:e]
    rep['peak_accel'] = float(np.max(rep_a))

    # Vertical displacement from ZUPT position (more accurate than HP for ROM)
    rep_pos = pos_vertical[s:e]
    rep['rom_m'] = float(np.ptp(rep_pos))
    rep['rom_cm'] = rep['rom_m'] * 100

    # Time to peak velocity
    peak_v_idx = np.argmax(rep_v_vert)
    rep['time_to_peak_v'] = peak_v_idx / SAMPLE_RATE

    # Rep number
    rep['rep_num'] = i + 1

    # Gyro activity (bar rotation during rep)
    rep_gyro = gyro_mag[s:e]
    rep['mean_rotation'] = float(np.mean(rep_gyro))
    rep['peak_rotation'] = float(np.max(rep_gyro))

# ── VELOCITY-BASED RPE & FATIGUE ────────────────────────────────────

if len(reps) >= 2:
    velocities = [r['mean_velocity'] for r in reps]
    peak_velocities = [r['peak_velocity'] for r in reps]

    # Velocity loss % (first rep vs last rep)
    velocity_loss_pct = (1 - velocities[-1] / velocities[0]) * 100 if velocities[0] > 0 else 0

    # Estimated RPE based on velocity loss (Helms et al. style)
    # Very rough mapping: 0% loss ≈ RPE 6, 10% loss ≈ RPE 8, 25%+ ≈ RPE 10
    if velocity_loss_pct < 5:
        est_rpe = 6.0
    elif velocity_loss_pct < 10:
        est_rpe = 6.0 + (velocity_loss_pct - 5) * 0.4  # 6-8
    elif velocity_loss_pct < 20:
        est_rpe = 8.0 + (velocity_loss_pct - 10) * 0.1  # 8-9
    elif velocity_loss_pct < 30:
        est_rpe = 9.0 + (velocity_loss_pct - 20) * 0.1  # 9-10
    else:
        est_rpe = 10.0
    est_rpe = min(est_rpe, 10.0)

    # Fatigue index (slope of velocity over reps)
    rep_nums = np.arange(1, len(reps) + 1)
    if len(reps) >= 3:
        fatigue_slope = np.polyfit(rep_nums, velocities, 1)[0]
    else:
        fatigue_slope = (velocities[-1] - velocities[0]) / (len(reps) - 1) if len(reps) > 1 else 0

    # Speed rating per rep (relative to best rep)
    best_v = max(velocities)
    speed_ratings = [(v / best_v * 100) if best_v > 0 else 100 for v in velocities]
else:
    velocity_loss_pct = 0
    est_rpe = 6.0
    fatigue_slope = 0
    speed_ratings = [100] * len(reps)

# ── 1RM ESTIMATION ──────────────────────────────────────────────────

# Using Jidovtseff et al. (2011) load-velocity relationship for bench press
# MVT (minimum velocity threshold) for bench press ≈ 0.17 m/s
MVT_EXERCISE = MVT  # m/s

if len(reps) >= 1:
    mean_v = np.mean([r['mean_velocity'] for r in reps])
    # Simple linear load-velocity: 1RM ≈ load / (1 - (MVT/velocity))
    # This is a rough single-point estimate; better with multiple loads
    if mean_v > MVT_EXERCISE:
        load_kg = LOAD_LBS * 0.453592
        est_1rm_kg = load_kg / (1 - (MVT_EXERCISE / mean_v)) if mean_v > MVT_EXERCISE else load_kg
        est_1rm_lbs = est_1rm_kg / 0.453592
    else:
        est_1rm_lbs = LOAD_LBS
        est_1rm_kg = LOAD_LBS * 0.453592
else:
    est_1rm_lbs = LOAD_LBS
    est_1rm_kg = LOAD_LBS * 0.453592

# ── BUILD DASHBOARD ─────────────────────────────────────────────────

print("Building dashboard...")

# Color scheme
BG = "#0f1117"
CARD_BG = "#1a1d27"
TEXT = "#e0e0e0"
ACCENT = "#4ecdc4"
ACCENT2 = "#ff6b6b"
ACCENT3 = "#ffe66d"
ACCENT4 = "#a8e6cf"
GRID = "#2a2d37"

fig = make_subplots(
    rows=5, cols=2,
    subplot_titles=(
        "Raw Accelerometer Signal",
        "Filtered Acceleration Magnitude",
        "Vertical Velocity (Concentric/Eccentric)",
        "Velocity Magnitude with Rep Boundaries",
        "Per-Rep Bar Path (Vertical vs Forward/Back)",
        "Vertical Displacement Over Time",
        "Per-Rep Mean Concentric Velocity",
        "Per-Rep Peak Velocity & Speed Rating",
        "Gyroscope Magnitude (Bar Rotation)",
        "Fatigue Curve & Velocity Trend"
    ),
    vertical_spacing=0.06,
    horizontal_spacing=0.08,
    specs=[
        [{"type": "scatter"}, {"type": "scatter"}],
        [{"type": "scatter"}, {"type": "scatter"}],
        [{"type": "scatter"}, {"type": "scatter"}],
        [{"type": "scatter"}, {"type": "scatter"}],
        [{"type": "scatter"}, {"type": "scatter"}],
    ]
)

# 1. Raw accelerometer
for data, name, color in [(ax_raw, 'X', ACCENT), (ay_raw, 'Y', ACCENT2), (az_raw, 'Z', ACCENT3)]:
    fig.add_trace(go.Scatter(x=t_s, y=data, name=f'Accel {name}',
                              line=dict(width=0.5, color=color), opacity=0.7,
                              legendgroup='raw_accel', showlegend=True), row=1, col=1)

# 2. Filtered accel magnitude
fig.add_trace(go.Scatter(x=t_s, y=accel_mag, name='|Accel| filtered',
                          line=dict(width=1, color=ACCENT), showlegend=True), row=1, col=2)
fig.add_hline(y=GRAVITY, line_dash="dash", line_color=ACCENT3, opacity=0.5, row=1, col=2,
              annotation_text="1g", annotation_position="top left")

# 3. Vertical velocity (HP for clean display)
fig.add_trace(go.Scatter(x=t_s, y=v_metric_vertical, name='Vertical Velocity',
                          line=dict(width=1, color=ACCENT), showlegend=True), row=2, col=1)
fig.add_hline(y=0, line_dash="dot", line_color=TEXT, opacity=0.3, row=2, col=1)

# Mark rep regions
for rep in reps:
    fig.add_vrect(x0=rep['start_s'], x1=rep['end_s'],
                  fillcolor=ACCENT, opacity=0.08, line_width=0, row=2, col=1)
    fig.add_vrect(x0=rep['start_s'], x1=rep['end_s'],
                  fillcolor=ACCENT, opacity=0.08, line_width=0, row=2, col=2)

# 4. Velocity magnitude with rep boundaries (HP for stable magnitudes)
fig.add_trace(go.Scatter(x=t_s, y=v_metric_mag, name='|Velocity|',
                          line=dict(width=1, color=ACCENT2), showlegend=True), row=2, col=2)

# Add rep boundary markers
for rep in reps:
    fig.add_vline(x=rep['start_s'], line_dash="dash", line_color=ACCENT4, opacity=0.5, row=2, col=2)

# 5. Per-rep bar paths via EKF — full eccentric + concentric cycle
# Run the Extended Kalman Filter per-rep for drift-bounded position estimation.
print("Running EKF for per-rep bar paths...")

colors_reps = [ACCENT, ACCENT2, ACCENT3, ACCENT4, '#c084fc', '#fb923c', '#38bdf8', '#f472b6']
zero_crossings_plot = np.where(np.diff(np.sign(v_vert_smooth)))[0]

# Build full rep boundaries (eccentric start → lockout) for EKF
accel_data = np.column_stack([ax_f, ay_f, az_f])
gyro_data = np.column_stack([gx_f, gy_f, gz_f])

ekf_rep_starts = []
ekf_rep_ends = []
for rep in reps:
    conc_start = rep['start_idx']
    conc_end = rep['end_idx']
    ecc_starts = zero_crossings_plot[zero_crossings_plot < conc_start]
    full_start = ecc_starts[-1] if len(ecc_starts) > 0 else conc_start
    ekf_rep_starts.append(full_start)
    ekf_rep_ends.append(conc_end)

ekf_results = estimate_per_rep_bar_path(
    accel_data, gyro_data, SAMPLE_RATE,
    ekf_rep_starts, ekf_rep_ends
)

for i, (rep, ekf_rep) in enumerate(zip(reps, ekf_results)):
    pos = ekf_rep['position']
    color = colors_reps[i % len(colors_reps)]

    # X = forward/back (negate: -X = forward in sensor frame → positive on plot)
    h = -pos[:, 0] * 100
    # Y = vertical
    v = pos[:, 1] * 100

    # Find turnaround (lowest vertical point = chest)
    turn_idx = np.argmin(v) if np.min(v) < v[0] else np.argmax(v)

    group = f'rep{i+1}'
    fig.add_trace(go.Scatter(x=h, y=v, name=f'Rep {i+1}', mode='lines',
                              line=dict(width=2, color=color),
                              legendgroup=group, showlegend=True), row=3, col=1)
    if len(h) > 0:
        fig.add_trace(go.Scatter(x=[h[0]], y=[v[0]], mode='markers',
                                  marker=dict(size=7, color=color, symbol='circle'),
                                  name=f'Lockout {i+1}', legendgroup=group,
                                  showlegend=False), row=3, col=1)
        if 0 < turn_idx < len(h) - 1:
            fig.add_trace(go.Scatter(x=[h[turn_idx]], y=[v[turn_idx]], mode='markers',
                                      marker=dict(size=7, color=color, symbol='diamond'),
                                      name=f'Chest {i+1}', legendgroup=group,
                                      showlegend=False), row=3, col=1)

# 6. Vertical displacement over time
fig.add_trace(go.Scatter(x=t_s, y=pos_vertical * 100, name='Vertical Position',
                          line=dict(width=1.5, color=ACCENT), showlegend=True), row=3, col=2)
for rep in reps:
    fig.add_vrect(x0=rep['start_s'], x1=rep['end_s'],
                  fillcolor=ACCENT3, opacity=0.08, line_width=0, row=3, col=2)

# 7. Per-rep mean concentric velocity (bar chart)
if reps:
    rep_nums = [f"Rep {r['rep_num']}" for r in reps]
    mean_vels = [r['mean_velocity'] for r in reps]

    colors_bar = [ACCENT if v >= np.mean(mean_vels) else ACCENT2 for v in mean_vels]

    fig.add_trace(go.Bar(x=rep_nums, y=mean_vels, name='Mean Conc. Velocity',
                          marker_color=colors_bar, showlegend=True,
                          text=[f"{v:.3f}" for v in mean_vels], textposition='outside',
                          textfont=dict(color=TEXT, size=11)), row=4, col=1)
    fig.add_hline(y=MVT, line_dash="dash", line_color=ACCENT2, opacity=0.7, row=4, col=1,
                  annotation_text=f"MVT ({MVT} m/s)", annotation_position="top right")

# 8. Peak velocity + speed rating
if reps:
    peak_vels = [r['peak_velocity'] for r in reps]

    fig.add_trace(go.Bar(x=rep_nums, y=peak_vels, name='Peak Velocity',
                          marker_color=ACCENT3, showlegend=True,
                          text=[f"{v:.3f}" for v in peak_vels], textposition='outside',
                          textfont=dict(color=TEXT, size=11)), row=4, col=2)

    # Add speed rating as text annotations
    for i, (rn, pv, sr) in enumerate(zip(rep_nums, peak_vels, speed_ratings)):
        fig.add_annotation(x=rn, y=pv + max(peak_vels)*0.15, text=f"{sr:.0f}%",
                          font=dict(color=ACCENT4, size=12, family="monospace"),
                          showarrow=False, row=4, col=2)

# 9. Gyroscope magnitude
fig.add_trace(go.Scatter(x=t_s, y=gyro_mag, name='|Gyro|',
                          line=dict(width=1, color=ACCENT3), showlegend=True), row=5, col=1)
for rep in reps:
    fig.add_vrect(x0=rep['start_s'], x1=rep['end_s'],
                  fillcolor=ACCENT, opacity=0.08, line_width=0, row=5, col=1)

# 10. Fatigue curve
if len(reps) >= 2:
    rep_x = [r['rep_num'] for r in reps]
    mean_vels = [r['mean_velocity'] for r in reps]

    fig.add_trace(go.Scatter(x=rep_x, y=mean_vels, name='Velocity Trend',
                              mode='lines+markers',
                              line=dict(width=2, color=ACCENT),
                              marker=dict(size=8, color=ACCENT),
                              showlegend=True), row=5, col=2)

    # Trend line
    if len(reps) >= 3:
        z = np.polyfit(rep_x, mean_vels, 1)
        trend = np.polyval(z, rep_x)
        fig.add_trace(go.Scatter(x=rep_x, y=trend, name='Trend',
                                  mode='lines', line=dict(width=2, color=ACCENT2, dash='dash'),
                                  showlegend=True), row=5, col=2)

# ── LAYOUT ──────────────────────────────────────────────────────────

fig.update_layout(
    height=2200,
    width=1400,
    template="plotly_dark",
    paper_bgcolor=BG,
    plot_bgcolor=CARD_BG,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
    title=dict(
        text=f"<b>IMU Session Analysis</b> — {EXERCISE} @ {LOAD_LBS} lbs<br>"
             f"<span style='font-size:14px; color:{ACCENT}'>"
             f"{len(reps)} reps detected | "
             f"Duration: {t_s[-1]:.1f}s | "
             f"Sample rate: {SAMPLE_RATE} Hz | "
             f"Est. RPE: {est_rpe:.1f} | "
             f"Velocity loss: {velocity_loss_pct:.1f}% | "
             f"Est. 1RM: {est_1rm_lbs:.0f} lbs ({est_1rm_kg:.1f} kg)"
             f"</span>",
        font=dict(size=20),
        x=0.5,
    ),
    showlegend=True,
    legend=dict(bgcolor="rgba(0,0,0,0.3)", bordercolor=GRID, borderwidth=1),
)

# Update all axes
fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID)
fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)

# Axis labels
for col in [1, 2]:
    fig.update_xaxes(title_text="Time (s)", row=1, col=col)
    fig.update_xaxes(title_text="Time (s)", row=2, col=col)
    fig.update_xaxes(title_text="Time (s)", row=5, col=col if col == 1 else col)

fig.update_yaxes(title_text="Accel (m/s²)", row=1, col=1)
fig.update_yaxes(title_text="|Accel| (m/s²)", row=1, col=2)
fig.update_yaxes(title_text="Velocity (m/s)", row=2, col=1)
fig.update_yaxes(title_text="|Velocity| (m/s)", row=2, col=2)
fig.update_xaxes(title_text="Forward ← → Back (cm)", row=3, col=1)
fig.update_yaxes(title_text="Vertical (cm)", row=3, col=1)
fig.update_yaxes(title_text="Vertical Pos (cm)", row=3, col=2)
fig.update_xaxes(title_text="Time (s)", row=3, col=2)
fig.update_yaxes(title_text="Mean Conc. Vel (m/s)", row=4, col=1)
fig.update_yaxes(title_text="Peak Vel (m/s)", row=4, col=2)
fig.update_yaxes(title_text="|Gyro| (rad/s)", row=5, col=1)
fig.update_xaxes(title_text="Time (s)", row=5, col=1)
fig.update_xaxes(title_text="Rep #", row=5, col=2)
fig.update_yaxes(title_text="Mean Vel (m/s)", row=5, col=2)

# ── SUMMARY TABLE ────────────────────────────────────────────────────

summary_html = f"""
<div style="font-family: Inter, system-ui, sans-serif; background: {BG}; color: {TEXT}; padding: 30px;">
<h1 style="color: {ACCENT}; text-align: center;">IMU Session Analysis — {EXERCISE} @ {LOAD_LBS} lbs</h1>

<div style="display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; margin: 20px 0;">
  <div style="background: {CARD_BG}; padding: 20px; border-radius: 12px; min-width: 160px; text-align: center;">
    <div style="font-size: 36px; font-weight: bold; color: {ACCENT};">{len(reps)}</div>
    <div style="color: #888;">Reps Detected</div>
  </div>
  <div style="background: {CARD_BG}; padding: 20px; border-radius: 12px; min-width: 160px; text-align: center;">
    <div style="font-size: 36px; font-weight: bold; color: {ACCENT2};">{est_rpe:.1f}</div>
    <div style="color: #888;">Est. RPE</div>
  </div>
  <div style="background: {CARD_BG}; padding: 20px; border-radius: 12px; min-width: 160px; text-align: center;">
    <div style="font-size: 36px; font-weight: bold; color: {ACCENT3};">{velocity_loss_pct:.1f}%</div>
    <div style="color: #888;">Velocity Loss</div>
  </div>
  <div style="background: {CARD_BG}; padding: 20px; border-radius: 12px; min-width: 160px; text-align: center;">
    <div style="font-size: 36px; font-weight: bold; color: {ACCENT4};">{est_1rm_lbs:.0f} lbs</div>
    <div style="color: #888;">Est. 1RM</div>
  </div>
  <div style="background: {CARD_BG}; padding: 20px; border-radius: 12px; min-width: 160px; text-align: center;">
    <div style="font-size: 36px; font-weight: bold; color: {ACCENT};">{t_s[-1]:.1f}s</div>
    <div style="color: #888;">Duration</div>
  </div>
</div>

<table style="width: 100%; max-width: 1000px; margin: 20px auto; border-collapse: collapse; background: {CARD_BG}; border-radius: 8px; overflow: hidden;">
<tr style="background: #252836;">
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Rep</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Duration (s)</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Mean Vel (m/s)</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Peak Vel (m/s)</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">ROM (cm)</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Time to Peak V (s)</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Speed Rating</th>
  <th style="padding: 12px; text-align: center; color: {ACCENT};">Peak Rotation (rad/s)</th>
</tr>
"""

for i, rep in enumerate(reps):
    row_bg = "#1e2130" if i % 2 == 0 else CARD_BG
    sr = speed_ratings[i] if i < len(speed_ratings) else 100
    sr_color = ACCENT4 if sr >= 90 else (ACCENT3 if sr >= 75 else ACCENT2)
    summary_html += f"""
<tr style="background: {row_bg};">
  <td style="padding: 10px; text-align: center; font-weight: bold;">{rep['rep_num']}</td>
  <td style="padding: 10px; text-align: center;">{rep['duration_s']:.2f}</td>
  <td style="padding: 10px; text-align: center;">{rep['mean_velocity']:.4f}</td>
  <td style="padding: 10px; text-align: center;">{rep['peak_velocity']:.4f}</td>
  <td style="padding: 10px; text-align: center;">{rep['rom_cm']:.1f}</td>
  <td style="padding: 10px; text-align: center;">{rep['time_to_peak_v']:.2f}</td>
  <td style="padding: 10px; text-align: center; color: {sr_color}; font-weight: bold;">{sr:.0f}%</td>
  <td style="padding: 10px; text-align: center;">{rep['peak_rotation']:.3f}</td>
</tr>"""

summary_html += """
</table>

<div style="text-align: center; margin: 20px 0; color: #666; font-size: 12px;">
  <p>Velocity-based RPE estimated using velocity loss across set (Helms et al. methodology).</p>
  <p>1RM estimate uses single-point load-velocity projection with MVT = {MVT} m/s for {EXERCISE.lower()}.</p>
  <p>Speed Rating = rep velocity / best rep velocity × 100%.</p>
  <p><em>Note: 1RM estimate from submaximal loads is rough — accuracy improves with heavier loads closer to actual max.</em></p>
</div>
</div>
"""

# ── SAVE HTML ────────────────────────────────────────────────────────

plot_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')

full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>IMU Session Analysis — {EXERCISE} @ {LOAD_LBS} lbs</title>
<style>
  body {{ margin: 0; background: {BG}; }}
  * {{ box-sizing: border-box; }}
</style>
</head>
<body>
{summary_html}
<div style="max-width: 1450px; margin: 0 auto; padding: 20px;">
{plot_html}
</div>
</body>
</html>"""

with open(OUTPUT_PATH, 'w') as f:
    f.write(full_html)

print(f"\nDashboard saved to: {OUTPUT_PATH}")

# ── PRINT SUMMARY ────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"  SESSION SUMMARY — {EXERCISE} @ {LOAD_LBS} lbs")
print(f"{'='*50}")
print(f"  Reps detected:    {len(reps)}")
print(f"  Duration:          {t_s[-1]:.1f}s")
print(f"  Est. RPE:          {est_rpe:.1f}")
print(f"  Velocity loss:     {velocity_loss_pct:.1f}%")
print(f"  Est. 1RM:          {est_1rm_lbs:.0f} lbs ({est_1rm_kg:.1f} kg)")
if reps:
    print(f"  Avg mean vel:      {np.mean([r['mean_velocity'] for r in reps]):.4f} m/s")
    print(f"  Best peak vel:     {max([r['peak_velocity'] for r in reps]):.4f} m/s")
    print(f"  Avg ROM:           {np.mean([r['rom_cm'] for r in reps]):.1f} cm")
print(f"{'='*50}")
