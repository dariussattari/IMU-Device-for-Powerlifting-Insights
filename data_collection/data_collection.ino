/*
 * IMU Barbell Tracker — Data Collection (USB Serial Mode)
 * ========================================================
 * Streams IMU data over USB serial as CSV lines.
 * A Python script on your laptop captures the stream to a .csv file.
 *
 * Also writes to SD card if available (dual output).
 *
 * Supports single-IMU (0x6A only) or dual-IMU (0x6A + 0x6B) mode.
 * Auto-detects how many IMUs are connected at startup.
 *
 * HOW TO USE:
 *   1. Upload this sketch
 *   2. Run the Python capture script: python3 capture_serial.py
 *   3. Recording starts/stops automatically via serial commands
 *      (or press the BOOT button if you prefer manual control)
 *   4. The CSV file will be saved on your laptop
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
 *   - RTClib (optional, for RTC timestamps)
 */

#include <Wire.h>
#include <SPI.h>
#include <Adafruit_LSM6DSOX.h>
#include <RTClib.h>
#include <SD.h>

// ===================== CONFIGURATION =====================

const int    SAMPLE_RATE_HZ  = 200;   // Samples per second
const int    SD_CS           = 10;    // Adalogger chip select pin
const int    BUTTON_PIN      = 0;     // BOOT button on ESP32-S3 (GPIO0)
const int    LED_PIN         = 13;    // Built-in LED for status

// ESP32-S3 Feather SPI pins (must be set explicitly)
const int    SPI_SCK         = 36;
const int    SPI_MOSI        = 35;
const int    SPI_MISO        = 37;

// Buffer size for SD card writes (if SD available)
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

// Write buffer (for SD card only)
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
  Serial.println("  (USB Serial + optional SD)");
  Serial.println("========================================");
  Serial.println();

  Wire.begin();
  Wire.setClock(400000);
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SD_CS);

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

  // ===== Initialize RTC (optional) =====
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

  // ===== Initialize SD (optional) =====
  Serial.print("SD Card:       ");
  if (SD.begin(SD_CS)) {
    sdOK = true;
    Serial.println("OK (will save to SD too)");
    sessionNumber = 1;
    while (SD.exists(getFilename(sessionNumber))) {
      sessionNumber++;
    }
    Serial.printf("Next session file: %s\n", getFilename(sessionNumber).c_str());
  } else {
    Serial.println("NOT FOUND (USB serial only - this is fine)");
  }

  Serial.println();
  Serial.println("========================================");
  if (dualMode) {
    Serial.println("  MODE: Dual-IMU");
  } else if (imu1OK) {
    Serial.println("  MODE: Single-IMU");
  }
  Serial.printf("  RATE: %d Hz\n", SAMPLE_RATE_HZ);
  Serial.printf("  OUTPUT: USB Serial%s\n", sdOK ? " + SD Card" : "");
  Serial.println("========================================");
  Serial.println();

  if (imu1OK) {
    Serial.println(">> Send 'START' over serial to begin recording");
    Serial.println(">> Send 'STOP' to end recording");
    Serial.println(">> (BOOT button also works if accessible)");
    Serial.println(">> LED = ON while recording");
    Serial.println(">> Run: python3 capture_serial.py\n");
    Serial.println("READY");
  } else {
    Serial.println("ERROR: No IMU found - check connections.");
  }
}

String getFilename(int num) {
  char buf[32];
  snprintf(buf, sizeof(buf), "/session_%03d.csv", num);
  return String(buf);
}

bool startRecording() {
  // Open SD file if available
  if (sdOK) {
    String filename = getFilename(sessionNumber);
    dataFile = SD.open(filename.c_str(), FILE_WRITE);
    if (dataFile) {
      if (dualMode) {
        dataFile.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z,a2x,a2y,a2z,g2x,g2y,g2z");
      } else {
        dataFile.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z");
      }
      dataFile.printf("# Sample rate: %d Hz\n", SAMPLE_RATE_HZ);
      dataFile.flush();
    }
  }

  recordingStartMs = millis();
  sampleCount = 0;
  lastSampleUs = micros();
  writeBuffer = "";
  bufferCount = 0;

  recording = true;
  digitalWrite(LED_PIN, HIGH);

  // Send start marker that the Python script will detect
  Serial.println("---DATA_START---");
  if (dualMode) {
    Serial.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z,a2x,a2y,a2z,g2x,g2y,g2z");
  } else {
    Serial.println("timestamp_ms,a1x,a1y,a1z,g1x,g1y,g1z");
  }

  return true;
}

void stopRecording() {
  recording = false;
  digitalWrite(LED_PIN, LOW);

  // Send stop marker
  Serial.println("---DATA_STOP---");

  unsigned long duration = millis() - recordingStartMs;
  float actualRate = (float)sampleCount / (duration / 1000.0);

  // Close SD file if open
  if (sdOK && dataFile) {
    if (bufferCount > 0) {
      dataFile.print(writeBuffer);
      writeBuffer = "";
      bufferCount = 0;
    }
    dataFile.printf("# Total samples: %lu\n", sampleCount);
    dataFile.printf("# Actual sample rate: %.1f Hz\n", actualRate);
    dataFile.close();
  }

  Serial.println();
  Serial.println("========================================");
  Serial.println("  RECORDING STOPPED");
  Serial.println("========================================");
  Serial.printf("  Duration:   %.1f seconds\n", duration / 1000.0);
  Serial.printf("  Samples:    %lu\n", sampleCount);
  Serial.printf("  Avg rate:   %.1f Hz\n", actualRate);
  if (sdOK) {
    Serial.printf("  SD file:    %s\n", getFilename(sessionNumber).c_str());
  }
  Serial.println("========================================\n");

  if (sdOK) sessionNumber++;
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

void checkSerialCommand() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "START" && !recording) {
      startRecording();
    } else if (cmd == "STOP" && recording) {
      stopRecording();
    } else if (cmd == "PING") {
      Serial.println("PONG");
    }
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
      "%lu,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f",
      ts,
      a1.acceleration.x, a1.acceleration.y, a1.acceleration.z,
      g1.gyro.x, g1.gyro.y, g1.gyro.z,
      a2.acceleration.x, a2.acceleration.y, a2.acceleration.z,
      g2.gyro.x, g2.gyro.y, g2.gyro.z);
  } else {
    snprintf(line, sizeof(line),
      "%lu,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f",
      ts,
      a1.acceleration.x, a1.acceleration.y, a1.acceleration.z,
      g1.gyro.x, g1.gyro.y, g1.gyro.z);
  }

  // Always stream over USB serial
  Serial.println(line);

  // Also write to SD if available
  if (sdOK && dataFile) {
    writeBuffer += line;
    writeBuffer += "\n";
    bufferCount++;
    if (bufferCount >= BUFFER_SAMPLES) {
      dataFile.print(writeBuffer);
      dataFile.flush();
      writeBuffer = "";
      bufferCount = 0;
    }
  }

  sampleCount++;
}

void loop() {
  checkButton();
  checkSerialCommand();

  if (recording && imu1OK) {
    unsigned long nowUs = micros();
    if (nowUs - lastSampleUs >= sampleIntervalUs) {
      lastSampleUs = nowUs;
      collectSample();
    }
  }
}
