#!/usr/bin/env python3
"""
IMU Barbell Tracker — Serial Data Capture
==========================================
Captures CSV data streamed from the ESP32-S3 over USB serial
and saves it to timestamped .csv files.

Usage:
    python3 capture_serial.py
    python3 capture_serial.py --port /dev/cu.usbmodem3101 --baud 115200 --output ./data
    python3 capture_serial.py --reps 10          # enable keystroke annotation for 10 reps

Annotation mode (--reps):
    While recording, press Enter to mark positions in sequence:
        lockout → chest → 1 → chest → 2 → chest → ... → chest → N → rack
    Annotations are saved to a companion CSV: session_..._annotations.csv
    with columns: timestamp_ms, label

The script auto-detects the serial port on macOS. Press Ctrl+C to quit.
"""

import serial
import serial.tools.list_ports
import argparse
import os
import sys
import threading
import time as time_mod
from datetime import datetime


def find_esp32_port():
    """Auto-detect the ESP32-S3 serial port."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        # Match common ESP32-S3 Feather port names
        if "usbmodem" in port.device.lower() or "usb" in port.device.lower():
            return port.device
        if "esp" in port.description.lower() or "feather" in port.description.lower():
            return port.device

    # Show available ports if auto-detect fails
    if ports:
        print("Could not auto-detect ESP32. Available ports:")
        for port in ports:
            print(f"  {port.device} — {port.description}")
        return ports[0].device

    return None


def build_annotation_sequence(num_reps):
    """
    Build the ordered list of labels the user cycles through with Enter.

    For a 10-rep set the sequence is:
        lockout, chest, 1, chest, 2, chest, 3, ..., chest, 10, rack

    'lockout'  = initial position at the top before rep 1
    'chest'    = bar on chest (bottom of each rep)
    '1'–'N'    = lockout at the top after the concentric phase
    'rack'     = bar re-racked at the end
    """
    seq = ["lockout"]
    for rep in range(1, num_reps + 1):
        seq.append("chest")
        seq.append(str(rep))
    seq.append("rack")
    return seq


def annotation_listener(ann_state):
    """
    Background thread: blocks on input() waiting for Enter presses.
    Each press records a timestamp and advances to the next label.
    """
    seq = ann_state["sequence"]
    idx = 0

    print(f"\n   [ANNOTATE] Press Enter to mark: {seq[idx]}")

    while idx < len(seq) and ann_state["active"]:
        try:
            input()  # blocks until Enter
        except EOFError:
            break

        if not ann_state["active"]:
            break

        # Compute ms elapsed since DATA_START (aligns with IMU timestamp_ms)
        now = time_mod.perf_counter()
        elapsed_ms = (now - ann_state["t0"]) * 1000.0

        label = seq[idx]
        ann_state["file"].write(f"{elapsed_ms:.1f},{label}\n")
        ann_state["file"].flush()
        ann_state["annotations"].append((elapsed_ms, label))

        print(f"   [ANNOTATE] ✓ {label} @ {elapsed_ms/1000:.2f}s", end="")

        idx += 1
        if idx < len(seq):
            print(f"  — next: {seq[idx]}")
        else:
            print("  — all positions marked!")

    ann_state["active"] = False


def main():
    parser = argparse.ArgumentParser(description="Capture IMU data from ESP32-S3 over USB serial")
    parser.add_argument("--port", type=str, default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--output", type=str, default=".", help="Output directory for CSV files (default: current dir)")
    parser.add_argument("--reps", type=int, default=0,
                        help="Number of reps — enables keystroke annotation mode (e.g. --reps 10)")
    args = parser.parse_args()

    # Find port
    port = args.port or find_esp32_port()
    if not port:
        print("ERROR: No serial port found. Is the ESP32-S3 plugged in?")
        sys.exit(1)

    # Ensure output directory exists
    os.makedirs(args.output, exist_ok=True)

    print(f"Connecting to {port} at {args.baud} baud...")

    try:
        ser = serial.Serial(port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"ERROR: Could not open {port}: {e}")
        sys.exit(1)

    print(f"Connected! Waiting for device to initialize...")

    # Give the ESP32 time to boot and print its startup info
    import time
    time.sleep(3)

    # Drain and display any startup messages already in the buffer
    while ser.in_waiting:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            print(line)

    # Send START command to begin recording automatically
    print("\nSending START command...")
    ser.write(b"START\n")
    print("Recording! Press Ctrl+C to stop.\n")

    recording = False
    csv_file = None
    sample_count = 0
    start_time = None
    ann_state = None
    ann_thread = None

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()

            if not line:
                continue

            # Detect start of data stream
            if line == "---DATA_START---":
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(args.output, f"session_{timestamp}.csv")
                csv_file = open(filename, "w")
                recording = True
                sample_count = 0
                start_time = datetime.now()
                print(f"\n>> RECORDING to {filename}")

                # Start annotation thread if --reps was specified
                if args.reps > 0:
                    ann_filename = os.path.join(
                        args.output, f"session_{timestamp}_annotations.csv"
                    )
                    ann_file = open(ann_filename, "w")
                    ann_file.write("timestamp_ms,label\n")
                    ann_file.flush()

                    ann_state = {
                        "sequence": build_annotation_sequence(args.reps),
                        "t0": time_mod.perf_counter(),
                        "file": ann_file,
                        "annotations": [],
                        "active": True,
                    }
                    ann_thread = threading.Thread(
                        target=annotation_listener, args=(ann_state,), daemon=True
                    )
                    ann_thread.start()

                continue

            # Detect end of data stream
            if line == "---DATA_STOP---":
                # Stop annotation thread
                if ann_state and ann_state["active"]:
                    ann_state["active"] = False
                    if ann_state["file"]:
                        ann_state["file"].close()
                    n_ann = len(ann_state["annotations"])
                    print(f"   Annotations: {n_ann} positions marked")

                if csv_file:
                    csv_file.close()
                    csv_file = None
                duration = (datetime.now() - start_time).total_seconds() if start_time else 0
                print(f"\n>> STOPPED — {sample_count} samples in {duration:.1f}s")
                if sample_count > 0 and duration > 0:
                    print(f"   Avg rate: {sample_count/duration:.1f} Hz")
                print(f"   Saved to: {filename}")
                if ann_state:
                    print(f"   Annotations: {ann_filename}")
                recording = False
                continue

            # Write CSV data
            if recording and csv_file:
                csv_file.write(line + "\n")
                sample_count += 1

                # Flush every 200 samples (~1 second at 200Hz)
                if sample_count % 200 == 0:
                    csv_file.flush()
                    elapsed = (datetime.now() - start_time).total_seconds()
                    rate = sample_count / elapsed if elapsed > 0 else 0
                    print(f"   {elapsed:.0f}s | {sample_count} samples | {rate:.0f} Hz", end="\r")
            else:
                # Print non-data lines (status messages from the ESP32)
                print(line)

    except KeyboardInterrupt:
        pass  # Fall through to cleanup
    finally:
        # Stop annotation thread
        if ann_state and ann_state["active"]:
            ann_state["active"] = False
            try:
                ann_state["file"].close()
            except Exception:
                pass

        # Wrap all cleanup so a second Ctrl+C can't break it
        try:
            print("\n\nSending STOP command...")
            ser.write(b"STOP\n")
        except Exception:
            pass

        if csv_file:
            try:
                csv_file.close()
            except Exception:
                pass
            duration = (datetime.now() - start_time).total_seconds() if start_time else 0
            print(f"Saved recording: {filename} ({sample_count} samples, {duration:.1f}s)")

        try:
            ser.close()
        except Exception:
            pass
        print("Serial port closed.")


if __name__ == "__main__":
    main()
