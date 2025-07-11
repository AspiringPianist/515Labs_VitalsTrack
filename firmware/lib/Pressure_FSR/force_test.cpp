#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30100.h"

#define REPORTING_PERIOD_MS 100
#define COLLECTION_TIME_MS 10000  // 10 seconds
#define FSR_PIN 35

MAX30100 sensor;
uint32_t tsLastReport = 0;

// BLE variables
BLEServer* bleServer;
BLEService* bleService;
BLECharacteristic* rawDataChar;
BLECharacteristic* controlChar;

// UUIDs
static const BLEUUID serviceUUID("12345678-1234-5678-1234-56789abcdef0");
static const BLEUUID rawDataCharUUID("abcdefab-1234-5678-1234-56789abcdef1");
static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");

// Simplified state management
char currentLabel[32] = "waiting";
bool isCollecting = false;
uint32_t collectionStartTime = 0;
bool clientConnected = false;

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        clientConnected = true;
        Serial.println("Client connected");
    }
    
    void onDisconnect(BLEServer* pServer) {
        clientConnected = false;
        Serial.println("Client disconnected - restarting advertising");
        BLEDevice::startAdvertising();
    }
};

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* pCharacteristic) {
        std::string value = pCharacteristic->getValue();
        
        if (value.length() > 6 && value.substr(0, 6) == "LABEL:") {
            // Stop any current collection
            isCollecting = false;
            
            // Set new label (safely)
            String newLabel = value.substr(6).c_str();
            newLabel.toCharArray(currentLabel, sizeof(currentLabel));
            
            Serial.println("Starting collection with label: " + String(currentLabel));
            
            // Start new collection
            isCollecting = true;
            collectionStartTime = millis();
            tsLastReport = 0;
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
    
    pinMode(FSR_PIN, INPUT);
    Serial.println("FSR sensor configured");
}

void setup_ble() {
    BLEDevice::init("ESP32_FSR_Collector");
    bleServer = BLEDevice::createServer();
    bleServer->setCallbacks(new ServerCallbacks());
    
    bleService = bleServer->createService(serviceUUID);

    rawDataChar = bleService->createCharacteristic(
        rawDataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY
    );
    rawDataChar->addDescriptor(new BLE2902());

    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE
    );
    controlChar->setCallbacks(new ControlCallbacks());

    bleService->start();

    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(serviceUUID);
    bleAdv->setScanResponse(true);
    BLEDevice::startAdvertising();
    
    Serial.println("BLE ready - waiting for connection");
}

void sendData(uint16_t ir, uint16_t red, uint16_t fsrValue) {
    if (!clientConnected) return;
    
    // Use static buffer to avoid memory issues
    static char buffer[120];
    snprintf(buffer, sizeof(buffer),
        "{\"ir\":%u,\"red\":%u,\"fsr\":%u,\"label\":\"%s\",\"timestamp\":%lu}",
        ir, red, fsrValue, currentLabel, millis()
    );
    
    rawDataChar->setValue((uint8_t*)buffer, strlen(buffer));
    rawDataChar->notify();
}

void setup() {
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);
    
    setup_ble();
    setup_sensor();
    
    Serial.println("=== Ready for data collection ===");
    Serial.println("Send LABEL:your_label to start 10-second collection");
}

void loop() {
    // Always update sensor
    sensor.update();
    
    // Check if we should collect data
    if (isCollecting) {
        // Check if collection time is up
        if (millis() - collectionStartTime >= COLLECTION_TIME_MS) {
            isCollecting = false;
            strcpy(currentLabel, "waiting");
            Serial.println("Collection finished - ready for next label");
            return;
        }
        
        // Collect and send data
        uint16_t ir, red;
        uint16_t fsrValue = analogRead(FSR_PIN);
        
        if (sensor.getRawValues(&ir, &red)) {
            if (millis() - tsLastReport >= REPORTING_PERIOD_MS) {
                sendData(ir, red, fsrValue);
                tsLastReport = millis();
                
                // Show progress
                uint32_t elapsed = millis() - collectionStartTime;
                if (elapsed % 2000 < 100) { // Every 2 seconds
                    Serial.printf("Collecting [%s]: %d/%d seconds\n", 
                                currentLabel, elapsed/1000, COLLECTION_TIME_MS/1000);
                }
            }
        }
    }
    
    delay(10);
}
