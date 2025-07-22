#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30100.h"

#define REPORTING_PERIOD_MS 500   // 2Hz reporting for consistency across all files
#define TEMP_SAMPLING_PERIOD_MS 1000  // Start temperature sampling every 1 second

MAX30100 sensor;

uint32_t tsLastReport = 0;
uint32_t tsLastTempSample = 0;
bool tempSamplingStarted = false;

BLEServer* bleServer;
BLEService* bleService;
BLECharacteristic* temperatureChar;

// Custom BLE UUIDs for temperature service
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
  
  // Configure sensor with same settings as original code
  // IR LED current as specified in original code, Red LED current as default
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

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);  // Use faster I2C speed as defined in MAX30100.h

  setup_ble();
  setup_sensor();
  
  Serial.println("System ready - Temperature monitoring started");
}

void loop() {
  sensor.update();  // Keep sensor updated
  
  // Start temperature sampling periodically
  if (millis() - tsLastTempSample > TEMP_SAMPLING_PERIOD_MS) {
    if (!tempSamplingStarted) {
      sensor.startTemperatureSampling();
      tempSamplingStarted = true;
      tsLastTempSample = millis();
    }
  }
  
  // Check if temperature is ready and report it
  if (tempSamplingStarted && sensor.isTemperatureReady()) {
    float temperature = sensor.retrieveTemperature();
    
    if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
      updateTemperature(temperature);
      tsLastReport = millis();
    }
    
    tempSamplingStarted = false;  // Reset flag for next sampling cycle
  }
  
  delay(10);  // Small delay to prevent excessive polling
}