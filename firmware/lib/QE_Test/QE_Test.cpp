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

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* pCharacteristic) {
        String value = pCharacteristic->getValue().c_str();
        
        if (value.startsWith("START:")) {
            currentLED = value.substring(6);
            collectingData = true;
            sampleCount = 0;
            irSum = 0;
            redSum = 0;
            Serial.println("Started collecting data for LED: " + currentLED);
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
    
    // Configure sensor for raw data collection
    sensor.setMode(MAX30100_MODE_SPO2_HR);
    sensor.setLedsCurrent(MAX30100_LED_CURR_50MA, MAX30100_LED_CURR_50MA);
    sensor.setHighresModeEnabled(true);
    
    Serial.println("Sensor configured for quantum efficiency testing");
}

void setup_ble() {
    BLEDevice::init("ESP32_QE_Test");
    bleServer = BLEDevice::createServer();
    bleService = bleServer->createService(qeServiceUUID);
    
    // Raw data characteristic (for sending measurements)
    rawDataChar = bleService->createCharacteristic(
        rawDataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    rawDataChar->addDescriptor(new BLE2902());
    
    // Control characteristic (for receiving commands)
    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE
    );
    controlChar->setCallbacks(new ControlCallbacks());
    
    bleService->start();
    
    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(qeServiceUUID);
    bleAdv->setScanResponse(true);
    bleAdv->setMinPreferred(0x06);
    bleAdv->setMinPreferred(0x12);
    BLEDevice::startAdvertising();
    
    Serial.println("BLE advertising started - Ready for quantum efficiency testing");
}

void sendRawData(uint16_t ir, uint16_t red) {
    char buf[128];
    snprintf(buf, sizeof(buf),
        "{\"ir\":%u,\"red\":%u,\"led\":\"%s\",\"samples\":%u,\"collecting\":%s}",
        ir, red, currentLED.c_str(), sampleCount, collectingData ? "true" : "false"
    );
    rawDataChar->setValue((uint8_t*)buf, strlen(buf));
    rawDataChar->notify();
}

void sendAverageData() {
    if (sampleCount > 0) {
        float avgIR = (float)irSum / sampleCount;
        float avgRed = (float)redSum / sampleCount;
        
        char buf[128];
        snprintf(buf, sizeof(buf),
            "{\"type\":\"average\",\"led\":\"%s\",\"avg_ir\":%.2f,\"avg_red\":%.2f,\"samples\":%u}",
            currentLED.c_str(), avgIR, avgRed, sampleCount
        );
        rawDataChar->setValue((uint8_t*)buf, strlen(buf));
        rawDataChar->notify();
        
        Serial.printf("Average for %s - IR: %.2f, Red: %.2f (samples: %u)\n", 
                     currentLED.c_str(), avgIR, avgRed, sampleCount);
    }
}

void setup() {
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);
    
    setup_ble();
    setup_sensor();
    
    Serial.println("=== MAX30100 Quantum Efficiency Test System ===");
    Serial.println("Ready to test photodiode response to different wavelengths");
    Serial.println("Make sure to black tape the emitter LEDs!");
}

void loop() {
    sensor.update();
    
    uint16_t ir, red;
    if (sensor.getRawValues(&ir, &red)) {
        if (collectingData) {
            irSum += ir;
            redSum += red;
            sampleCount++;
            
            // Send average every batch of samples
            if (sampleCount % SAMPLES_PER_BATCH == 0) {
                sendAverageData();
            }
        }
        
        // Send raw data at regular intervals
        if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
            sendRawData(ir, red);
            tsLastReport = millis();
        }
    }
    
    delay(10);
}
