# IMU Barbell Tracker — Data Collection Test Procedure

## Hardware Setup

1. Mount the IMU device securely to the barbell sleeve using the 3D-printed clamp.
2. Connect the ESP32-S3 to your laptop via USB-C.
3. Confirm the LED on the board is solid (powered) — if blinking, wait for it to stabilize.

## Software Setup

Ensure `pyserial` is installed:

```bash
pip install pyserial
```

Navigate to the `data_collection/` directory:

```bash
cd data_collection/
```

## Running a Trial

### Without Annotation (basic capture)

```bash
python3 capture_serial.py
```

### With Keystroke Annotation (recommended)

Specify the number of reps with `--reps`. For a 10-rep set:

```bash
python3 capture_serial.py --reps 10
```

The script will auto-detect the ESP32 serial port, connect, and send the START command. Once `>> RECORDING` appears, data is streaming at 200 Hz.

## Annotation Protocol

When `--reps` is enabled, the terminal prompts you to press **Enter** at each position change. The sequence for a 10-rep bench press set is:

| Press | Label | Meaning |
|-------|-------|---------|
| 1 | `lockout` | Bar at top, arms locked out (unrack complete) |
| 2 | `chest` | Bar touches chest (bottom of rep 1) |
| 3 | `1` | Lockout at top (rep 1 complete) |
| 4 | `chest` | Bar touches chest (bottom of rep 2) |
| 5 | `2` | Lockout at top (rep 2 complete) |
| ... | ... | ...alternating `chest` and rep number... |
| 21 | `10` | Lockout at top (rep 10 complete) |
| 22 | `rack` | Bar re-racked |

The terminal displays the current label and what comes next, so you don't need to keep count. Each press logs a `timestamp_ms` aligned to the IMU data timeline.

### Tips for Clean Annotations

- Have a training partner press Enter while you lift, or position the laptop where you can tap Enter between reps.
- Press at the moment of position change, not after — reaction delay is unavoidable but try to minimize it.
- If you miss a press or press too early, note the rep number and fix the annotation file manually after the session.

## Stopping the Trial

Press **Ctrl+C** to stop recording. The script sends a STOP command to the device and closes all files cleanly.

## Output Files

After a session, you'll find these in the output directory (default: `data_collection/`):

| File | Contents |
|------|----------|
| `session_YYYYMMDD_HHMMSS.csv` | Raw IMU data — `timestamp_ms, a1x, a1y, a1z, g1x, g1y, g1z` at 200 Hz |
| `session_YYYYMMDD_HHMMSS_annotations.csv` | Keystroke annotations — `timestamp_ms, label` (only present if `--reps` was used) |

### Example Annotation File

```csv
timestamp_ms,label
2104.3,lockout
5287.1,chest
6493.8,1
8012.5,chest
9201.7,2
```

## Verification Checklist

After each session, confirm:

- [ ] IMU CSV has the expected number of samples (~200 per second of recording)
- [ ] Annotation CSV has the correct number of entries (2 × reps + 2 for lockout and rack)
- [ ] Timestamps in the annotation file fall within the IMU data's time range
- [ ] No large gaps in IMU `timestamp_ms` (would indicate dropped samples)

## Optional Arguments

```
--port /dev/cu.usbmodem3101    Override auto-detected serial port
--baud 115200                  Set baud rate (default: 115200)
--output ./data                Set output directory (default: current dir)
--reps N                       Enable annotation mode for N reps
```
