"""
IMU-based Barbell Bar Path Reconstruction
==========================================

Reconstructs 2D bar path (vertical + forward/back) from a single 6-DOF IMU
mounted on a barbell.

Algorithm:
  1. Mahony complementary filter for orientation (gyro + gravity reference)
  2. Rotate accelerometer to world frame, subtract gravity
  3. Per-rep constrained double integration:
     - Mean-remove acceleration to enforce v(0)=v(T)=0
     - Linear detrend position to enforce p(0)≈p(T)

Coordinate conventions:
  Sensor frame:  Y = up (gravity), -X = forward (toward lifter), Z = lateral
  World frame:   Y = vertical (up +), X = horizontal (toward lifter +)

Author: Darius Sattari (Harvard)
"""

import numpy as np
from scipy.signal import butter, filtfilt


# ── Quaternion utilities ────────────────────────────────────────────

def quat_mult(q, r):
    """Hamilton product q ⊗ r."""
    qw, qx, qy, qz = q
    rw, rx, ry, rz = r
    return np.array([
        qw*rw - qx*rx - qy*ry - qz*rz,
        qw*rx + qx*rw + qy*rz - qz*ry,
        qw*ry - qx*rz + qy*rw + qz*rx,
        qw*rz + qx*ry - qy*rx + qz*rw,
    ])


def quat_conj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_normalize(q):
    n = np.linalg.norm(q)
    return q / n if n > 1e-10 else np.array([1.0, 0.0, 0.0, 0.0])


def quat_to_rotation_matrix(q):
    """Unit quaternion → 3×3 rotation matrix (sensor → world)."""
    q = quat_normalize(q)
    qw, qx, qy, qz = q
    return np.array([
        [1 - 2*(qy**2 + qz**2),     2*(qx*qy - qz*qw),     2*(qx*qz + qy*qw)],
        [    2*(qx*qy + qz*qw), 1 - 2*(qx**2 + qz**2),     2*(qy*qz - qx*qw)],
        [    2*(qx*qz - qy*qw),     2*(qy*qz + qx*qw), 1 - 2*(qx**2 + qy**2)],
    ])


def quat_from_accel(accel):
    """Quaternion aligning sensor gravity with world Y-up."""
    a = accel / np.linalg.norm(accel)
    cross = np.cross(a, [0, 1, 0])
    dot = np.dot(a, [0, 1, 0])
    if dot < -0.9999:
        return np.array([0.0, 1.0, 0.0, 0.0])
    w = 1.0 + dot
    return quat_normalize(np.array([w, cross[0], cross[1], cross[2]]))


# ── Mahony complementary filter ─────────────────────────────────────

def estimate_orientation(accel_data, gyro_data, sample_rate, kp=1.0):
    """
    Mahony (2008) complementary filter for orientation.
    Fuses gyroscope with accelerometer gravity reference.
    Includes automatic gyro bias removal from calibration period.
    """
    n = len(accel_data)
    dt = 1.0 / sample_rate

    cal_n = min(int(0.5 * sample_rate), n)
    q = quat_from_accel(np.mean(accel_data[:cal_n], axis=0))
    gyro_bias = np.mean(gyro_data[:cal_n], axis=0)

    orientations = np.zeros((n, 4))
    orientations[0] = q

    for i in range(1, n):
        gyro = gyro_data[i] - gyro_bias
        accel = accel_data[i]
        accel_mag = np.linalg.norm(accel)

        correction = np.zeros(3)
        if accel_mag > 1e-6:
            a_hat = accel / accel_mag
            R = quat_to_rotation_matrix(q)
            v_hat = R.T @ np.array([0.0, 1.0, 0.0])
            error = np.cross(a_hat, v_hat)

            gravity_err = abs(accel_mag - 9.81) / 9.81
            adaptive_kp = kp * max(0, 1.0 - 3.0 * gravity_err)
            correction = adaptive_kp * error

        gyro_c = gyro + correction
        omega_norm = np.linalg.norm(gyro_c)
        if omega_norm > 1e-10:
            angle = omega_norm * dt
            axis = gyro_c / omega_norm
            dq = np.array([np.cos(angle/2), axis[0]*np.sin(angle/2),
                           axis[1]*np.sin(angle/2), axis[2]*np.sin(angle/2)])
            q = quat_normalize(quat_mult(q, dq))

        orientations[i] = q

    return orientations


# ── Constrained double integration ──────────────────────────────────

def _integrate_segment_constrained(accel_world, dt):
    """
    Drift-free double integration for a single rep segment.

    Enforces physical constraints:
      v(0) = v(T) = 0   (bar at rest at lockout)
      p(0) = p(T) ≈ 0   (bar returns to lockout)

    Method:
      1. High-pass filter acceleration at very low frequency (0.15 Hz) to
         remove DC gravity residuals while preserving motion content (>0.5 Hz)
      2. Remove mean acceleration → net impulse = 0
      3. Integrate velocity, linear detrend → v(T) = 0 exactly
      4. Integrate position, quadratic detrend → p(T) ≈ p(0)

    For longer segments (>1.5s), gravity subtraction residuals cause
    quadratic drift in position. The high-pass pre-filter removes these
    slowly-varying residuals before they accumulate through integration.
    """
    n = len(accel_world)
    vel = np.zeros((n, 3))
    pos = np.zeros((n, 3))

    duration = n * dt
    nyq = 0.5 / dt

    for k in range(3):
        a = accel_world[:, k].copy()

        # For longer segments, high-pass filter to remove DC gravity residual
        # 0.15 Hz cutoff preserves motion content (>0.5 Hz) while removing
        # slowly-varying bias that causes quadratic drift in integration
        if duration > 1.2 and n > 15:
            hp_freq = 0.15
            if hp_freq / nyq < 0.95:  # ensure valid frequency
                bh, ah = butter(2, hp_freq / nyq, btype='high')
                a = filtfilt(bh, ah, a)

        a -= np.mean(a)

        v = np.cumsum(a) * dt
        # Linear detrend velocity
        v -= np.linspace(0, v[-1], n)

        p = np.cumsum(v) * dt
        # For longer segments, use quadratic detrend on position to handle
        # residual parabolic drift from any remaining acceleration bias
        if duration > 1.8:
            t_norm = np.linspace(0, 1, n)
            coeffs = np.polyfit(t_norm, p, 2)
            p -= np.polyval(coeffs, t_norm)
        else:
            # Linear detrend position
            p -= np.linspace(0, p[-1], n)

        vel[:, k] = v
        pos[:, k] = p

    return vel, pos


# ── Public API ──────────────────────────────────────────────────────

def estimate_bar_path(accel_data, gyro_data, sample_rate,
                      zupt_accel_thresh=0.8, zupt_gyro_thresh=0.3,
                      gravity=9.81):
    """Estimate full-session bar path (backward compat)."""
    n = len(accel_data)
    dt = 1.0 / sample_rate

    orientations = estimate_orientation(accel_data, gyro_data, sample_rate)

    g_world = np.array([0.0, gravity, 0.0])
    accel_world = np.zeros((n, 3))
    for i in range(n):
        R = quat_to_rotation_matrix(orientations[i])
        accel_world[i] = R @ accel_data[i] - g_world

    vel, pos = _integrate_segment_constrained(accel_world, dt)

    # Stationary detection (for display)
    cal_n = min(int(0.5 * sample_rate), n)
    g_bias = np.mean(accel_data[:cal_n], axis=0)
    accel_lin = accel_data - g_bias
    ae = np.sqrt(np.sum(accel_lin**2, axis=1))
    ge = np.sqrt(np.sum(gyro_data**2, axis=1))
    win = max(3, int(0.05 * sample_rate))
    if win % 2 == 0:
        win += 1
    kern = np.ones(win) / win
    is_stat = (np.convolve(ae, kern, mode='same') < zupt_accel_thresh) & \
              (np.convolve(ge, kern, mode='same') < zupt_gyro_thresh)

    return {
        'position': pos, 'velocity': vel, 'orientation': orientations,
        'is_stationary': is_stat, 'accel_world': accel_world,
    }


def estimate_per_rep_bar_path(accel_data, gyro_data, sample_rate,
                              rep_starts, rep_ends,
                              zupt_accel_thresh=0.8, zupt_gyro_thresh=0.3,
                              gravity=9.81):
    """
    Estimate bar path independently for each rep.

    Each rep is processed in isolation with constrained double integration.
    Padding is added before/after for filter settling, then trimmed.
    The constrained integration enforces v(0)=v(T)=0 and p(0)≈p(T),
    distributing any integration drift evenly across the segment.
    """
    n_total = len(accel_data)
    dt = 1.0 / sample_rate
    g_world = np.array([0.0, gravity, 0.0])

    # Full-session orientation (computed once for consistency)
    full_orient = estimate_orientation(accel_data, gyro_data, sample_rate)

    # Precompute full-session world-frame acceleration
    accel_world_full = np.zeros((n_total, 3))
    for i in range(n_total):
        R = quat_to_rotation_matrix(full_orient[i])
        accel_world_full[i] = R @ accel_data[i] - g_world

    results = []
    for start, end in zip(rep_starts, rep_ends):
        # Pad segment (0.3s each side for filter settling)
        pad_before = min(int(0.3 * sample_rate), start)
        pad_after = min(int(0.3 * sample_rate), n_total - end)
        seg_start = start - pad_before
        seg_end = end + pad_after
        seg_n = seg_end - seg_start

        if seg_n < 10:
            results.append({
                'position': np.zeros((end - start, 3)),
                'velocity': np.zeros((end - start, 3)),
                'orientation': full_orient[start:end].copy(),
            })
            continue

        # Extract world-frame acceleration
        seg_accel = accel_world_full[seg_start:seg_end].copy()

        # Low-pass filter to reduce noise before double integration.
        # 8 Hz keeps the rep dynamics (motion is 0.5-3 Hz) while cutting
        # noise that gets amplified by integration.
        nyq = 0.5 * sample_rate
        if seg_n > 15:
            b, a = butter(3, 8.0 / nyq, btype='low')
            for k in range(3):
                seg_accel[:, k] = filtfilt(b, a, seg_accel[:, k])

        # Constrained double integration
        vel, pos = _integrate_segment_constrained(seg_accel, dt)

        # Trim padding — return only the rep portion
        trim_s = pad_before
        trim_e = pad_before + (end - start)
        rep_pos = pos[trim_s:trim_e].copy()
        rep_vel = vel[trim_s:trim_e].copy()
        rep_orient = full_orient[start:end].copy()

        # Zero position to start of rep
        if len(rep_pos) > 0:
            rep_pos -= rep_pos[0]

        results.append({
            'position': rep_pos,
            'velocity': rep_vel,
            'orientation': rep_orient,
        })

    return results
