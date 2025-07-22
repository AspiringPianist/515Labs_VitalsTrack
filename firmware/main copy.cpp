#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "ADXL335.h"
#include "MAX30100_PulseOximeter.h"
#include "MAX30100.h"
#include "sensor_quality_model.h"

// ==================================================
// UNIFIED SENSOR SYSTEM - ALL MODES IN ONE
// ==================================================
// Control via BLE commands:
// MODE:HR_SPO2        - Heart rate and SpO2 monitoring
// MODE:TEMPERATURE    - Temperature monitoring
// MODE:FORCE_TEST     - Force sensor testing with labels
// MODE:DISTANCE_TEST  - Distance/quantum efficiency testing
// MODE:QUALITY        - ML-based quality assessment
// MODE:RAW_DATA      - Raw sensor data collection

// Operating modes
enum OperatingMode {
    MODE_IDLE = 0,
    MODE_HR_SPO2 = 1,
    MODE_TEMPERATURE = 2,
    MODE_FORCE_TEST = 3,
    MODE_DISTANCE_TEST = 4,
    MODE_QUALITY = 5,
    MODE_RAW_DATA = 6
};

// Global variables
OperatingMode currentMode = MODE_IDLE;
uint32_t tsLastReport = 0;
uint32_t reportingPeriod = 1000;
bool clientConnected = false;

// Sensor objects - only initialize what we need
PulseOximeter* pox = nullptr;
MAX30100* rawSensor = nullptr;
ADXL335 accel;

// Sensor data
float ax = 0.0, ay = 0.0, az = 0.0;
float heartRate = 0.0, spO2 = 0.0, temperature = 0.0;
uint16_t irValue = 0, redValue = 0, fsrValue = 0;

// BLE variables
BLEServer* bleServer;
BLEService* bleService;
BLECharacteristic* dataChar;
BLECharacteristic* controlChar;
BLECharacteristic* statusChar;

// UUIDs - using consistent set
static const BLEUUID serviceUUID("12345678-1234-5678-1234-56789abcdef0");
static const BLEUUID dataCharUUID("abcdefab-1234-5678-1234-56789abcdef1");
static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");
static const BLEUUID statusCharUUID("abcdefab-1234-5678-1234-56789abcdef3");

// Mode-specific variables
struct {
    String currentLabel = "waiting";
    bool isCollecting = false;
    uint32_t collectionStartTime = 0;
    uint32_t collectionDuration = 10000; // 10 seconds default
} forceTest;

struct {
    String currentLED = "none";
    int currentDistance = 0;
    bool collectingData = false;
    uint32_t irSum = 0;
    uint32_t redSum = 0;
    uint16_t sampleCount = 0;
    uint16_t samplesPerBatch = 10;
} distanceTest;

struct {
    bool tempSamplingStarted = false;
    uint32_t tsLastTempSample = 0;
    uint32_t tempSamplingPeriod = 1000;
} temperatureMode;

struct {
    float previousHeartRate = 0.0;
    float previousSpO2 = 0.0;
    float previousAccelMag = 0.0;
    bool hasPreviousData = false;
    uint32_t totalSamples = 0;
    uint32_t goodQualitySamples = 0;
} qualityMode;

// FSR sensor pin
#define FSR_PIN 35

// ==================================================
// FORWARD DECLARATIONS
// ==================================================
void onBeatDetected();
void sendStatus();
void handleControlCommand(String command);
void switchMode(String modeName);
int assessDataQuality();
bool checkMemory(const char* operation);

// ==================================================
// UTILITY FUNCTIONS
// ==================================================

void onBeatDetected() {
    Serial.println("💓 Beat Detected!");
}

bool checkMemory(const char* operation) {
    uint32_t freeHeap = ESP.getFreeHeap();
    Serial.printf("💾 %s - Free heap: %u bytes\n", operation, freeHeap);
    
    if (freeHeap < 30000) { // Less than 30KB free (reduced for boards without PSRAM)
        Serial.println("⚠️  WARNING: Low memory!");
        return false;
    }
    return true;
}

// ==================================================
// BLE CALLBACK CLASSES
// ==================================================

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        clientConnected = true;
        Serial.println("📱 Client connected");
        sendStatus();
    }
    
    void onDisconnect(BLEServer* pServer) {
        clientConnected = false;
        Serial.println("📱 Client disconnected - restarting advertising");
        BLEDevice::startAdvertising();
    }
};

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* pCharacteristic) {
        String value = pCharacteristic->getValue().c_str();
        handleControlCommand(value);
    }
};

// ==================================================
// UTILITY FUNCTIONS
// ==================================================

void sendStatus() {
    if (!clientConnected) return;
    
    const char* modeNames[] = {"IDLE", "HR_SPO2", "TEMPERATURE", "FORCE_TEST", "DISTANCE_TEST", "QUALITY", "RAW_DATA"};
    char buffer[150];  // Reduced from 200
    snprintf(buffer, sizeof(buffer),
        "{\"status\":\"ready\",\"mode\":\"%s\",\"uptime\":%lu,\"free_heap\":%u}",
        modeNames[currentMode], millis(), ESP.getFreeHeap()
    );
    
    statusChar->setValue((uint8_t*)buffer, strlen(buffer));
    statusChar->notify();
}

void cleanupSensors() {
    Serial.printf("💾 Before cleanup - Free heap: %u bytes\n", ESP.getFreeHeap());
    
    if (pox != nullptr) {
        delete pox;
        pox = nullptr;
    }
    if (rawSensor != nullptr) {
        delete rawSensor;
        rawSensor = nullptr;
    }
    
    Serial.printf("💾 After cleanup - Free heap: %u bytes\n", ESP.getFreeHeap());
}

bool initializePulseOximeter() {
    if (!checkMemory("Before pulse oximeter init")) {
        return false;
    }
    
    cleanupSensors();
    pox = new PulseOximeter();
    
    Serial.print("🔧 Initializing pulse oximeter... ");
    if (!pox->begin()) {
        Serial.println("FAILED");
        delete pox;
        pox = nullptr;
        return false;
    }
    
    // Set beat detection callback
    pox->setOnBeatDetectedCallback(onBeatDetected);
    
    pox->setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal HR/SpO2 signal strength
    Serial.println("✅ SUCCESS");
    checkMemory("After pulse oximeter init");
    return true;
}

bool initializeRawSensor() {
    if (!checkMemory("Before raw sensor init")) {
        return false;
    }
    
    cleanupSensors();
    rawSensor = new MAX30100();
    
    Serial.print("🔧 Initializing raw sensor... ");
    if (!rawSensor->begin()) {
        Serial.println("FAILED");
        delete rawSensor;
        rawSensor = nullptr;
        return false;
    }
    
    rawSensor->setMode(MAX30100_MODE_SPO2_HR);
    rawSensor->setLedsCurrent(MAX30100_LED_CURR_50MA, MAX30100_LED_CURR_50MA);
    rawSensor->setHighresModeEnabled(true);
    Serial.println("✅ SUCCESS");
    checkMemory("After raw sensor init");
    return true;
}

void initializeAccelerometer() {
    Serial.print("🏃 Initializing accelerometer... ");
    accel.begin();
    Serial.println("✅ SUCCESS");
}

// ==================================================
// MODE SWITCHING AND CONTROL
// ==================================================

void handleControlCommand(String command) {
    Serial.println("📨 Command received: " + command);
    
    if (command.startsWith("MODE:")) {
        String mode = command.substring(5);
        switchMode(mode);
    }
    else if (command.startsWith("LABEL:")) {
        // Force test label
        if (currentMode == MODE_FORCE_TEST) {
            forceTest.currentLabel = command.substring(6);
            forceTest.isCollecting = true;
            forceTest.collectionStartTime = millis();
            Serial.println("🏷️  Force test started with label: " + forceTest.currentLabel);
        }
    }
    else if (command.startsWith("START:")) {
        // Distance test start
        if (currentMode == MODE_DISTANCE_TEST) {
            int colonIndex = command.indexOf(':', 6);
            if (colonIndex > 0) {
                distanceTest.currentLED = command.substring(6, colonIndex);
                distanceTest.currentDistance = command.substring(colonIndex + 1).toInt();
            } else {
                distanceTest.currentLED = command.substring(6);
                distanceTest.currentDistance = 0;
            }
            distanceTest.collectingData = true;
            distanceTest.sampleCount = 0;
            distanceTest.irSum = 0;
            distanceTest.redSum = 0;
            Serial.printf("📏 Distance test started: %s at %dmm\n", 
                         distanceTest.currentLED.c_str(), distanceTest.currentDistance);
        }
    }
    else if (command == "STOP") {
        if (currentMode == MODE_FORCE_TEST) {
            forceTest.isCollecting = false;
            forceTest.currentLabel = "waiting";
        } else if (currentMode == MODE_DISTANCE_TEST) {
            distanceTest.collectingData = false;
        }
        Serial.println("⏹️  Collection stopped");
    }
    else if (command == "RESET") {
        if (rawSensor != nullptr) {
            rawSensor->resetFifo();
            Serial.println("🔄 FIFO reset");
        }
    }
    else if (command == "STATUS") {
        sendStatus();
    }
    
    sendStatus();
}

void switchMode(String modeName) {
    OperatingMode newMode = MODE_IDLE;
    uint32_t newReportingPeriod = 1000;
    
    if (modeName == "HR_SPO2") {
        newMode = MODE_HR_SPO2;
        newReportingPeriod = 500;
    } else if (modeName == "TEMPERATURE") {
        newMode = MODE_TEMPERATURE;
        newReportingPeriod = 2000;
    } else if (modeName == "FORCE_TEST") {
        newMode = MODE_FORCE_TEST;
        newReportingPeriod = 100;
    } else if (modeName == "DISTANCE_TEST") {
        newMode = MODE_DISTANCE_TEST;
        newReportingPeriod = 100;
    } else if (modeName == "QUALITY") {
        newMode = MODE_QUALITY;
        newReportingPeriod = 1000;
    } else if (modeName == "RAW_DATA") {
        newMode = MODE_RAW_DATA;
        newReportingPeriod = 500;
    } else if (modeName == "IDLE") {
        newMode = MODE_IDLE;
        newReportingPeriod = 2000;
    }
    
    if (newMode == currentMode) {
        Serial.println("⚡ Already in " + modeName + " mode");
        return;
    }
    
    Serial.println("🔄 Switching to " + modeName + " mode");
    currentMode = newMode;
    reportingPeriod = newReportingPeriod;
    tsLastReport = 0;
    
    // Initialize appropriate sensors for the mode
    bool needsPulseOx = (newMode == MODE_HR_SPO2 || newMode == MODE_QUALITY);
    bool needsRawSensor = (newMode == MODE_TEMPERATURE || newMode == MODE_FORCE_TEST || newMode == MODE_DISTANCE_TEST || newMode == MODE_RAW_DATA);
    bool needsAccel = (newMode == MODE_HR_SPO2 || newMode == MODE_QUALITY || newMode == MODE_RAW_DATA);
    
    if (needsPulseOx) {
        initializePulseOximeter();
    } else if (needsRawSensor) {
        initializeRawSensor();
    }
    
    if (needsAccel) {
        initializeAccelerometer();
    }
    
    // Reset mode-specific variables
    if (newMode == MODE_FORCE_TEST) {
        forceTest.isCollecting = false;
        forceTest.currentLabel = "waiting";
    } else if (newMode == MODE_DISTANCE_TEST) {
        distanceTest.collectingData = false;
        distanceTest.currentLED = "none";
        distanceTest.currentDistance = 0;
    } else if (newMode == MODE_TEMPERATURE) {
        temperatureMode.tempSamplingStarted = false;
        temperatureMode.tsLastTempSample = 0;
    } else if (newMode == MODE_QUALITY) {
        qualityMode.hasPreviousData = false;
        qualityMode.totalSamples = 0;
        qualityMode.goodQualitySamples = 0;
    }
    
    Serial.println("✅ Mode switch complete");
}

// ==================================================
// SENSOR READING FUNCTIONS
// ==================================================

void readSensorData() {
    // Always read accelerometer if available
    accel.getAcceleration(&ax, &ay, &az);
    
    // Read appropriate sensor based on mode
    if (pox != nullptr && (currentMode == MODE_HR_SPO2 || currentMode == MODE_QUALITY)) {
        pox->update();
        float newHeartRate = pox->getHeartRate();
        float newSpO2 = pox->getSpO2();
        
        // Debug output every 5 seconds when values change significantly
        static uint32_t lastDebugOutput = 0;
        if (millis() - lastDebugOutput > 5000 || 
            abs(newHeartRate - heartRate) > 5 || 
            abs(newSpO2 - spO2) > 2) {
            
            Serial.printf("🔍 HR: %.1f -> %.1f, SpO2: %.1f -> %.1f\n", 
                         heartRate, newHeartRate, spO2, newSpO2);
            lastDebugOutput = millis();
        }
        
        heartRate = newHeartRate;
        spO2 = newSpO2;
    }
    
    if (rawSensor != nullptr) {
        rawSensor->update();
        rawSensor->getRawValues(&irValue, &redValue);
        
        // Temperature reading for temperature mode
        if (currentMode == MODE_TEMPERATURE) {
            if (millis() - temperatureMode.tsLastTempSample > temperatureMode.tempSamplingPeriod) {
                if (!temperatureMode.tempSamplingStarted) {
                    rawSensor->startTemperatureSampling();
                    temperatureMode.tempSamplingStarted = true;
                    temperatureMode.tsLastTempSample = millis();
                }
            }
            
            if (temperatureMode.tempSamplingStarted && rawSensor->isTemperatureReady()) {
                temperature = rawSensor->retrieveTemperature();
                temperatureMode.tempSamplingStarted = false;
            }
        }
    }
    
    // Read FSR for force test mode
    if (currentMode == MODE_FORCE_TEST) {
        fsrValue = analogRead(FSR_PIN);
    }
}

// ==================================================
// ML QUALITY ASSESSMENT
// ==================================================

int assessDataQuality() {
    if (!qualityMode.hasPreviousData) {
        qualityMode.hasPreviousData = true;
        qualityMode.previousHeartRate = heartRate;
        qualityMode.previousSpO2 = spO2;
        qualityMode.previousAccelMag = sqrt(ax*ax + ay*ay + az*az);
        return 1; // Good quality for first sample
    }
    
    float currentAccelMag = sqrt(ax*ax + ay*ay + az*az);
    
    // Use the embedded ML model
    int quality = assess_sensor_quality(
        heartRate, spO2, ax, ay, az,
        abs(heartRate - qualityMode.previousHeartRate),
        abs(spO2 - qualityMode.previousSpO2),
        qualityMode.previousAccelMag
    );
    
    // Update previous values
    qualityMode.previousHeartRate = heartRate;
    qualityMode.previousSpO2 = spO2;
    qualityMode.previousAccelMag = currentAccelMag;
    
    return quality;
}

// ==================================================
// DATA TRANSMISSION FUNCTIONS
// ==================================================

void sendData() {
    if (!clientConnected) return;
    
    char buffer[250];  // Reduced from 300
    uint32_t timestamp = millis();
    
    switch (currentMode) {
        case MODE_HR_SPO2:
            snprintf(buffer, sizeof(buffer),
                "{\"hr\":%.1f,\"spo2\":%.1f,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"timestamp\":%lu}",
                heartRate, spO2, ax, ay, az, timestamp
            );
            break;
            
        case MODE_TEMPERATURE:
            snprintf(buffer, sizeof(buffer),
                "{\"temperature\":%.3f,\"timestamp\":%lu}",
                temperature, timestamp
            );
            break;
            
        case MODE_FORCE_TEST:
            if (forceTest.isCollecting) {
                // Check if collection time is up
                if (millis() - forceTest.collectionStartTime >= forceTest.collectionDuration) {
                    forceTest.isCollecting = false;
                    forceTest.currentLabel = "waiting";
                    Serial.println("🏁 Force collection finished");
                    return;
                }
            }
            
            snprintf(buffer, sizeof(buffer),
                "{\"ir\":%u,\"red\":%u,\"fsr\":%u,\"label\":\"%s\",\"collecting\":%s,\"timestamp\":%lu}",
                irValue, redValue, fsrValue, forceTest.currentLabel.c_str(), 
                forceTest.isCollecting ? "true" : "false", timestamp
            );
            break;
            
        case MODE_DISTANCE_TEST:
            if (distanceTest.collectingData) {
                distanceTest.irSum += irValue;
                distanceTest.redSum += redValue;
                distanceTest.sampleCount++;
                
                if (distanceTest.sampleCount % distanceTest.samplesPerBatch == 0) {
                    float avgIR = (float)distanceTest.irSum / distanceTest.sampleCount;
                    float avgRed = (float)distanceTest.redSum / distanceTest.sampleCount;
                    
                    snprintf(buffer, sizeof(buffer),
                        "{\"type\":\"average\",\"led\":\"%s\",\"distance_mm\":%d,\"avg_ir\":%.2f,\"avg_red\":%.2f,\"samples\":%u,\"timestamp\":%lu}",
                        distanceTest.currentLED.c_str(), distanceTest.currentDistance, avgIR, avgRed, distanceTest.sampleCount, timestamp
                    );
                }
            } else {
                snprintf(buffer, sizeof(buffer),
                    "{\"ir\":%u,\"red\":%u,\"led\":\"%s\",\"distance_mm\":%d,\"collecting\":%s,\"timestamp\":%lu}",
                    irValue, redValue, distanceTest.currentLED.c_str(), distanceTest.currentDistance, 
                    distanceTest.collectingData ? "true" : "false", timestamp
                );
            }
            break;
            
        case MODE_QUALITY: {
            int quality = assessDataQuality();
            qualityMode.totalSamples++;
            if (quality > 0) qualityMode.goodQualitySamples++;
            
            float qualityPercent = (qualityMode.totalSamples > 0) ? 
                (float)qualityMode.goodQualitySamples / qualityMode.totalSamples * 100.0f : 0.0f;
                
            snprintf(buffer, sizeof(buffer),
                "{\"hr\":%.1f,\"spo2\":%.1f,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"quality\":%d,\"quality_percent\":%.1f,\"accel_mag\":%.3f,\"timestamp\":%lu}",
                heartRate, spO2, ax, ay, az, quality, qualityPercent, sqrt(ax*ax + ay*ay + az*az), timestamp
            );
            break;
        }
            
        case MODE_RAW_DATA:
            snprintf(buffer, sizeof(buffer),
                "{\"hr\":%.1f,\"spo2\":%.1f,\"ir\":%u,\"red\":%u,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"timestamp\":%lu}",
                heartRate, spO2, irValue, redValue, ax, ay, az, timestamp
            );
            break;
            
        case MODE_IDLE:
        default:
            snprintf(buffer, sizeof(buffer),
                "{\"status\":\"idle\",\"uptime\":%lu,\"free_heap\":%u}",
                timestamp, ESP.getFreeHeap()
            );
            break;
    }
    
    dataChar->setValue((uint8_t*)buffer, strlen(buffer));
    dataChar->notify();
}

// ==================================================
// BLE SETUP
// ==================================================

void setup_ble() {
    BLEDevice::init("ESP32_Unified_Sensor");
    bleServer = BLEDevice::createServer();
    bleServer->setCallbacks(new ServerCallbacks());
    
    bleService = bleServer->createService(serviceUUID);

    // Data characteristic (for sensor readings)
    dataChar = bleService->createCharacteristic(
        dataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    dataChar->addDescriptor(new BLE2902());

    // Control characteristic (for commands)
    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE
    );
    controlChar->setCallbacks(new ControlCallbacks());

    // Status characteristic (for system status)
    statusChar = bleService->createCharacteristic(
        statusCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    statusChar->addDescriptor(new BLE2902());

    bleService->start();

    BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(serviceUUID);
    bleAdv->setScanResponse(true);
    bleAdv->setMinPreferred(0x06);
    bleAdv->setMinPreferred(0x12);
    BLEDevice::startAdvertising();
    
    Serial.println("📡 BLE advertising started - ESP32_Unified_Sensor");
}

// ==================================================
// MAIN SETUP AND LOOP
// ==================================================

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("🚀 ESP32 Unified Sensor System Starting...");
    Serial.printf("💾 Free heap: %u bytes\n", ESP.getFreeHeap());
    Serial.println("==================================================");
    Serial.println("Available modes:");
    Serial.println("  MODE:HR_SPO2      - Heart rate and SpO2 monitoring");
    Serial.println("  MODE:TEMPERATURE  - Temperature monitoring");
    Serial.println("  MODE:FORCE_TEST   - Force sensor testing with labels");
    Serial.println("  MODE:DISTANCE_TEST - Distance/quantum efficiency testing");
    Serial.println("  MODE:QUALITY      - ML-based quality assessment");
    Serial.println("  MODE:RAW_DATA     - Raw sensor data collection");
    Serial.println("  MODE:IDLE         - Idle mode");
    Serial.println("==================================================");
    
    Wire.begin();
    Wire.setClock(100000);  // Changed from 400000 to match library code
    
    // Initialize FSR pin
    pinMode(FSR_PIN, INPUT);
    
    // Initialize accelerometer (always available)
    initializeAccelerometer();
    
    Serial.printf("💾 After accel init - Free heap: %u bytes\n", ESP.getFreeHeap());
    
    // Setup BLE
    setup_ble();
    
    Serial.printf("💾 After BLE init - Free heap: %u bytes\n", ESP.getFreeHeap());
    Serial.println("✅ System ready - waiting for mode selection via BLE");
    Serial.println("💡 Send MODE:HR_SPO2 (or other mode) to start");
}

void loop() {
    // Monitor memory usage periodically
    static uint32_t lastMemoryCheck = 0;
    if (millis() - lastMemoryCheck > 10000) { // Every 10 seconds
        Serial.printf("💾 Free heap: %u bytes\n", ESP.getFreeHeap());
        lastMemoryCheck = millis();
    }
    
    // Always read sensor data
    readSensorData();
    
    // Send data at appropriate intervals
    if (millis() - tsLastReport >= reportingPeriod) {
        sendData();
        tsLastReport = millis();
    }
    
    // Small delay to prevent overwhelming the system
}
