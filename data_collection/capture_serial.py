#!/usr/bin/env python3
"""
IMU Barbell Tracker — Serial Data Capture
==========================================
Captures CSV data streamed from the ESP32-S3 over USB serial
and saves it to timestamped .csv files.

Usage:
    python3 capture_serial.py

    Optional arguments:
    python3 capture_serial.py --port /dev/cu.usbmodem3101 --baud 115200 --output ./data

The script auto-detects the serial port on macOS. Press Ctrl+C to quit.
"""

import serial
import serial.tools.list_ports
import argparse
import os
import sys
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


def main():
    parser = argparse.ArgumentParser(description="Capture IMU data from ESP32-S3 over USB serial")
    parser.add_argument("--port", type=str, default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--output", type=str, default=".", help="Output directory for CSV files (default: current dir)")
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
                continue

            # Detect end of data stream
            if line == "---DATA_STOP---":
                if csv_file:
                    csv_file.close()
                    csv_file = None
                duration = (datetime.now() - start_time).total_seconds() if start_time else 0
                print(f"\n>> STOPPED — {sample_count} samples in {duration:.1f}s")
                if sample_count > 0 and duration > 0:
                    print(f"   Avg rate: {sample_count/duration:.1f} Hz")
                print(f"   Saved to: {filename}")
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
