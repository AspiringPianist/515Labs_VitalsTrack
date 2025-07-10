// Distance testing version of MAX30100 BLE code
#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30100.h"

#define REPORTING_PERIOD_MS 100
#define SAMPLES_PER_BATCH 10

MAX30100 sensor;
uint32_t tsLastReport = 0;

// BLE variables
BLEServer* bleServer;
BLEService* bleService;
BLECharacteristic* rawDataChar;
BLECharacteristic* controlChar;

// UUIDs for quantum efficiency testing
static const BLEUUID qeServiceUUID("12345678-1234-5678-1234-56789abcdef0");
static const BLEUUID rawDataCharUUID("abcdefab-1234-5678-1234-56789abcdef1");
static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");

// Data collection variables
uint32_t irSum = 0;
uint32_t redSum = 0;
uint16_t sampleCount = 0;
bool collectingData = false;
String currentLED = "none";
int currentDistance = 0; // NEW

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* pCharacteristic) {
        String value = pCharacteristic->getValue().c_str();
        
        if (value.startsWith("START:")) {
            int colonIndex = value.indexOf(':', 6);
            if (colonIndex > 0) {
                currentLED = value.substring(6, colonIndex);
                currentDistance = value.substring(colonIndex + 1).toInt();
            } else {
                currentLED = value.substring(6);
                currentDistance = 0;
            }
            collectingData = true;
            sampleCount = 0;
            irSum = 0;
            redSum = 0;
            Serial.println("Started collecting for " + currentLED + " at " + String(currentDistance) + "mm");
        } else if (value == "STOP") {
            collectingData = false;
            Serial.println("Stopped data collection");
        } else if (value == "RESET") {
            sensor.resetFifo();
            Serial.println("FIFO reset");
        }
    }
};

void setup_sensor() {
    Serial.print("Initializing MAX30100 sensor... ");
    if (!sensor.begin()) {
        Serial.println("FAILED");
        while (1);
    } else {
        Serial.println("SUCCESS");
    }
    sensor.setMode(MAX30100_MODE_SPO2_HR);
    sensor.setLedsCurrent(MAX30100_LED_CURR_50MA, MAX30100_LED_CURR_50MA);
    sensor.setHighresModeEnabled(true);
    Serial.println("Sensor configured for distance testing");
}

void setup_ble() {
    BLEDevice::init("ESP32_Distance_Test");
    bleServer = BLEDevice::createServer();
    bleService = bleServer->createService(qeServiceUUID);

    rawDataChar = bleService->createCharacteristic(
        rawDataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    rawDataChar->addDescriptor(new BLE2902());

    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE
    );
    controlChar->setCallbacks(new ControlCallbacks());

    bleService->start();

    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(qeServiceUUID);
    bleAdv->setScanResponse(true);
    BLEDevice::startAdvertising();
    Serial.println("BLE advertising started");
}

void sendRawData(uint16_t ir, uint16_t red) {
    char buf[160];
    snprintf(buf, sizeof(buf),
        "{\"ir\":%u,\"red\":%u,\"led\":\"%s\",\"samples\":%u,\"distance_mm\":%d,\"collecting\":%s}",
        ir, red, currentLED.c_str(), sampleCount, currentDistance, collectingData ? "true" : "false"
    );
    rawDataChar->setValue((uint8_t*)buf, strlen(buf));
    rawDataChar->notify();
}

void sendAverageData() {
    if (sampleCount > 0) {
        float avgIR = (float)irSum / sampleCount;
        float avgRed = (float)redSum / sampleCount;
        char buf[160];
        snprintf(buf, sizeof(buf),
            "{\"type\":\"average\",\"led\":\"%s\",\"distance_mm\":%d,\"avg_ir\":%.2f,\"avg_red\":%.2f,\"samples\":%u}",
            currentLED.c_str(), currentDistance, avgIR, avgRed, sampleCount
        );
        rawDataChar->setValue((uint8_t*)buf, strlen(buf));
        rawDataChar->notify();
        Serial.printf("Average (%s @ %dmm): IR=%.2f, Red=%.2f (samples=%u)\n", currentLED.c_str(), currentDistance, avgIR, avgRed, sampleCount);
    }
}

void setup() {
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);
    setup_ble();
    setup_sensor();
    Serial.println("=== Distance Test Mode ===");
}

void loop() {
    sensor.update();
    uint16_t ir, red;
    if (sensor.getRawValues(&ir, &red)) {
        if (collectingData) {
            irSum += ir;
            redSum += red;
            sampleCount++;
            if (sampleCount % SAMPLES_PER_BATCH == 0) {
                sendAverageData();
            }
        }
        if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
            sendRawData(ir, red);
            tsLastReport = millis();
        }
    }
    delay(10);
}
