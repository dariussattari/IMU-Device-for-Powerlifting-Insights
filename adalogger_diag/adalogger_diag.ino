/*
 * Adalogger Diagnostic — Brute Force Pin Scanner
 * ================================================
 * Tries every possible CS pin and SPI configuration
 * to find the SD card. Also checks power delivery
 * to the Adalogger by testing GPIO states.
 *
 * Upload this, open Serial Monitor at 115200.
 * Make sure a MicroSD card is inserted in the Adalogger.
 */

#include <Wire.h>
#include <SPI.h>
#include <SD.h>

// All usable GPIO pins on ESP32-S3 Feather headers
const int ALL_PINS[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 35, 36, 37, 38};
const int NUM_PINS = 23;

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0 < 3000)) delay(10);
  delay(500);

  Serial.println();
  Serial.println("========================================");
  Serial.println("  Adalogger Diagnostic - Pin Scanner");
  Serial.println("========================================");
  Serial.println();

  // ===== STEP 1: I2C Scan =====
  Serial.println("--- Step 1: I2C Bus Scan ---");
  Serial.println("Looking for RTC at 0x68...");
  Wire.begin();

  int deviceCount = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte error = Wire.endTransmission();
    if (error == 0) {
      deviceCount++;
      Serial.print("  FOUND: 0x");
      if (addr < 16) Serial.print("0");
      Serial.print(addr, HEX);
      if (addr == 0x68) Serial.print("  <-- RTC (Adalogger is connected!)");
      else if (addr == 0x6A) Serial.print("  <-- IMU #1");
      else if (addr == 0x6B) Serial.print("  <-- IMU #2");
      else if (addr == 0x36) Serial.print("  <-- Battery Gauge");
      Serial.println();
    }
  }
  Serial.printf("Total I2C devices: %d\n", deviceCount);

  bool rtcFound = false;
  Wire.beginTransmission(0x68);
  if (Wire.endTransmission() == 0) {
    rtcFound = true;
    Serial.println("\nRTC FOUND! Adalogger I2C connection is GOOD.");
  } else {
    Serial.println("\nRTC NOT found at 0x68.");
    Serial.println("This means SDA/SCL are NOT reaching the Adalogger,");
    Serial.println("OR the Adalogger is not receiving power (3V/GND).");
  }
  Serial.println();

  // ===== STEP 2: Check if SD card responds on expected pins =====
  Serial.println("--- Step 2: SD Card on expected pins ---");
  Serial.println("Trying SCK=36, MISO=37, MOSI=35, CS=10...");

  SPI.end();
  SPI.begin(36, 37, 35, 10);
  if (SD.begin(10)) {
    Serial.println("  SD CARD FOUND on expected pins!");
    SD.end();
  } else {
    Serial.println("  Failed on expected pins.");
    SD.end();
    SPI.end();

    // ===== STEP 3: Try default SPI without explicit pins =====
    Serial.println();
    Serial.println("--- Step 3: SD Card with default SPI pins ---");
    SPI.begin();
    Serial.printf("  Default SPI: SCK=%d, MISO=%d, MOSI=%d\n", SCK, MISO, MOSI);
    if (SD.begin(10)) {
      Serial.println("  SD CARD FOUND with default SPI + CS=10!");
      SD.end();
    } else {
      Serial.println("  Failed with default SPI.");
      SD.end();
      SPI.end();

      // ===== STEP 4: Brute force CS pin =====
      Serial.println();
      Serial.println("--- Step 4: Trying every possible CS pin ---");
      Serial.println("(Using explicit SPI: SCK=36, MISO=37, MOSI=35)");
      Serial.println();

      bool found = false;
      for (int i = 0; i < NUM_PINS; i++) {
        int cs = ALL_PINS[i];
        SPI.begin(36, 37, 35, cs);
        if (SD.begin(cs)) {
          Serial.printf("  >>> SD CARD FOUND on CS pin %d! <<<\n", cs);
          found = true;
          SD.end();
          SPI.end();
          break;
        }
        SD.end();
        SPI.end();
        Serial.printf("  CS=%d: no\n", cs);
      }

      if (!found) {
        Serial.println();
        Serial.println("  SD card not found on ANY pin.");
        Serial.println();

        // ===== STEP 5: Try with default SPI + all CS pins =====
        Serial.println("--- Step 5: Default SPI + every CS pin ---");
        for (int i = 0; i < NUM_PINS; i++) {
          int cs = ALL_PINS[i];
          SPI.begin();
          if (SD.begin(cs)) {
            Serial.printf("  >>> SD CARD FOUND: default SPI + CS=%d! <<<\n", cs);
            found = true;
            SD.end();
            SPI.end();
            break;
          }
          SD.end();
          SPI.end();
          Serial.printf("  CS=%d: no\n", cs);
        }

        if (!found) {
          Serial.println();
          Serial.println("========================================");
          Serial.println("  DIAGNOSIS");
          Serial.println("========================================");
          if (!rtcFound) {
            Serial.println("  Neither RTC nor SD card detected.");
            Serial.println("  The Adalogger is NOT receiving signals");
            Serial.println("  from the Feather. Possible causes:");
            Serial.println("  1. Header pin solder joints on the");
            Serial.println("     Adalogger are not bonded to traces");
            Serial.println("     (cold solder joints)");
            Serial.println("  2. Adalogger is oriented backwards");
            Serial.println("     (flipped 180 degrees)");
            Serial.println("  3. 3V/GND not reaching Adalogger");
            Serial.println();
            Serial.println("  TEST: With board powered, measure");
            Serial.println("  voltage between Adalogger 3V and GND");
            Serial.println("  header pins. Should read 3.3V.");
          } else {
            Serial.println("  RTC works but SD card does not.");
            Serial.println("  I2C is OK but SPI connections are wrong.");
            Serial.println("  Check SCK, MO, MI, and pin 10 wires.");
          }
          Serial.println("========================================");
        }
      }
    }
  }

  Serial.println();
  Serial.println("Diagnostic complete.");
}

void loop() {
  delay(1000);
}
