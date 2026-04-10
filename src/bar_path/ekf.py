"""
Extended Kalman Filter for IMU-based Barbell Tracking
=====================================================

Fuses 6-DOF IMU data (accelerometer + gyroscope) to estimate:
  - 3D orientation (quaternion)
  - 3D velocity (m/s)
  - 3D position (m)

Based on Kok, Hol, & Schön (2017) methodology with adaptations for
barbell-mounted IMU:
  - Gravity reference updates correct orientation drift
  - Zero-velocity updates (ZUPT) bound position drift between reps
  - Per-rep position reset ensures each rep starts at the origin

State vector (10):
  q = [qw, qx, qy, qz]   — orientation quaternion (sensor → world)
  v = [vx, vy, vz]        — velocity in world frame (m/s)
  p = [px, py, pz]         — position in world frame (m)

IMU orientation convention (user-defined):
  Y = up (gravity axis)
  -X = forward (toward lifter in unracked position)
  Z = lateral

Author: Darius Sattari (Harvard)
"""

import numpy as np
from scipy.signal import butter, filtfilt


# ── Quaternion utilities ────────────────────────────────────────────

def quat_mult(q, r):
    """Hamilton product of two quaternions q ⊗ r."""
    qw, qx, qy, qz = q
    rw, rx, ry, rz = r
    return np.array([
        qw*rw - qx*rx - qy*ry - qz*rz,
        qw*rx + qx*rw + qy*rz - qz*ry,
        qw*ry - qx*rz + qy*rw + qz*rx,
        qw*rz + qx*ry - qy*rx + qz*rw,
    ])


def quat_conj(q):
    """Conjugate of a quaternion."""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_normalize(q):
    """Normalize quaternion to unit length."""
    n = np.linalg.norm(q)
    if n < 1e-10:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_to_rotation_matrix(q):
    """Convert unit quaternion to 3x3 rotation matrix (sensor → world)."""
    q = quat_normalize(q)
    qw, qx, qy, qz = q
    return np.array([
        [1 - 2*(qy**2 + qz**2),     2*(qx*qy - qz*qw),     2*(qx*qz + qy*qw)],
        [    2*(qx*qy + qz*qw), 1 - 2*(qx**2 + qz**2),     2*(qy*qz - qx*qw)],
        [    2*(qx*qz - qy*qw),     2*(qy*qz + qx*qw), 1 - 2*(qx**2 + qy**2)],
    ])


def quat_from_two_vectors(v_from, v_to):
    """Quaternion that rotates v_from to align with v_to."""
    v_from = v_from / np.linalg.norm(v_from)
    v_to = v_to / np.linalg.norm(v_to)
    cross = np.cross(v_from, v_to)
    dot = np.dot(v_from, v_to)
    if dot < -0.999999:
        # Vectors are anti-parallel; pick an arbitrary perpendicular axis
        perp = np.array([1, 0, 0]) if abs(v_from[0]) < 0.9 else np.array([0, 1, 0])
        axis = np.cross(v_from, perp)
        axis = axis / np.linalg.norm(axis)
        return np.array([0.0, axis[0], axis[1], axis[2]])
    w = 1.0 + dot
    q = np.array([w, cross[0], cross[1], cross[2]])
    return quat_normalize(q)


def rotate_vector_by_quat(q, v):
    """Rotate vector v by quaternion q: v' = q ⊗ [0,v] ⊗ q*."""
    v_quat = np.array([0.0, v[0], v[1], v[2]])
    rotated = quat_mult(quat_mult(q, v_quat), quat_conj(q))
    return rotated[1:4]


# ── EKF Implementation ─────────────────────────────────────────────

class BarbellEKF:
    """
    Extended Kalman Filter for barbell position tracking.

    Uses an error-state (indirect) formulation where the nominal state
    is propagated with the gyroscope, and the error state is corrected
    by accelerometer gravity references and ZUPT.
    """

    def __init__(self, dt, gravity=9.81):
        self.dt = dt
        self.g = gravity
        self.g_world = np.array([0.0, self.g, 0.0])  # Y-up convention

        # ── Nominal state ──
        self.q = np.array([1.0, 0.0, 0.0, 0.0])  # orientation quaternion
        self.v = np.zeros(3)                        # velocity (world frame)
        self.p = np.zeros(3)                        # position (world frame)

        # ── Error-state covariance (9x9) ──
        # Error state: [dθ(3), dv(3), dp(3)]
        # dθ = orientation error (rotation vector)
        # dv = velocity error
        # dp = position error
        self.P = np.eye(9) * 0.01

        # ── Process noise ──
        self.sigma_gyro = 0.01       # rad/s — gyroscope noise density
        self.sigma_accel = 0.5       # m/s² — accelerometer noise density
        self.sigma_gyro_bias = 0.001 # rad/s² — gyro bias random walk (unused for now)

        # ── Measurement noise ──
        self.sigma_gravity = 0.5     # m/s² — gravity reference measurement noise
        self.sigma_zupt = 0.01       # m/s — ZUPT velocity measurement noise

    def initialize_from_accel(self, accel):
        """
        Initialize orientation quaternion so that the measured acceleration
        (which should be ~gravity when stationary) maps to the world-frame
        gravity vector [0, g, 0].
        """
        # In sensor frame, gravity points in the direction of the accel reading
        accel_normalized = accel / np.linalg.norm(accel)
        # World-frame gravity direction
        gravity_world = np.array([0.0, 1.0, 0.0])
        # Find quaternion that rotates sensor gravity to world gravity
        self.q = quat_from_two_vectors(accel_normalized, gravity_world)
        self.v = np.zeros(3)
        self.p = np.zeros(3)
        self.P = np.eye(9) * 0.01

    def predict(self, gyro, accel):
        """
        Prediction step: propagate state using gyroscope and accelerometer.

        Args:
            gyro: [gx, gy, gz] in rad/s (sensor frame)
            accel: [ax, ay, az] in m/s² (sensor frame)
        """
        dt = self.dt

        # ── 1. Update orientation with gyroscope ──
        omega = gyro  # angular velocity in sensor frame
        omega_norm = np.linalg.norm(omega)

        if omega_norm > 1e-8:
            # Quaternion derivative: dq/dt = 0.5 * q ⊗ [0, ω]
            angle = omega_norm * dt
            axis = omega / omega_norm
            # Small rotation quaternion
            dq = np.array([
                np.cos(angle / 2),
                axis[0] * np.sin(angle / 2),
                axis[1] * np.sin(angle / 2),
                axis[2] * np.sin(angle / 2),
            ])
            self.q = quat_normalize(quat_mult(self.q, dq))

        # ── 2. Rotate accel to world frame and remove gravity ──
        R = quat_to_rotation_matrix(self.q)
        accel_world = R @ accel  # sensor → world
        accel_linear = accel_world - self.g_world  # remove gravity

        # ── 3. Integrate velocity and position ──
        self.p = self.p + self.v * dt + 0.5 * accel_linear * dt**2
        self.v = self.v + accel_linear * dt

        # ── 4. Propagate error-state covariance ──
        # Linearized state transition for error state
        F = np.eye(9)
        # dθ propagation (gyro integration)
        F[0:3, 0:3] = np.eye(3) - self._skew(omega) * dt
        # dv depends on orientation error (cross product with accel)
        F[3:6, 0:3] = -R @ self._skew(accel) * dt
        # dp depends on dv
        F[6:9, 3:6] = np.eye(3) * dt

        # Process noise
        Q = np.zeros((9, 9))
        Q[0:3, 0:3] = np.eye(3) * (self.sigma_gyro * dt)**2
        Q[3:6, 3:6] = np.eye(3) * (self.sigma_accel * dt)**2
        Q[6:9, 6:9] = np.eye(3) * (self.sigma_accel * dt**2 / 2)**2

        self.P = F @ self.P @ F.T + Q

    def update_gravity(self, accel, weight=1.0):
        """
        Measurement update using accelerometer as a gravity reference.

        When the bar is not accelerating much, the accelerometer reading
        should point in the direction of gravity. This corrects orientation
        drift, especially around the horizontal axes.

        Args:
            accel: [ax, ay, az] in m/s² (sensor frame)
            weight: scaling factor for measurement confidence (0-1)
        """
        R = quat_to_rotation_matrix(self.q)

        # Predicted gravity in sensor frame: g_sensor = R^T @ g_world
        g_pred = R.T @ self.g_world

        # Measurement: normalized accelerometer reading scaled to g
        accel_norm = np.linalg.norm(accel)
        if accel_norm < 1e-6:
            return

        g_meas = accel / accel_norm * self.g

        # Innovation (measurement residual)
        y = g_meas - g_pred  # 3x1

        # Measurement Jacobian: H maps error state to predicted measurement change
        # d(g_pred)/d(dθ) = [g_pred]× (skew symmetric matrix)
        H = np.zeros((3, 9))
        H[0:3, 0:3] = self._skew(g_pred)

        # Measurement noise (scaled by weight — lower weight = more noise)
        R_noise = np.eye(3) * (self.sigma_gravity / max(weight, 0.1))**2

        # Kalman gain
        S = H @ self.P @ H.T + R_noise
        K = self.P @ H.T @ np.linalg.inv(S)

        # Error state correction
        dx = K @ y

        # Apply correction
        self._apply_error_state(dx)

        # Update covariance
        I_KH = np.eye(9) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R_noise @ K.T  # Joseph form

    def update_zupt(self):
        """
        Zero-velocity update: when the bar is stationary, force velocity to zero.
        This is the most powerful drift correction available.
        """
        # Measurement: velocity should be zero
        y = -self.v  # innovation = 0 - v_predicted

        # Measurement Jacobian: H maps error state to velocity
        H = np.zeros((3, 9))
        H[0:3, 3:6] = np.eye(3)

        # Measurement noise
        R_noise = np.eye(3) * self.sigma_zupt**2

        # Kalman gain
        S = H @ self.P @ H.T + R_noise
        K = self.P @ H.T @ np.linalg.inv(S)

        # Error state correction
        dx = K @ y

        # Apply correction
        self._apply_error_state(dx)

        # Update covariance (Joseph form for numerical stability)
        I_KH = np.eye(9) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R_noise @ K.T

    def _apply_error_state(self, dx):
        """Apply error-state correction to nominal state."""
        # Orientation correction
        dtheta = dx[0:3]
        angle = np.linalg.norm(dtheta)
        if angle > 1e-8:
            axis = dtheta / angle
            dq = np.array([
                np.cos(angle / 2),
                axis[0] * np.sin(angle / 2),
                axis[1] * np.sin(angle / 2),
                axis[2] * np.sin(angle / 2),
            ])
            self.q = quat_normalize(quat_mult(self.q, dq))

        # Velocity and position correction
        self.v += dx[3:6]
        self.p += dx[6:9]

    @staticmethod
    def _skew(v):
        """Skew-symmetric matrix from 3-vector."""
        return np.array([
            [    0, -v[2],  v[1]],
            [ v[2],     0, -v[0]],
            [-v[1],  v[0],     0],
        ])


# ── High-level processing function ─────────────────────────────────

def estimate_bar_path(accel_data, gyro_data, sample_rate,
                      zupt_accel_thresh=1.5, zupt_gyro_thresh=0.15,
                      gravity=9.81):
    """
    Estimate 3D bar path from raw IMU data using EKF.

    Args:
        accel_data: Nx3 array of accelerometer readings (m/s²)
        gyro_data:  Nx3 array of gyroscope readings (rad/s)
        sample_rate: Hz
        zupt_accel_thresh: stationary detection threshold for accel energy
        zupt_gyro_thresh: stationary detection threshold for gyro energy
        gravity: local gravity magnitude

    Returns:
        dict with keys:
            'position': Nx3 array (m), world frame [X, Y, Z]
            'velocity': Nx3 array (m/s), world frame
            'orientation': Nx4 array (quaternions)
            'is_stationary': Nx1 boolean array
            'accel_world': Nx3 array, gravity-compensated world-frame acceleration
    """
    n = len(accel_data)
    dt = 1.0 / sample_rate

    # ── Detect stationary periods ──
    # Low-pass filter for stable energy estimation
    nyq = 0.5 * sample_rate
    b, a = butter(2, 2.0 / nyq, btype='low')

    accel_lin_energy = np.zeros(n)
    gyro_energy = np.zeros(n)

    # We need gravity removal for energy calculation
    # Use first second as calibration
    cal_n = min(sample_rate, n)
    gravity_bias = np.mean(accel_data[:cal_n], axis=0)

    accel_debiased = accel_data - gravity_bias
    accel_lin_energy = np.sqrt(np.sum(accel_debiased**2, axis=1))
    gyro_energy_raw = np.sqrt(np.sum(gyro_data**2, axis=1))

    if n > 12:  # filtfilt needs minimum length
        accel_lin_energy = filtfilt(b, a, accel_lin_energy)
        gyro_energy = filtfilt(b, a, gyro_energy_raw)
    else:
        gyro_energy = gyro_energy_raw

    is_stationary = (accel_lin_energy < zupt_accel_thresh) & (gyro_energy < zupt_gyro_thresh)

    # ── Initialize EKF ──
    ekf = BarbellEKF(dt, gravity)
    ekf.initialize_from_accel(np.mean(accel_data[:cal_n], axis=0))

    # Tune process noise based on sensor characteristics
    ekf.sigma_gyro = 0.01
    ekf.sigma_accel = 0.5
    ekf.sigma_gravity = 0.3
    ekf.sigma_zupt = 0.005

    # ── Output arrays ──
    positions = np.zeros((n, 3))
    velocities = np.zeros((n, 3))
    orientations = np.zeros((n, 4))
    accel_world_out = np.zeros((n, 3))

    orientations[0] = ekf.q

    # ── Run EKF ──
    for i in range(1, n):
        accel = accel_data[i]
        gyro = gyro_data[i]

        # Prediction step
        ekf.predict(gyro, accel)

        # Gravity reference update
        # Weight based on how close accel magnitude is to gravity
        # (high dynamic acceleration = low weight = less trust in gravity ref)
        accel_mag = np.linalg.norm(accel)
        gravity_weight = np.exp(-5.0 * abs(accel_mag - gravity) / gravity)

        # Only apply gravity update when acceleration is reasonably close to g
        if gravity_weight > 0.3:
            ekf.update_gravity(accel, weight=gravity_weight)

        # ZUPT update
        if is_stationary[i]:
            ekf.update_zupt()

        # Store results
        R = quat_to_rotation_matrix(ekf.q)
        accel_world = R @ accel - np.array([0, gravity, 0])

        positions[i] = ekf.p.copy()
        velocities[i] = ekf.v.copy()
        orientations[i] = ekf.q.copy()
        accel_world_out[i] = accel_world

    return {
        'position': positions,
        'velocity': velocities,
        'orientation': orientations,
        'is_stationary': is_stationary,
        'accel_world': accel_world_out,
    }


def estimate_per_rep_bar_path(accel_data, gyro_data, sample_rate,
                              rep_starts, rep_ends,
                              zupt_accel_thresh=1.5, zupt_gyro_thresh=0.15,
                              gravity=9.81):
    """
    Estimate bar path independently for each rep.

    Running EKF per-rep bounds drift to within each rep's duration (~2s)
    rather than the full session. Position is zeroed to lockout (rep start).

    Args:
        accel_data: Nx3 array
        gyro_data: Nx3 array
        sample_rate: Hz
        rep_starts: list of start indices for each rep
        rep_ends: list of end indices for each rep
        zupt_accel_thresh, zupt_gyro_thresh: ZUPT thresholds
        gravity: local gravity

    Returns:
        list of dicts, one per rep, each containing:
            'position': Mx3 (m), zeroed to rep start
            'velocity': Mx3 (m/s)
            'orientation': Mx4 (quaternions)
    """
    results = []

    for start, end in zip(rep_starts, rep_ends):
        # Pad slightly before/after for filter settling
        pad = min(20, start)  # 0.1s at 200Hz
        seg_start = start - pad
        seg_end = min(end + pad, len(accel_data))

        seg_accel = accel_data[seg_start:seg_end]
        seg_gyro = gyro_data[seg_start:seg_end]

        result = estimate_bar_path(
            seg_accel, seg_gyro, sample_rate,
            zupt_accel_thresh, zupt_gyro_thresh, gravity
        )

        # Trim padding and zero position to rep start
        trim_start = pad
        trim_end = trim_start + (end - start)

        pos = result['position'][trim_start:trim_end].copy()
        pos -= pos[0]  # zero to start of rep

        results.append({
            'position': pos,
            'velocity': result['velocity'][trim_start:trim_end],
            'orientation': result['orientation'][trim_start:trim_end],
        })

    return results
