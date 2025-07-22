#include <Arduino.h>

// Conditional compilation flag - change this to switch between modes
#define USE_TEMPERATURE_MODE 0  // Set to 1 for Temperature, 0 for HR_SpO2
    
#if USE_TEMPERATURE_MODE
  // Temperature Mode
  #include <Wire.h>
  #include <BLEDevice.h>
  #include <BLEServer.h>
  #include <BLEUtils.h>
  #include <BLE2902.h>
  #include "MAX30100.h"

  #define REPORTING_PERIOD_MS 500   // 2Hz reporting for consistency
  #define TEMP_SAMPLING_PERIOD_MS 1000

  MAX30100 sensor;
  uint32_t tsLastReport = 0;
  uint32_t tsLastTempSample = 0;
  bool tempSamplingStarted = false;

  BLEServer* bleServer;
  BLEService* bleService;
  BLECharacteristic* temperatureChar;

  static const BLEUUID tempServiceUUID("12345678-1234-5678-1234-56789abcdef0");
  static const BLEUUID tempCharUUID("abcdefab-1234-5678-1234-56789abcdef1");

  void setup_sensor() {
    Serial.print("Initializing MAX30100 sensor... ");
    if (!sensor.begin()) {
      Serial.println("FAILED");
      while (1);
    } else {
      Serial.println("SUCCESS");
    }
    sensor.setLedsCurrent(MAX30100_LED_CURR_24MA, MAX30100_LED_CURR_24MA);  // Set both IR and Red to 24mA
  }

  void setup_ble() {
    BLEDevice::init("ESP32_Temperature");
    bleServer = BLEDevice::createServer();
    bleService = bleServer->createService(tempServiceUUID);
    temperatureChar = bleService->createCharacteristic(
      tempCharUUID,
      BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    temperatureChar->addDescriptor(new BLE2902());
    bleService->start();

    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(tempServiceUUID);
    bleAdv->setScanResponse(true);
    bleAdv->setMinPreferred(0x06);
    bleAdv->setMinPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("BLE advertising started.");
  }

  void updateTemperature(float temperature) {
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"temperature\":%.3f}", temperature);
    temperatureChar->setValue((uint8_t*)buf, strlen(buf));
    temperatureChar->notify();
    Serial.printf("Temperature: %.3f°C\n", temperature);
  }

#else
  // HR_SpO2 Mode
  #include <Wire.h>
  #include <BLEDevice.h>
  #include <BLEServer.h>
  #include <BLEUtils.h>
  #include <BLE2902.h>
  #include "ADXL335.h"
  #include "MAX30100_PulseOximeter.h"

  #define REPORTING_PERIOD_MS 500

  PulseOximeter pox;
  ADXL335 accel;
  float ax = 0.0, ay = 0.0, az = 0.0;
  uint32_t tsLastReport = 0;

  BLEServer* bleServer;
  BLEService* bleService;
  BLECharacteristic* customSensorChar;

  static const BLEUUID customServiceUUID("12345678-1234-5678-1234-56789abcdef0");
  static const BLEUUID customCharUUID("abcdefab-1234-5678-1234-56789abcdef1");

  void setup_oximeter() {
    Serial.print("Initializing pulse oximeter... ");
    if (!pox.begin()) {
      Serial.println("FAILED");
      while (1);
    } else {
        Serial.println("SUCCESS");
    }
    pox.setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal HR/SpO2 signal strength
  }  void setup_accel() {
    accel.begin();
  }

  void setup_ble() {
    BLEDevice::init("ESP32_Sensor");
    bleServer = BLEDevice::createServer();
    bleService = bleServer->createService(customServiceUUID);
    customSensorChar = bleService->createCharacteristic(
      customCharUUID,
      BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    customSensorChar->addDescriptor(new BLE2902());
    bleService->start();

    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(customServiceUUID);
    bleAdv->setScanResponse(true);
    bleAdv->setMinPreferred(0x06);
    bleAdv->setMinPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("BLE advertising started.");
  }

  void update(float hrf, float spo2f, float ax, float ay, float az) {
    char buf[128];
    snprintf(buf, sizeof(buf),
      "{\"hr\":%.0f,\"spo2\":%.0f,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f}",
      hrf, spo2f, ax, ay, az
    );
    customSensorChar->setValue((uint8_t*)buf, strlen(buf));
    customSensorChar->notify();
    Serial.println(buf);
  }

#endif

void setup() {
  Serial.begin(115200);
  Wire.begin();
  
#if USE_TEMPERATURE_MODE
  Wire.setClock(400000);  // Use 400kHz I2C speed for better performance, consistent across all files
  setup_ble();
  setup_sensor();
  Serial.println("System ready - Temperature monitoring started");
#else
  Wire.setClock(400000);  // Use 400kHz I2C speed for better performance, consistent across all files
  setup_ble();
  setup_oximeter();
  setup_accel();
  Serial.println("System ready - HR/SpO2 monitoring started");
#endif
}

void loop() {
#if USE_TEMPERATURE_MODE
  // Temperature Mode Loop
  sensor.update();
  
  if (millis() - tsLastTempSample > TEMP_SAMPLING_PERIOD_MS) {
    if (!tempSamplingStarted) {
      sensor.startTemperatureSampling();
      tempSamplingStarted = true;
      tsLastTempSample = millis();
    }
  }
  
  if (tempSamplingStarted && sensor.isTemperatureReady()) {
    float temperature = sensor.retrieveTemperature();
    
    if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
      updateTemperature(temperature);
      tsLastReport = millis();
    }
    
    tempSamplingStarted = false;
  }
  
  delay(10);

#else
  // HR_SpO2 Mode Loop
  pox.update();

  if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
    float hr = pox.getHeartRate();
    float spo2 = pox.getSpO2();
    accel.getAcceleration(&ax, &ay, &az);

    Serial.printf("HR: %.1f | SpO2: %.1f | Accel: {%.2f, %.2f, %.2f}\n", hr, spo2, ax, ay, az);

    update(hr, spo2, ax, ay, az);
    tsLastReport = millis();
  }
#endif
}
