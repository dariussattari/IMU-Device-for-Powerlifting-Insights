/*
 * IMU Barbell Tracker — Hardware Verification + I2C Bus Scan
 * ===========================================================
 * This sketch does TWO important things:
 *   1. Scans the entire I2C bus to show you EXACTLY which devices
 *      are connected and at which addresses
 *   2. Tests all components: both IMUs, RTC, SD card
 *
 * IMPORTANT: Run this FIRST before any data collection.
 * Open Serial Monitor at 115200 baud to see results.
 *
 * Board:  Adafruit ESP32-S3 Feather (#5477)
 * Select: Tools -> Board -> "Adafruit Feather ESP32-S3"
 *
 * Required Libraries (Sketch -> Include Library -> Manage Libraries):
 *   - "Adafruit LSM6DS" by Adafruit
 *   - "Adafruit Unified Sensor" by Adafruit
 *   - "RTClib" by Adafruit
 */

#include <Wire.h>
#include <SPI.h>
#include <Adafruit_LSM6DSOX.h>
#include <RTClib.h>
#include <SD.h>

const int SD_CS = 10;

// ESP32-S3 Feather SPI pins (must be set explicitly)
const int SPI_SCK  = 36;
const int SPI_MOSI = 35;
const int SPI_MISO = 37;

Adafruit_LSM6DSOX imu1;
Adafruit_LSM6DSOX imu2;
RTC_PCF8523 rtc;

bool imu1OK = false;
bool imu2OK = false;
bool rtcOK = false;
bool sdOK = false;

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0 < 3000)) delay(10);
  delay(500);

  Serial.println();
  Serial.println("========================================");
  Serial.println("  IMU Barbell Tracker - Hardware Test");
  Serial.println("  (with I2C Bus Scanner)");
  Serial.println("========================================");
  Serial.println();

  Wire.begin();
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SD_CS);

  // ===== I2C BUS SCAN =====
  // This tells you exactly what's connected
  Serial.println("--- I2C Bus Scan ---");
  Serial.println("Scanning all addresses (0x01 to 0x7F)...");
  Serial.println();
  int deviceCount = 0;

  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte error = Wire.endTransmission();

    if (error == 0) {
      deviceCount++;
      Serial.print("  FOUND device at address 0x");
      if (addr < 16) Serial.print("0");
      Serial.print(addr, HEX);

      // Identify known devices
      if (addr == 0x6A) Serial.println("  <-- LSM6DSOX IMU (default address)");
      else if (addr == 0x6B) Serial.println("  <-- LSM6DSOX IMU (alternate address)");
      else if (addr == 0x68) Serial.println("  <-- PCF8523 RTC (Adalogger)");
      else if (addr == 0x36) Serial.println("  <-- MAX17048 Battery Gauge");
      else Serial.println("  <-- Unknown device");
    }
  }

  Serial.println();
  Serial.print("Total devices found: ");
  Serial.println(deviceCount);
  Serial.println();

  // ===== ANALYZE WHAT WE FOUND =====
  // Check if we see both IMU addresses
  Wire.beginTransmission(0x6A);
  bool has6A = (Wire.endTransmission() == 0);
  Wire.beginTransmission(0x6B);
  bool has6B = (Wire.endTransmission() == 0);

  if (has6A && has6B) {
    Serial.println("GREAT: Both IMU addresses detected (0x6A and 0x6B).");
    Serial.println("       Both IMUs are ready for dual-sensor operation.");
  } else if (has6A && !has6B) {
    Serial.println("NOTE: Only ONE IMU detected at 0x6A (default address).");
    Serial.println("      This could mean:");
    Serial.println("      - Both IMUs have the same address (only one responds)");
    Serial.println("      - Second IMU is not connected");
    Serial.println("      To fix: cut SDO/SA0 jumper on IMU #2 to get 0x6B");
  } else if (!has6A && has6B) {
    Serial.println("NOTE: Only one IMU detected, at 0x6B (alternate).");
    Serial.println("      The default address (0x6A) IMU may not be connected.");
  } else {
    Serial.println("WARNING: No IMU detected at either address!");
    Serial.println("         Check STEMMA QT cable connections.");
  }
  Serial.println();

  // ===== TEST IMU #1 (0x6A) =====
  Serial.println("--- Test: IMU #1 (address 0x6A) ---");
  if (imu1.begin_I2C(0x6A)) {
    imu1OK = true;
    imu1.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
    imu1.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
    imu1.setAccelDataRate(LSM6DS_RATE_416_HZ);
    imu1.setGyroDataRate(LSM6DS_RATE_416_HZ);
    Serial.println("  [PASS] IMU #1 initialized");
    Serial.println("  Config: +/-16g, +/-2000dps, 416Hz");

    sensors_event_t a, g, t;
    imu1.getEvent(&a, &g, &t);
    float grav = sqrt(a.acceleration.x*a.acceleration.x +
                      a.acceleration.y*a.acceleration.y +
                      a.acceleration.z*a.acceleration.z);
    Serial.printf("  Accel: [%+.2f, %+.2f, %+.2f] m/s^2\n",
                  a.acceleration.x, a.acceleration.y, a.acceleration.z);
    Serial.printf("  Gyro:  [%+.2f, %+.2f, %+.2f] rad/s\n",
                  g.gyro.x, g.gyro.y, g.gyro.z);
    Serial.printf("  Gravity magnitude: %.2f m/s^2 %s\n",
                  grav, (grav > 8.0 && grav < 12.0) ? "(OK)" : "(WARNING)");
  } else {
    Serial.println("  [FAIL] IMU #1 not found at 0x6A");
  }
  Serial.println();

  // ===== TEST IMU #2 (0x6B) =====
  Serial.println("--- Test: IMU #2 (address 0x6B) ---");
  if (imu2.begin_I2C(0x6B)) {
    imu2OK = true;
    imu2.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
    imu2.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
    imu2.setAccelDataRate(LSM6DS_RATE_416_HZ);
    imu2.setGyroDataRate(LSM6DS_RATE_416_HZ);
    Serial.println("  [PASS] IMU #2 initialized");
    Serial.println("  Config: +/-16g, +/-2000dps, 416Hz");

    sensors_event_t a, g, t;
    imu2.getEvent(&a, &g, &t);
    float grav = sqrt(a.acceleration.x*a.acceleration.x +
                      a.acceleration.y*a.acceleration.y +
                      a.acceleration.z*a.acceleration.z);
    Serial.printf("  Accel: [%+.2f, %+.2f, %+.2f] m/s^2\n",
                  a.acceleration.x, a.acceleration.y, a.acceleration.z);
    Serial.printf("  Gyro:  [%+.2f, %+.2f, %+.2f] rad/s\n",
                  g.gyro.x, g.gyro.y, g.gyro.z);
    Serial.printf("  Gravity magnitude: %.2f m/s^2 %s\n",
                  grav, (grav > 8.0 && grav < 12.0) ? "(OK)" : "(WARNING)");
  } else {
    Serial.println("  [FAIL] IMU #2 not found at 0x6B");
    Serial.println("  This is expected if you haven't cut the SDO jumper yet.");
    Serial.println("  Single-IMU mode still works fine for initial testing.");
  }
  Serial.println();

  // ===== TEST RTC =====
  Serial.println("--- Test: PCF8523 RTC ---");
  if (rtc.begin()) {
    rtcOK = true;
    if (!rtc.initialized() || rtc.lostPower()) {
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
      Serial.println("  [PASS] RTC found (set to compile time)");
    } else {
      Serial.println("  [PASS] RTC found");
    }
    DateTime now = rtc.now();
    Serial.printf("  Time: %04d-%02d-%02d %02d:%02d:%02d\n",
                  now.year(), now.month(), now.day(),
                  now.hour(), now.minute(), now.second());
  } else {
    Serial.println("  [FAIL] RTC not found");
  }
  Serial.println();

  // ===== TEST SD =====
  Serial.println("--- Test: MicroSD Card ---");
  if (SD.begin(SD_CS)) {
    sdOK = true;
    Serial.println("  [PASS] MicroSD detected");
    File f = SD.open("/hw_test.csv", FILE_WRITE);
    if (f) {
      f.println("test,ok");
      f.close();
      Serial.println("  Write test: OK");
    }
  } else {
    Serial.println("  [FAIL] MicroSD not detected");
    Serial.println("  Check: card inserted? Formatted as FAT32?");
  }
  Serial.println();

  // ===== SUMMARY =====
  Serial.println("========================================");
  Serial.println("  RESULTS SUMMARY");
  Serial.println("========================================");
  Serial.printf("  IMU #1 (0x6A): %s\n", imu1OK ? "PASS" : "FAIL");
  Serial.printf("  IMU #2 (0x6B): %s\n", imu2OK ? "PASS" : "FAIL (see note above)");
  Serial.printf("  RTC:           %s\n", rtcOK  ? "PASS" : "FAIL");
  Serial.printf("  SD Card:       %s\n", sdOK   ? "PASS" : "FAIL");
  Serial.println("========================================");

  if (imu1OK && imu2OK) {
    Serial.println("\nBoth IMUs working! Dual-sensor mode ready.");
  } else if (imu1OK) {
    Serial.println("\nOne IMU working. You can still collect data in single-IMU mode.");
    Serial.println("For dual-IMU: cut SDO jumper on IMU #2 or check daisy-chain cable.");
  }

  if (imu1OK || imu2OK) {
    Serial.println("\n--- Live stream (10 seconds) ---");
    Serial.println("Tilt/shake the device to verify readings change.\n");
  }
}

unsigned long streamStart = 0;
bool done = false;

void loop() {
  if (done || (!imu1OK && !imu2OK)) { delay(1000); return; }
  if (streamStart == 0) streamStart = millis();

  unsigned long elapsed = millis() - streamStart;
  if (elapsed > 10000) {
    done = true;
    Serial.println("\n--- Stream complete ---");
    Serial.println("Hardware test done. Upload data_collection.ino to start recording.");
    return;
  }

  if (imu1OK) {
    sensors_event_t a, g, t;
    imu1.getEvent(&a, &g, &t);
    Serial.printf("IMU1: A[%+7.2f %+7.2f %+7.2f] G[%+7.1f %+7.1f %+7.1f]",
                  a.acceleration.x, a.acceleration.y, a.acceleration.z,
                  g.gyro.x, g.gyro.y, g.gyro.z);
  }
  if (imu2OK) {
    sensors_event_t a, g, t;
    imu2.getEvent(&a, &g, &t);
    Serial.printf("  IMU2: A[%+7.2f %+7.2f %+7.2f] G[%+7.1f %+7.1f %+7.1f]",
                  a.acceleration.x, a.acceleration.y, a.acceleration.z,
                  g.gyro.x, g.gyro.y, g.gyro.z);
  }
  Serial.printf("  %lums\n", elapsed);
  delay(100);
}
