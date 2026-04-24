# IMU-Based Device for Powerlifting Insights

An open-source barbell-mounted IMU system for automated rep counting, 3D bar path reconstruction, velocity profiling, and 1RM prediction across the squat, bench press, and deadlift.

**Authors:** Darius Sattari & Mashruf Mahin

---

## Motivation

Velocity-based training (VBT) devices cost $200–400 and are typically closed-source. Meanwhile, no public dataset currently combines barbell-mounted IMU data with ground-truth velocity across all three competition powerlifts. This project addresses both gaps: we build a research-grade barbell tracker for under $100 and release an open data-collection and analysis pipeline that others can reproduce and extend.

## Hypotheses

1. A neural network trained on windowed IMU time-series can count squat, bench press, and deadlift repetitions with **>95% accuracy** given a user-specified exercise type.
2. An Extended Kalman Filter (EKF) fusing accelerometer and gyroscope data can reconstruct bar path trajectories that closely match OpenCap markerless motion-capture ground truth.
3. IMU-derived velocity metrics can predict 1-rep max within **5% of actual** values, outperforming traditional Epley/Brzycki estimation formulas.

## Hardware Overview

| Component | Product | ~Price |
|-----------|---------|-------:|
| IMU (×2) | Adafruit LSM6DSOX 6-DoF | $11.95 ea |
| MCU | Adafruit ESP32-S3 Feather | $17.50 |
| Data Logger | Adalogger FeatherWing (MicroSD + RTC) | $8.95 |
| Battery | 500 mAh LiPo 3.7V | $7.95 |
| Wiring | STEMMA QT / Qwiic cables | $1.90 |
| Mounting | P-clamp + IP65 enclosure + cinch strap | ~$24.00 |
| **Total** | | **~$96** |

Both IMU sensors are mounted on the same barbell end (dual-sensor bracket, 3D-printed) for redundancy and rotation detection. Full BOM and build instructions live in [`hardware/`](hardware/).

## Repository Structure

```
.
├── hardware/              # Physical build
│   ├── cad/               # 3D-printable STLs (dual-IMU bracket, P-clamp cradle)
│   └── datasheets/        # Component datasheets (LSM6DSOX, ESP32-S3, etc.)
│
├── firmware/              # ESP32-S3 firmware (Arduino / CircuitPython)
│   ├── src/               # Main firmware source
│   ├── lib/               # Vendored or local libraries
│   └── config/            # Sampling rate, BLE, SD-card settings
│
├── data/                  # All experimental data (not committed — see .gitignore)
│   ├── raw/               # Unprocessed IMU binary / CSV from SD card
│   ├── processed/         # Cleaned, aligned, labeled datasets
│   ├── opencap/           # OpenCap motion-capture exports (ground truth)
│   └── external/          # Public datasets (RecGym, MM-Fit, etc.)
│
├── notebooks/             # Jupyter notebooks for EDA, prototyping, figures
│
├── models/                # ML / signal-processing models
│   ├── trained/           # Saved model weights / checkpoints
│   └── configs/           # Hyperparameter configs and training recipes
│
├── src/                   # Core Python analysis pipeline
│   ├── preprocessing/     # Raw IMU → cleaned, gravity-compensated signals
│   ├── rep_counting/      # NN-based repetition counting
│   ├── bar_path/          # EKF bar path reconstruction
│   ├── velocity/          # Mean concentric velocity, peak velocity, profiles
│   ├── one_rm/            # Load–velocity profiling & 1RM prediction
│   └── utils/             # Shared helpers (I/O, plotting, constants)
│
├── validation/            # Scripts comparing IMU outputs to OpenCap ground truth
│
├── docs/                  # Write-ups, figures, and references
│   ├── figures/           # Generated plots and diagrams
│   └── references/        # Key papers (PDFs or BibTeX)
│
├── .gitignore
└── README.md
```

## Project Milestones

| # | Milestone | Key Deliverable |
|---|-----------|-----------------|
| 1 | Data-collection protocol & hardware build | Mounted, tested device; documented protocol |
| 2 | Data acquisition (squat / bench / deadlift) | Synchronized IMU + OpenCap recordings across subjects and loads (45–90% 1RM) |
| 3 | Data preparation | Cleaned, time-aligned, labeled dataset |
| 4 | Rep counting model | Trained NN with >95% accuracy, <1 rep error per set |
| 5 | Bar path reconstruction | EKF pipeline; RMSE & correlation vs. OpenCap |
| 6 | Feature engineering & metric extraction | Velocity profiles, sticking-point detection, 1RM estimates |
| 7 | End-to-end validation & final report | Statistical comparison of IMU-only vs. IMU+OpenCap; written report |

## Getting Started

### Firmware

```bash
# Install PlatformIO (recommended) or use Arduino IDE
cd firmware/
# Flash to ESP32-S3 Feather — see firmware/README.md for details
```

### Python Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Pipeline

```bash
# 1. Offload raw data from MicroSD into data/raw/
# 2. Preprocess
python -m src.preprocessing.run --input data/raw/ --output data/processed/

# 3. Rep counting
python -m src.rep_counting.train --config models/configs/rep_counting.yaml

# 4. Bar path reconstruction
python -m src.bar_path.reconstruct --input data/processed/ --output data/processed/

# 5. Velocity & 1RM
python -m src.velocity.profile --input data/processed/
python -m src.one_rm.predict --input data/processed/
```

### Web UI + API

Two processes, two ports. FastAPI serves the analysis endpoints; Vite runs the React frontend and proxies `/api/*` through.

```bash
# Terminal 1 — analysis API (port 8000)
uvicorn src.api.app:app --reload --port 8000

# Terminal 2 — UI dev server (port 5173, on the `ui` branch)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Drag-drop a bench-press CSV (with an optional annotations CSV), enter load and lifter, then open the session for velocity metrics + sticking-point detection, or select two or more sessions and run the 1RM consensus.

For a production-style single-process serve, run `npm run build` and FastAPI will mount `frontend/dist/` at `/`.

## Validation Approach

Ground truth is captured via **OpenCap** (smartphone-based markerless motion capture, validated to within 2–10° of marker-based systems). IMU-derived bar paths and velocities are compared against OpenCap trajectories using RMSE, Pearson correlation, and Bland-Altman analysis.

## Key References

1. Uhlrich et al. (2023). *OpenCap: Human movement dynamics from smartphone videos.* PLOS Computational Biology.
2. Renner et al. (2024). *Concurrent validity of novel smartphone-based apps monitoring barbell velocity in powerlifting exercises.* PLOS ONE.
3. Kim et al. (2024). *Intelligent Repetition Counting for Unseen Exercises.* arXiv:2410.00407.
4. Perez-Castilla et al. (2021). *ML and load–velocity profiling to estimate 1RM for bench press.* Sports.
5. Sbrollini et al. (2022). *Validation of an automatic inertial sensor-based methodology for barbell velocity monitoring.* Sensors.

## License

TBD
