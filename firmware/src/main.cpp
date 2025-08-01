#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <esp_wifi.h>
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
// MODE:RAW_DATA       - Raw sensor data collection

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
uint32_t reportingPeriod = 500;  // Default 2Hz (500ms) for all modes
bool clientConnected = false;

// Sensor objects - static to avoid dynamic allocation
PulseOximeter pox;
MAX30100 rawSensor;
ADXL335 accel;
bool poxInitialized = false;
bool rawSensorInitialized = false;

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
    char currentLabel[16] = "waiting";
    bool isCollecting = false;
    uint32_t collectionStartTime = 0;
    uint32_t collectionDuration = 10000;
} forceTest;

struct {
    char currentLED[8] = "none";
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
void handleControlCommand(const char* command);
void switchMode(const char* modeName);
int assessDataQuality();
bool checkMemory(const char* operation);
void resetSensors();
bool primeSensor(); // New function for priming

// ==================================================
// UTILITY FUNCTIONS
// ==================================================

void onBeatDetected() {
    Serial.println("💓 Beat Detected!");
}

bool checkMemory(const char* operation) {
    uint32_t freeHeap = ESP.getFreeHeap();
    Serial.printf("💾 %s - Free heap: %u bytes\n", operation, freeHeap);
    if (freeHeap < 30000) {
        Serial.println("⚠️  WARNING: Low memory!");
        return false;
    }
    return true;
}

void resetSensors() {
    Serial.println("🔄 Resetting sensors...");
    
    // First shutdown any active sensors
    if (poxInitialized) {
        pox.shutdown();
        delay(50);  // Give time for shutdown to complete
        poxInitialized = false;
    }
    if (rawSensorInitialized) {
        rawSensor.shutdown();
        delay(50);  // Give time for shutdown to complete
        rawSensorInitialized = false;
    }
    
    // Reset I2C bus
    Wire.end();
    delay(100);  // Allow bus to fully reset
    
    // Reinitialize I2C
    Wire.begin();
    Wire.setClock(100000);  // 100kHz I2C for better stability
    delay(50);  // Allow bus to stabilize
    
    // Reset MAX30100 registers to default state
    Wire.beginTransmission(0x57);  // MAX30100 I2C address
    Wire.write(0xFF);  // Reset command register
    Wire.write(0x40);  // Reset command
    Wire.endTransmission();
    delay(100);  // Wait for reset to complete
    
    Serial.println("✅ Sensors and I2C bus reset");
}

bool primeSensor(PulseOximeter& poxSensor, MAX30100& rawSensor, bool isPulseOximeter) {
    Serial.print("🔧 Priming sensor... ");
    
    // Step 1: Reset FIFO and mode
    if (isPulseOximeter) {
        poxSensor.shutdown();
        if (!poxSensor.begin()) {
            Serial.println("FAILED to begin during priming");
            return false;
        }
        poxSensor.setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal HR/SpO2 signal strength
    } else {
        rawSensor.resetFifo();
        rawSensor.shutdown();
        if (!rawSensor.begin()) {
            Serial.println("FAILED to begin during priming");
            return false;
        }
        rawSensor.setMode(MAX30100_MODE_SPO2_HR);
        rawSensor.setLedsCurrent(MAX30100_LED_CURR_24MA, MAX30100_LED_CURR_24MA);  // Set both IR and Red to 24mA
        rawSensor.setHighresModeEnabled(true);  // Enable high resolution mode for consistency
    }
    
    // Step 2: Perform dummy reads to stabilize
    uint32_t startTime = millis();
    uint16_t dummyIr, dummyRed;
    for (int i = 0; i < 10; i++) { // 10 dummy reads
        if (isPulseOximeter) {
            poxSensor.update();
        } else {
            rawSensor.update();
            rawSensor.getRawValues(&dummyIr, &dummyRed);
        }
        delay(20); // 20ms per read, total ~200ms
        if (millis() - startTime > 500) { // Timeout after 500ms
            Serial.println("FAILED: Priming timeout");
            return false;
        }
    }
    
    // Step 3: Verify sensor state
    bool isReady = isPulseOximeter ? poxSensor.begin() : rawSensor.begin();
    if (!isReady) {
        Serial.println("FAILED: Sensor not ready after priming");
        return false;
    }
    
    Serial.println("✅ SUCCESS");
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
        resetSensors();
        currentMode = MODE_IDLE;
        reportingPeriod = 500;  // Consistent 2Hz (500ms) for all modes
        tsLastReport = 0;
        forceTest.isCollecting = false;
        distanceTest.collectingData = false;
        temperatureMode.tempSamplingStarted = false;
        qualityMode.hasPreviousData = false;
        BLEDevice::startAdvertising();
    }
};

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* pCharacteristic) {
        const char* value = pCharacteristic->getValue().c_str();
        handleControlCommand(value);
    }
};

// ==================================================
// UTILITY FUNCTIONS
// ==================================================

void sendStatus() {
    if (!clientConnected) return;
    
    const char* modeNames[] = {"IDLE", "HR_SPO2", "TEMPERATURE", "FORCE_TEST", "DISTANCE_TEST", "QUALITY", "RAW_DATA"};
    char buffer[150];
    snprintf(buffer, sizeof(buffer),
        "{\"status\":\"ready\",\"mode\":\"%s\",\"uptime\":%lu,\"free_heap\":%u}",
        modeNames[currentMode], millis(), ESP.getFreeHeap()
    );
    
    statusChar->setValue((uint8_t*)buffer, strlen(buffer));
    statusChar->notify();
}

bool initializePulseOximeter() {
    if (!checkMemory("Before pulse oximeter init")) {
        return false;
    }
    
    resetSensors();
    
    // Wait for sensor to be fully reset
    delay(200);
    
    Serial.print("🔧 Initializing pulse oximeter... ");
    
    // Try initialization with retries
    int retryCount = 0;
    const int maxRetries = 3;
    
    while (retryCount < maxRetries) {
        if (primeSensor(pox, rawSensor, true)) {
            pox.setOnBeatDetectedCallback(onBeatDetected);
            poxInitialized = true;
            Serial.println("✅ SUCCESS");
            checkMemory("After pulse oximeter init");
            return true;
        }
        
        Serial.print("Retry ");
        Serial.println(retryCount + 1);
        delay(100);
        resetSensors();
        retryCount++;
    }
    
    Serial.println("FAILED after retries");
    poxInitialized = false;
    return false;
}

bool initializeRawSensor() {
    if (!checkMemory("Before raw sensor init")) {
        return false;
    }
    
    resetSensors();
    Serial.print("🔧 Initializing raw sensor... ");
    if (!primeSensor(pox, rawSensor, false)) {
        Serial.println("FAILED");
        rawSensorInitialized = false;
        return false;
    }
    
    rawSensorInitialized = true;
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

void handleControlCommand(const char* command) {
    Serial.printf("📨 Command received: %s\n", command);
    
    if (strncmp(command, "MODE:", 5) == 0) {
        switchMode(command + 5);
    }
    else if (strncmp(command, "LABEL:", 6) == 0) {
        if (currentMode == MODE_FORCE_TEST) {
            strncpy(forceTest.currentLabel, command + 6, sizeof(forceTest.currentLabel) - 1);
            forceTest.currentLabel[sizeof(forceTest.currentLabel) - 1] = '\0';
            forceTest.isCollecting = true;
            forceTest.collectionStartTime = millis();
            Serial.printf("🏷️  Force test started with label: %s\n", forceTest.currentLabel);
        }
    }
    else if (strncmp(command, "START:", 6) == 0) {
        if (currentMode == MODE_DISTANCE_TEST) {
            const char* colon = strchr(command + 6, ':');
            if (colon) {
                strncpy(distanceTest.currentLED, command + 6, colon - (command + 6));
                distanceTest.currentLED[colon - (command + 6)] = '\0';
                distanceTest.currentDistance = atoi(colon + 1);
            } else {
                strncpy(distanceTest.currentLED, command + 6, sizeof(distanceTest.currentLED) - 1);
                distanceTest.currentLED[sizeof(distanceTest.currentLED) - 1] = '\0';
                distanceTest.currentDistance = 0;
            }
            distanceTest.collectingData = true;
            distanceTest.sampleCount = 0;
            distanceTest.irSum = 0;
            distanceTest.redSum = 0;
            Serial.printf("📏 Distance test started: %s at %dmm\n", 
                         distanceTest.currentLED, distanceTest.currentDistance);
        }
    }
    else if (strcmp(command, "STOP") == 0) {
        if (currentMode == MODE_FORCE_TEST) {
            forceTest.isCollecting = false;
            strncpy(forceTest.currentLabel, "waiting", sizeof(forceTest.currentLabel));
        } else if (currentMode == MODE_DISTANCE_TEST) {
            distanceTest.collectingData = false;
        }
        Serial.println("⏹️  Collection stopped");
    }
    else if (strcmp(command, "RESET") == 0) {
        resetSensors();
    }
    else if (strcmp(command, "STATUS") == 0) {
        sendStatus();
    }
    
    sendStatus();
}

void switchMode(const char* modeName) {
    OperatingMode newMode = MODE_IDLE;
    uint32_t newReportingPeriod = 500;  // Default to 2Hz (500ms) for all modes
    
    if (strcmp(modeName, "HR_SPO2") == 0) {
        newMode = MODE_HR_SPO2;
        newReportingPeriod = 500;
    } else if (strcmp(modeName, "TEMPERATURE") == 0) {
        newMode = MODE_TEMPERATURE;
        newReportingPeriod = 500;  // Changed from 2000ms to 500ms for 2Hz
    } else if (strcmp(modeName, "FORCE_TEST") == 0) {
        newMode = MODE_FORCE_TEST;
        newReportingPeriod = 500;  // Changed from 100ms to 500ms for 2Hz
    } else if (strcmp(modeName, "DISTANCE_TEST") == 0) {
        newMode = MODE_DISTANCE_TEST;
        newReportingPeriod = 500;  // Changed from 100ms to 500ms for 2Hz
    } else if (strcmp(modeName, "QUALITY") == 0) {
        newMode = MODE_QUALITY;
        newReportingPeriod = 500;  // Changed from 1000ms to 500ms for 2Hz
    } else if (strcmp(modeName, "RAW_DATA") == 0) {
        newMode = MODE_RAW_DATA;
        newReportingPeriod = 500;
    } else if (strcmp(modeName, "IDLE") == 0) {
        newMode = MODE_IDLE;
        newReportingPeriod = 500;  // Changed from 2000ms to 500ms for 2Hz
    }
    
    if (newMode == currentMode) {
        Serial.printf("⚡ Already in %s mode\n", modeName);
        return;
    }
    
    Serial.printf("🔄 Switching to %s mode\n", modeName);
    currentMode = newMode;
    reportingPeriod = newReportingPeriod;
    tsLastReport = 0;
    
    bool needsPulseOx = (newMode == MODE_HR_SPO2 || newMode == MODE_QUALITY);
    bool needsRawSensor = (newMode == MODE_TEMPERATURE || newMode == MODE_FORCE_TEST || 
                         newMode == MODE_DISTANCE_TEST || newMode == MODE_RAW_DATA);
    bool needsAccel = (newMode == MODE_HR_SPO2 || newMode == MODE_QUALITY || newMode == MODE_RAW_DATA);
    
    if (newMode == MODE_IDLE) {
        resetSensors();
    } else {
        // Always reinitialize the correct sensor type when switching modes
        // This ensures proper LED settings and configuration
        if (needsPulseOx) {
            if (rawSensorInitialized) {
                // Switching from raw sensor to pulse oximeter
                Serial.println("🔄 Switching from raw sensor to pulse oximeter");
                resetSensors(); // Clean reset before switching
            }
            initializePulseOximeter();
        } else if (needsRawSensor) {
            if (poxInitialized) {
                // Switching from pulse oximeter to raw sensor  
                Serial.println("🔄 Switching from pulse oximeter to raw sensor");
                resetSensors(); // Clean reset before switching
            }
            initializeRawSensor();
        }
        
        if (needsAccel) {
            initializeAccelerometer();
        }
    }
    
    if (newMode == MODE_FORCE_TEST) {
        forceTest.isCollecting = false;
        strncpy(forceTest.currentLabel, "waiting", sizeof(forceTest.currentLabel));
    } else if (newMode == MODE_DISTANCE_TEST) {
        distanceTest.collectingData = false;
        strncpy(distanceTest.currentLED, "none", sizeof(distanceTest.currentLED));
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
    accel.getAcceleration(&ax, &ay, &az);
    
    if (poxInitialized && (currentMode == MODE_HR_SPO2 || currentMode == MODE_QUALITY)) {
        pox.update();
        float newHeartRate = pox.getHeartRate();
        float newSpO2 = pox.getSpO2();
        
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
    
    if (rawSensorInitialized) {
        rawSensor.update();
        rawSensor.getRawValues(&irValue, &redValue);
        
        if (currentMode == MODE_TEMPERATURE) {
            if (millis() - temperatureMode.tsLastTempSample > temperatureMode.tempSamplingPeriod) {
                if (!temperatureMode.tempSamplingStarted) {
                    rawSensor.startTemperatureSampling();
                    temperatureMode.tempSamplingStarted = true;
                    temperatureMode.tsLastTempSample = millis();
                }
            }
            
            if (temperatureMode.tempSamplingStarted && rawSensor.isTemperatureReady()) {
                temperature = rawSensor.retrieveTemperature();
                temperatureMode.tempSamplingStarted = false;
            }
        }
    }
    
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
        return 1;
    }
    
    float currentAccelMag = sqrt(ax*ax + ay*ay + az*az);
    
    int quality = assess_sensor_quality(
        heartRate, spO2, ax, ay, az,
        abs(heartRate - qualityMode.previousHeartRate),
        abs(spO2 - qualityMode.previousSpO2),
        qualityMode.previousAccelMag
    );
    
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
    
    char buffer[300];
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
                if (millis() - forceTest.collectionStartTime >= forceTest.collectionDuration) {
                    forceTest.isCollecting = false;
                    strncpy(forceTest.currentLabel, "waiting", sizeof(forceTest.currentLabel));
                    Serial.println("🏁 Force collection finished");
                    return;
                }
            }
            
            snprintf(buffer, sizeof(buffer),
                "{\"ir\":%u,\"red\":%u,\"fsr\":%u,\"label\":\"%s\",\"collecting\":%s,\"timestamp\":%lu}",
                irValue, redValue, fsrValue, forceTest.currentLabel, 
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
                        distanceTest.currentLED, distanceTest.currentDistance, avgIR, avgRed, distanceTest.sampleCount, timestamp
                    );
                }
            } else {
                snprintf(buffer, sizeof(buffer),
                    "{\"ir\":%u,\"red\":%u,\"led\":\"%s\",\"distance_mm\":%d,\"collecting\":%s,\"timestamp\":%lu}",
                    irValue, redValue, distanceTest.currentLED, distanceTest.currentDistance, 
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

    dataChar = bleService->createCharacteristic(
        dataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    dataChar->addDescriptor(new BLE2902());

    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE
    );
    controlChar->setCallbacks(new ControlCallbacks());

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
    
    esp_wifi_stop(); // Disable Wi-Fi to save power
    
    Wire.begin();
    Wire.setClock(100000);  // Use 100kHz I2C speed for better stability
    
    pinMode(FSR_PIN, INPUT);
    
    initializeAccelerometer();
    
    Serial.printf("💾 After accel init - Free heap: %u bytes\n", ESP.getFreeHeap());
    
    setup_ble();
    
    Serial.printf("💾 After BLE init - Free heap: %u bytes\n", ESP.getFreeHeap());
    Serial.println("✅ System ready - waiting for mode selection via BLE");
    Serial.println("💡 Send MODE:HR_SPO2 (or other mode) to start");
}

void loop() {
    static uint32_t lastMemoryCheck = 0;
    if (millis() - lastMemoryCheck > 10000) {
        Serial.printf("💾 Free heap: %u bytes\n", ESP.getFreeHeap());
        lastMemoryCheck = millis();
    }
    
    readSensorData();
    
    if (millis() - tsLastReport >= reportingPeriod) {
        sendData();
        tsLastReport = millis();
    }
}