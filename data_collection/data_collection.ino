/*
 * IMU Barbell Tracker — Data Collection Sketch
 * ==============================================
 * Records IMU data to the SD card as timestamped CSV files.
 * Supports single-IMU (0x6A only) or dual-IMU (0x6A + 0x6B) mode.
 * Auto-detects how many IMUs are connected at startup.
 *
 * HOW TO USE:
 *   1. Upload this sketch
 *   2. Open Serial Monitor at 115200 to see status
 *   3. Press the BOOT button (GPIO0) to START recording
 *   4. Press it again to STOP recording
 *   5. Remove SD card and open the CSV file on your computer
 *
 * Each recording session creates a new file: /session_001.csv, /session_002.csv, etc.
 *
 * CSV COLUMNS (single IMU):
 *   timestamp_ms, a1x, a1y, a1z, g1x, g1y, g1z
 *
 * CSV COLUMNS (dual IMU):
 *   timestamp_ms, a1x, a1y, a1z, g1x, g1y, g1z, a2x, a2y, a2z, g2x, g2y, g2z
 *
 * Board:  Adafruit ESP32-S3 Feather (#5477)
 * Select: Tools -> Board -> "Adafruit Feather ESP32-S3"
 *
 * Libraries needed:
 *   - Adafruit LSM6DS
 *   - Adafruit Unified Sensor
 *   - RTClib
 */

#include <Wire.h>
#include <SPI.h>
#include <Adafruit_LSM6DSOX.h>
#include <RTClib.h>
#include <SD.h>

// ===================== CONFIGURATION =====================
// Change these to adjust behavior:

const int    SAMPLE_RATE_HZ  = 200;   // Samples per second (max ~416 for dual-IMU)
const int    SD_CS           = 5;     // Adalogger chip select pin
const int    BUTTON_PIN      = 0;     // BOOT button on ESP32-S3 (GPIO0)
const int    LED_PIN         = 13;    // Built-in LED for status

// Buffering: we batch writes to the SD card for efficiency.
// At 200Hz, each sample is ~80 bytes, so 50 samples = ~4KB per write.
const int    BUFFER_SAMPLES  = 50;

// ===================== GLOBALS =====================

Adafruit_LSM6DSOX imu1;
Adafruit_LSM6DSOX imu2;
RTC_PCF8523 rtc;

bool imu1OK = false;
bool imu2OK = false;
bool rtcOK  = false;
bool sdOK   = false;
bool dualMode = false;

bool recording = false;
bool buttonPressed = false;
unsigned long lastButtonTime = 0;

File dataFile;
int sessionNumber = 0;
unsigned long recordingStartMs = 0;
unsigned long sampleCount = 0;
unsigned long lastSampleUs = 0;
unsigned long sampleIntervalUs = 0;

// Write buffer
String writeBuffer = "";
int bufferCount = 0;

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0 < 3000)) delay(10);
  delay(500);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.println();
  Serial.println("========================================");
  Serial.println("  IMU Barbell Tracker - Data Collection");
  Serial.println("========================================");
  Serial.println();

  Wire.begin();
  Wire.setClock(400000);  // Fast I2C (400kHz) for higher throughput

  sampleIntervalUs = 1000000UL / SAMPLE_RATE_HZ;

  // ===== Initialize IMU #1 =====
  Serial.print("IMU #1 (0x6A): ");
  if (imu1.begin_I2C(0x6A)) {
    imu1OK = true;
    imu1.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
    imu1.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
    imu1.setAccelDataRate(LSM6DS_RATE_416_HZ);
    imu1.setGyroDataRate(LSM6DS_RATE_416_HZ);
    Serial.println("OK (16g, 2000dps, 416Hz)");
  } else {
    Serial.println("NOT FOUND");
  }

  // ===== Initialize IMU #2 =====
  Serial.print("IMU #2 (0x6B): ");
  if (imu2.begin_I2C(0x6B)) {
    imu2OK = true;
    imu2.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
    imu2.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
    imu2.setAccelDataRate(LSM6DS_RATE_416_HZ);
    imu2.setGyroDataRate(LSM6DS_RATE_416_HZ);
    Serial.println("OK (16g, 2000dps, 416Hz)");
  } else {
    Serial.println("NOT FOUND (single-IMU mode)");
  }

  dualMode = imu1OK && imu2OK;

  // ===== Initialize RTC =====
  Serial.print("RTC:           ");
  if (rtc.begin()) {
    rtcOK = true;
    if (!rtc.initialized() || rtc.lostPower()) {
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
      Serial.println("OK (set to compile time)");
    } else {
      DateTime now = rtc.now();
      Serial.printf("OK (%04d-%02d-%02d %02d:%02d:%02d)\n",
                    now.year(), now.month(), now.day(),
                    now.hour(), now.minute(), now.second());
    }
  } else {
    Serial.println("NOT FOUND (timestamps will use millis only)");
  }

  // ===== Initialize SD =====
  Serial.print("SD Card:       ");
  if (SD.begin(SD_CS)) {
    sdOK = true;
    Serial.println("OK");

    // Find next session number
    sessionNumber = 1;
    while (SD.exists(getFilename(sessionNumber))) {
      sessionNumber++;
    }
    Serial.printf("Next session file: %s\n", getFilename(sessionNumber).c_str());
  } else {
    Serial.println("NOT FOUND - CANNOT RECORD");
  }

  Serial.println();
  Serial.println("========================================");
  if (dualMode) {
    Serial.println("  MODE: Dual-IMU");
    Serial.printf("  RATE: %d Hz per sensor\n", SAMPLE_RATE_HZ);
    Serial.printf("  DATA: ~%.1f KB/sec\n", SAMPLE_RATE_HZ * 80.0 / 1024.0);
  } else if (imu1OK) {
    Serial.println("  MODE: Single-IMU");
    Serial.printf("  RATE: %d Hz\n", SAMPLE_RATE_HZ);
    Serial.printf("  DATA: ~%.1f KB/sec\n", SAMPLE_RATE_HZ * 48.0 / 1024.0);
  }
  Serial.println("========================================");
  Serial.println();

  if (imu1OK && sdOK) {
    Serial.println(">> Press BOOT button to START recording");
    Serial.println(">> Press again to STOP");
    Serial.println(">> LED = ON while recording\n");
  } else {
    Serial.println("ERROR: Cannot start - check IMU and SD card connections.");
  }
}

String getFilename(int num) {
  char buf[32];
  snprintf(buf, sizeof(buf), "/session_%03d.csv", num);
  return String(buf);
}

bool startRecording() {
  String filename = getFilename(sessionNumber);
  dataFile = SD.open(filename.c_str(), FILE_WRITE);
  if (!dataFile) {
    Serial.println("ERROR: Could not create file!");
    return false;
  }

  // Write CSV header
  if (dualMode) {
    dataFile.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z,a2x,a2y,a2z,g2x,g2y,g2z");
  } else {
    dataFile.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z");
  }

  // Write metadata as comment
  if (rtcOK) {
    DateTime now = rtc.now();
    dataFile.printf("# Started: %04d-%02d-%02d %02d:%02d:%02d\n",
                    now.year(), now.month(), now.day(),
                    now.hour(), now.minute(), now.second());
  }
  dataFile.printf("# Sample rate: %d Hz\n", SAMPLE_RATE_HZ);
  dataFile.printf("# Mode: %s\n", dualMode ? "dual-IMU" : "single-IMU");
  dataFile.printf("# Accel range: +/-16g\n");
  dataFile.printf("# Gyro range: +/-2000 dps\n");
  dataFile.printf("# Units: acceleration in m/s^2, gyro in rad/s\n");
  dataFile.flush();

  recordingStartMs = millis();
  sampleCount = 0;
  lastSampleUs = micros();
  writeBuffer = "";
  bufferCount = 0;

  recording = true;
  digitalWrite(LED_PIN, HIGH);

  Serial.printf("RECORDING to %s ...\n", filename.c_str());
  Serial.println("Press BOOT button to stop.\n");
  return true;
}

void stopRecording() {
  recording = false;
  digitalWrite(LED_PIN, LOW);

  // Flush remaining buffer
  if (bufferCount > 0) {
    dataFile.print(writeBuffer);
    writeBuffer = "";
    bufferCount = 0;
  }

  unsigned long duration = millis() - recordingStartMs;
  float actualRate = (float)sampleCount / (duration / 1000.0);

  dataFile.printf("# Ended after %.1f seconds\n", duration / 1000.0);
  dataFile.printf("# Total samples: %lu\n", sampleCount);
  dataFile.printf("# Actual sample rate: %.1f Hz\n", actualRate);
  dataFile.close();

  Serial.println();
  Serial.println("========================================");
  Serial.println("  RECORDING STOPPED");
  Serial.println("========================================");
  Serial.printf("  File:       %s\n", getFilename(sessionNumber).c_str());
  Serial.printf("  Duration:   %.1f seconds\n", duration / 1000.0);
  Serial.printf("  Samples:    %lu\n", sampleCount);
  Serial.printf("  Avg rate:   %.1f Hz\n", actualRate);
  Serial.println("========================================\n");

  sessionNumber++;
  Serial.println(">> Press BOOT button to start new recording");
}

void checkButton() {
  bool pressed = (digitalRead(BUTTON_PIN) == LOW);

  if (pressed && !buttonPressed && (millis() - lastButtonTime > 300)) {
    buttonPressed = true;
    lastButtonTime = millis();

    if (!recording) {
      startRecording();
    } else {
      stopRecording();
    }
  }

  if (!pressed) {
    buttonPressed = false;
  }
}

void collectSample() {
  unsigned long now = millis();
  unsigned long ts = now - recordingStartMs;

  sensors_event_t a1, g1, t1;
  imu1.getEvent(&a1, &g1, &t1);

  char line[200];

  if (dualMode) {
    sensors_event_t a2, g2, t2;
    imu2.getEvent(&a2, &g2, &t2);

    snprintf(line, sizeof(line),
      "%lu,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f\n",
      ts,
      a1.acceleration.x, a1.acceleration.y, a1.acceleration.z,
      g1.gyro.x, g1.gyro.y, g1.gyro.z,
      a2.acceleration.x, a2.acceleration.y, a2.acceleration.z,
      g2.gyro.x, g2.gyro.y, g2.gyro.z);
  } else {
    snprintf(line, sizeof(line),
      "%lu,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f\n",
      ts,
      a1.acceleration.x, a1.acceleration.y, a1.acceleration.z,
      g1.gyro.x, g1.gyro.y, g1.gyro.z);
  }

  writeBuffer += line;
  bufferCount++;
  sampleCount++;

  // Flush buffer to SD card periodically
  if (bufferCount >= BUFFER_SAMPLES) {
    dataFile.print(writeBuffer);
    dataFile.flush();
    writeBuffer = "";
    bufferCount = 0;
  }

  // Print progress every 5 seconds
  if (sampleCount % (SAMPLE_RATE_HZ * 5) == 0) {
    float elapsed = (millis() - recordingStartMs) / 1000.0;
    float rate = sampleCount / elapsed;
    Serial.printf("  Recording... %.0fs | %lu samples | %.0f Hz avg\n",
                  elapsed, sampleCount, rate);
  }
}

void loop() {
  checkButton();

  if (recording && imu1OK) {
    unsigned long nowUs = micros();
    if (nowUs - lastSampleUs >= sampleIntervalUs) {
      lastSampleUs = nowUs;
      collectSample();
    }
  }
}
