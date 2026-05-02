# Barbell Lab — IMU-Based Powerlifting Insights

An open-source, barbell-mounted IMU platform for **rep counting, per-rep bar-path reconstruction, velocity profiling, sticking-point detection, and load–velocity 1RM prediction**. Current scope: bench press (squat, deadlift, and 2-D bar-path reconstruction are in development).

The repo ships:

- **Hardware build** for a sub-$100 ESP32-S3 + dual LSM6DSOX barbell tracker.
- **Firmware** (Arduino sketch) that streams IMU samples over USB serial.
- **Analysis pipeline** in pure Python (NumPy + SciPy + Pandas) — no ML training required.
- **FastAPI** layer exposing the analyses as JSON endpoints.
- **React + Vite + Tailwind** dashboard that drives the API end-to-end.

**Authors:** Darius Sattari · Mashruf Mahin · Barbell Lab · Harvard SEAS

---

## Motivation

Velocity-based-training devices retail for $200–400 and are typically closed-source. No public dataset combines barbell-mounted IMU data with ground-truth velocity across the squat, bench press, and deadlift. This project addresses both gaps: a research-grade barbell tracker for under $100 and an end-to-end open analysis pipeline that others can reproduce, audit, and extend.

## Research hypotheses

The frontend's **Research** tab is the canonical, in-app statement of these. Summarized:

| # | Hypothesis | Method (as implemented) | Target |
|---|------------|-------------------------|--------|
| **H1** | A signal-processing pipeline can count squat / bench / deadlift reps from a single barbell-mounted IMU without per-lifter training. | Schmitt-trigger hysteresis on vertical velocity (vy ±0.25 m/s). gravity-removed a<sub>y</sub> → 5 Hz Butterworth low-pass → cumulative integration → 0.3 Hz high-pass to suppress integrator drift. Two post-rep gates filter false reps: a global-gyro rerack check and a 2.0 s post-motion test. | ≥ 95 % accuracy vs. logged rep counts |
| **H2** | A single 6-DoF IMU can recover per-rep 2-D bar trajectory with bounded drift. | Calibration-only orientation: gravity vector fitted from a 1 s pre-lift stillness window defines a static body-to-world rotation (no AHRS across the session — gyro integration through unrack events flips world-Z). Each rep is integrated once over its full lockout→chest→lockout cycle with linear endpoint anchoring on velocity AND position across all three axes; both endpoints share the same stationary pose, so drift is bounded inside the rep window. Output resampled to 120 points. | per-rep drift < 5 cm; consistent ROM within session |
| **H3** | IMU-derived velocity metrics predict 1RM better than Epley / Brzycki rep-based formulas. | **Primary:** linear load–velocity profile across ≥ 2 loads — best mean propulsive velocity (MPV) per load, OLS regression to a literature minimum velocity threshold (MVT = 0.17 m/s for bench), R²-weighted consensus across MPV / MCV / top-2-MPV variants, 2 000-iter bootstrap CI. **Single-set fallback:** mean of (a) González-Badillo 2011 population MPV→%1RM and (b) within-set velocity-loss → reps-in-reserve → %1RM via the Baechle rep table. | within 5 % of tested 1RM |
| **H4** | Phase-anchored sticking points are reproducible per lifter-exercise and predictive of proximity to failure. | Per-rep concentric velocity is scanned with `scipy.signal.find_peaks` for the initial drive peak and the deepest valley after it. A sticking point is accepted on velocity depth ≥ 0.04 m/s, post-valley resurgence ≥ 0.02 m/s, and the valley sitting within 10–90 % of concentric duration. | same lifter · same load → sticking time within ±10 % across sessions |

Validation harnesses live in [`src/rep_counting/validate_all.py`](src/rep_counting/validate_all.py), [`src/sticking_point/validate_sticking_point.py`](src/sticking_point/validate_sticking_point.py), and [`src/velocity/compare_methods.py`](src/velocity/compare_methods.py). Their JSON outputs sit in [`validation/`](validation/).

## Hardware

| Component | Product | ~Price |
|-----------|---------|-------:|
| IMU (×2) | Adafruit LSM6DSOX 6-DoF | $11.95 ea |
| MCU | Adafruit ESP32-S3 Feather | $17.50 |
| Data Logger | Adalogger FeatherWing (MicroSD + RTC) | $8.95 |
| Battery | 500 mAh LiPo 3.7 V | $7.95 |
| Wiring | STEMMA QT / Qwiic cables | $1.90 |
| Mounting | P-clamp + IP65 enclosure + cinch strap | ~$24.00 |
| **Total** | | **~$96** |

Both IMUs mount on the same barbell sleeve in a 3-D-printed dual-sensor bracket for redundancy and rotation cross-check. Datasheets live in [`hardware/datasheets/`](hardware/datasheets/). Bracket / clamp STLs are in development under [`hardware/cad/`](hardware/cad/).

## Repository structure

```
.
├── hardware/                       # Physical build
│   ├── cad/                        # 3-D-printable STLs (in development)
│   └── datasheets/                 # Component datasheets
│
├── firmware/                       # ESP32-S3 firmware skeleton
│   ├── src/                        # (see data_collection/data_collection.ino — current sketch)
│   ├── lib/
│   └── config/
│
├── data_collection/                # Sketch + capture/analysis scripts + recorded sessions
│   ├── data_collection.ino         # ESP32-S3 sketch (USB-serial CSV streamer)
│   ├── capture_serial.py           # Records sketch output to CSV
│   ├── analyze_session.py          # Standalone HTML report generator (Plotly)
│   ├── plot_session.py             # Quick PNG diagnostics for one session
│   ├── slide_figures.py            # Figure generator for write-ups / talks
│   ├── sample/                     # Three committed bench-press sessions (240/8, 265/5, 275/3)
│   └── session_*.csv               # Additional reference recordings
│
├── src/                            # Core Python analysis pipeline
│   ├── rep_counting/               # Schmitt-trigger rep counter + validation harness
│   ├── velocity/                   # Velocity integration (4 methods) + per-rep metrics
│   ├── sticking_point/             # Concentric valley detection + validation harness
│   ├── one_rm/                     # Load–velocity profile + 5 estimators + bootstrap CI
│   ├── bar_path/                   # Per-rep 3-D bar-path reconstruction (CLI + API router)
│   ├── api/                        # FastAPI app: sessions, analyze, one-rm, bar-path
│   ├── preprocessing/              # (reserved for future shared filtering helpers)
│   └── utils/                      # (reserved for shared I/O helpers)
│
├── frontend/                       # Vite + React + TS + Tailwind + shadcn/ui dashboard
│   ├── src/pages/                  # Sessions, Analysis, 1RM/Sticking, Research tabs
│   ├── src/components/             # Charts, primitives, layout
│   └── src/api/                    # Typed fetch wrappers for /api/*
│
├── validation/                     # JSON scoreboards from validation harnesses
│   ├── method_scores.json          # Velocity-method comparison (4 methods × 8 sessions)
│   ├── sticking_point_scores.json  # SP detection per session + aggregate
│   └── one_rm_scores.json          # 1RM consensus per lifter
│
├── docs/                           # Write-ups, figures, references
│   └── data-collection-procedure.md
│
├── tests/                          # (test scaffolding under tests/api/)
├── api_storage/                    # Local FastAPI session store (gitignored)
├── requirements.txt                # Python deps
└── README.md
```

Empty placeholder dirs (`data/`, `models/`, `notebooks/`) are reserved for downstream OpenCap / ML work and kept via `.gitkeep`. Recorded session CSVs live under `data_collection/` (those are committed) — large `data/raw/` captures and trained model artifacts are gitignored.

## Quick start

The fastest demo is **API + UI**, two terminals.

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Backend API (terminal 1, port 8000)

```bash
uvicorn src.api.app:app --reload --port 8000
```

Health check: <http://localhost:8000/api/health> → `{"status":"ok"}`. Interactive docs at <http://localhost:8000/docs>.

### 3. Frontend dashboard (terminal 2, port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the backend on port 8000, so the two processes feel like one app.

**To use the dashboard:**

1. **Sessions & Sets** tab — drag-drop a session CSV (e.g. `data_collection/sample/D_240_8.csv`) and optionally its annotations CSV. Enter load and lifter.
2. **Analysis** tab — pick a session to see vy trace, detected reps, per-rep MPV / MCV / PCV, and bar-path overlay.
3. **1RM & Sticking** tab — select two or more sessions of the same lifter at different loads and run the consensus 1RM estimator (LVP regression + bootstrap CI). One session falls back to GB population + within-set velocity-loss heuristics.
4. **Research** tab — read the live hypotheses + methods card.

### 4. Production-style single-process

```bash
cd frontend && npm run build && cd ..
uvicorn src.api.app:app --port 8000
```

The FastAPI app auto-mounts `frontend/dist/` at `/`, so the UI and API share one origin.

## CLI usage (no UI required)

Each analysis module has its own command-line entry. Pass any session CSV from `data_collection/` or your own.

**Per-session tools** — run on any single recorded set:

```bash
# Rep counting (Schmitt-trigger, no model file needed)
python -m src.rep_counting.sign_change_rep_counter \
    data_collection/sample/D_240_8.csv

# Per-rep velocity metrics — MPV / MCV / PCV / TPV / ROM
python src/velocity/velocity_metrics.py \
    data_collection/sample/D_240_8.csv \
    data_collection/sample/D_240_8_annotations.csv \
    --method B

# Per-rep sticking-point detection
python src/sticking_point/sticking_point.py \
    data_collection/sample/D_240_8.csv \
    data_collection/sample/D_240_8_annotations.csv

# Per-rep 3-D bar-path reconstruction (CLI)
python -m src.bar_path data_collection/sample/D_240_8.csv --out bar_path.json
```

**Validation harnesses** — run across the committed reference dataset (8 bench sessions × 2 lifters × 4 loads in `data_collection/`):

```bash
# Rep-counter accuracy vs. annotated rep counts
python src/rep_counting/validate_all.py

# Sticking-point detection + aggregate criteria
python src/sticking_point/validate_sticking_point.py \
    --out validation/sticking_point_scores.json

# Compare 4 velocity-integration methods (endpoint residual, ROM symmetry, ROM CV, load-velocity monotonicity)
python src/velocity/compare_methods.py \
    --out validation/method_scores.json

# 1RM consensus for one lifter across their LVP
python src/one_rm/one_rm.py --lifter D --method-details
```

The validation scripts read the eight reference sessions named `<lifter>_<load>_<reps>_session_<timestamp>.csv` (and matching `_annotations.csv`) shipped under `data_collection/`. Drop new recordings in alongside them and rerun — the rep counter and bar-path CLIs accept any single CSV.

For an end-to-end interactive HTML report on one session:

```bash
python data_collection/analyze_session.py data_collection/sample/D_240_8.csv \
    --exercise "Bench Press" --load 240
```

## API reference

All endpoints live under `/api`. The frontend calls the same routes.

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/health` | Liveness probe |
| `POST` | `/api/sessions` | Upload one session CSV (+ optional annotations) → returns `session_id` |
| `GET`  | `/api/sessions` | List all uploaded sessions |
| `DELETE` | `/api/sessions/{id}` | Delete a session |
| `POST` | `/api/sessions/{id}/analyze` | Rep boundaries, per-rep velocity metrics, sticking points, plot data |
| `POST` | `/api/sessions/{id}/bar-path` | Per-rep 3-D bar-path reconstruction |
| `POST` | `/api/one-rm` | Multi-session 1RM consensus + 95 % bootstrap CI |

Sessions are persisted under `api_storage/` (gitignored). Stop and restart the server without losing your demo state.

## Data collection

Recording new sessions is documented in [`docs/data-collection-procedure.md`](docs/data-collection-procedure.md). Quick version:

1. Flash [`data_collection/data_collection.ino`](data_collection/data_collection.ino) onto the ESP32-S3 Feather (Arduino IDE; install Adafruit `LSM6DS` and `Adafruit Unified Sensor`).
2. Mount the bracket on the bar sleeve, USB-tether to your laptop.
3. Run the capture script:
   ```bash
   pip install pyserial
   python data_collection/capture_serial.py
   ```
4. Optionally annotate rep tops + rack timing in a sibling `_annotations.csv` (one row per rep top, one row labeled `rack`).
5. Drop the resulting CSV into the dashboard or pass it to any of the CLI modules above.

## Validation results (current dataset)

The reference dataset under `data_collection/` is 11 bench-press sessions across 2 lifters (Darius, Mashruf) at loads 135 / 155 / 175 / 185 lb plus three additional captures used for rep-counter regression. Numbers below are reproducible by running the harnesses above:

| Module | Result |
|--------|--------|
| Rep counting (`validate_all.py`) | **73 / 73 reps detected · 11 / 11 sessions PASS · 0 misses, 0 extras** |
| Velocity methods (`compare_methods.py`) | `B_det` (per-rep endpoint detrend) wins: 0 m/s endpoint residual, 0.21 m ROM symmetry residual, 0.13 ROM CV |
| Sticking-point detection (`validate_sticking_point.py`) | **7 / 8 panels PASS** · A1 detection rate 31 % · A2 load-monotone depth 4 / 4 lifter pairs · A3 SP frac in [10 %, 90 %] 16 / 16 |
| 1RM consensus (Darius LVP, 4 sessions) | **305.8 lb · 95 % CI [236, 351] · LVP-consensus** |

Full JSON scoreboards: [`validation/method_scores.json`](validation/method_scores.json), [`validation/sticking_point_scores.json`](validation/sticking_point_scores.json), [`validation/one_rm_scores.json`](validation/one_rm_scores.json).

OpenCap-based markerless motion-capture ground truth for bar velocity and trajectory is the next validation step, not in this revision.

## Key references

1. Uhlrich et al. (2023). *OpenCap: Human movement dynamics from smartphone videos.* PLOS Computational Biology.
2. Renner et al. (2024). *Concurrent validity of novel smartphone-based apps monitoring barbell velocity in powerlifting exercises.* PLOS ONE.
3. Kim et al. (2024). *Intelligent Repetition Counting for Unseen Exercises.* arXiv:2410.00407.
4. Pérez-Castilla et al. (2021). *Machine learning and load–velocity profiling to estimate 1RM for bench press.* Sports.
5. Sbrollini et al. (2022). *Validation of an automatic inertial sensor-based methodology for barbell velocity monitoring.* Sensors.
6. González-Badillo & Sánchez-Medina (2010). *Movement velocity as a measure of loading intensity in resistance training.* Int. J. Sports Med.
7. Morán-Navarro et al. (2017). *Time course of recovery following resistance training leading or not to failure.* Eur. J. Appl. Physiol.

## License

TBD.
