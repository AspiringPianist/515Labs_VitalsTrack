#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "ADXL335.h"
#include "MAX30100_PulseOximeter.h"

// Conditional compilation flag - change this to switch between modes
#define USE_QUALITY_MODE 1  // Set to 1 for Quality Assessment, 0 for Raw Data Collection

#if USE_QUALITY_MODE
  // Quality Assessment Mode with ML Model
  #include "sensor_quality_model.h"  // Our generated ML model header
  
  #define REPORTING_PERIOD_MS 1000  // 1Hz for quality assessment
  
  PulseOximeter pox;
  ADXL335 accel;
  float ax = 0.0, ay = 0.0, az = 0.0;
  uint32_t tsLastReport = 0;
  
  // BLE variables
  BLEServer* bleServer;
  BLEService* bleService;
  BLECharacteristic* vitalsDataChar;
  BLECharacteristic* qualityChar;
  BLECharacteristic* controlChar;
  
  // UUIDs for Quality Mode
  static const BLEUUID serviceUUID("12345678-1234-5678-1234-56789abcdef0");
  static const BLEUUID vitalsDataCharUUID("abcdefab-1234-5678-1234-56789abcdef3");
  static const BLEUUID qualityCharUUID("abcdefab-1234-5678-1234-56789abcdef4");
  static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");
  
  // Quality assessment variables
  struct SensorData {
      float heartRate;
      float spO2;
      float ax, ay, az;
      uint32_t timestamp;
      int quality;
  };
  
  SensorData currentData;
  SensorData previousData;
  bool hasPreviousData = false;
  bool clientConnected = false;
  
  // Quality statistics
  uint32_t totalSamples = 0;
  uint32_t goodQualitySamples = 0;
  uint32_t qualityCheckInterval = 10;
  
  class ServerCallbacks: public BLEServerCallbacks {
      void onConnect(BLEServer* pServer) {
          clientConnected = true;
          Serial.println("📱 Client connected to Quality Monitor");
      }
      
      void onDisconnect(BLEServer* pServer) {
          clientConnected = false;
          Serial.println("📱 Client disconnected - restarting advertising");
          BLEDevice::startAdvertising();
      }
  };
  
  class ControlCallbacks: public BLECharacteristicCallbacks {
      void onWrite(BLECharacteristic* pCharacteristic) {
          std::string value = pCharacteristic->getValue();
          
          if (value == "RESET_STATS") {
              totalSamples = 0;
              goodQualitySamples = 0;
              Serial.println("🔄 Quality statistics reset");
          } else if (value.substr(0, 9) == "INTERVAL:") {
              qualityCheckInterval = std::stoi(value.substr(9));
              Serial.println("⏱️ Quality check interval set to: " + String(qualityCheckInterval));
          } else if (value == "RECALIBRATE") {
              // Trigger sensor recalibration
              Serial.println("🔧 Recalibrating sensors...");
              pox.setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal signal strength
          }
      }
  };
  
  void setup_oximeter() {
      Serial.print("🔧 Initializing pulse oximeter... ");
      if (!pox.begin()) {
          Serial.println("❌ FAILED");
          while (1);
      } else {
          Serial.println("✅ SUCCESS");
      }
      pox.setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal signal strength
  }
  
  void setup_accel() {
      Serial.print("🏃 Initializing accelerometer... ");
      accel.begin();
      Serial.println("✅ SUCCESS");
  }
  
  void setup_ble() {
      BLEDevice::init("ESP32_Quality_Monitor");
      bleServer = BLEDevice::createServer();
      bleServer->setCallbacks(new ServerCallbacks());
      
      bleService = bleServer->createService(serviceUUID);
  
      // Vitals data characteristic
      vitalsDataChar = bleService->createCharacteristic(
          vitalsDataCharUUID,
          BLECharacteristic::PROPERTY_NOTIFY
      );
      vitalsDataChar->addDescriptor(new BLE2902());
  
      // Quality assessment characteristic
      qualityChar = bleService->createCharacteristic(
          qualityCharUUID,
          BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
      );
      qualityChar->addDescriptor(new BLE2902());
  
      // Control characteristic
      controlChar = bleService->createCharacteristic(
          controlCharUUID,
          BLECharacteristic::PROPERTY_WRITE
      );
      controlChar->setCallbacks(new ControlCallbacks());
  
      bleService->start();
  
      BLEAdvertising* bleAdv = BLEDevice::getAdvertising();
      bleAdv->addServiceUUID(serviceUUID);
      bleAdv->setScanResponse(true);
      bleAdv->setMinPreferred(0x06);
      bleAdv->setMinPreferred(0x12);
      BLEDevice::startAdvertising();
      
      Serial.println("📡 BLE advertising started");
  }
  
  void readSensorData() {
      // Read pulse oximeter data
      currentData.heartRate = pox.getHeartRate();
      currentData.spO2 = pox.getSpO2();
      
      // Read accelerometer data
      accel.getAcceleration(&currentData.ax, &currentData.ay, &currentData.az);
      
      // Set timestamp
      currentData.timestamp = millis();
      
      // Validate sensor readings
      if (currentData.heartRate < 30 || currentData.heartRate > 220) {
          currentData.heartRate = hasPreviousData ? previousData.heartRate : 75;
      }
      if (currentData.spO2 < 70 || currentData.spO2 > 100) {
          currentData.spO2 = hasPreviousData ? previousData.spO2 : 98;
      }
  }
  
  int assessDataQuality() {
      if (!hasPreviousData) {
          return 1; // Assume good quality for first sample
      }
      
      // Use our embedded ML model for quality assessment
      float prev_accel_mag = sqrt(previousData.ax*previousData.ax + 
                                 previousData.ay*previousData.ay + 
                                 previousData.az*previousData.az);
      
      int quality = assess_sensor_quality(
          currentData.heartRate, currentData.spO2,
          currentData.ax, currentData.ay, currentData.az,
          previousData.heartRate, previousData.spO2,
          prev_accel_mag
      );
      
      return quality;
  }
  
  void sendVitalsData() {
      if (!clientConnected) return;
      
      // Create JSON with vitals and quality
      char buffer[250];
      snprintf(buffer, sizeof(buffer),
          "{\"hr\":%.1f,\"spo2\":%.1f,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"quality\":%d,\"timestamp\":%lu,\"accel_mag\":%.3f}",
          currentData.heartRate, currentData.spO2,
          currentData.ax, currentData.ay, currentData.az,
          currentData.quality, currentData.timestamp,
          sqrt(currentData.ax*currentData.ax + currentData.ay*currentData.ay + currentData.az*currentData.az)
      );
      
      vitalsDataChar->setValue((uint8_t*)buffer, strlen(buffer));
      vitalsDataChar->notify();
  }
  
  void sendQualityReport() {
      if (!clientConnected) return;
      
      float qualityPercentage = (totalSamples > 0) ? 
          (float)goodQualitySamples / totalSamples * 100.0f : 0.0f;
      
      char buffer[200];
      snprintf(buffer, sizeof(buffer),
          "{\"total_samples\":%lu,\"good_samples\":%lu,\"quality_percent\":%.1f,\"timestamp\":%lu,\"model_features\":%d}",
          totalSamples, goodQualitySamples, qualityPercentage, millis(), NUM_FEATURES
      );
      
      qualityChar->setValue((uint8_t*)buffer, strlen(buffer));
      qualityChar->notify();
      
      Serial.printf("📊 Quality Report: %.1f%% (%lu/%lu samples)\n", 
                    qualityPercentage, goodQualitySamples, totalSamples);
  }

#else
  // Raw Data Collection Mode
  #define REPORTING_PERIOD_MS 500
  
  PulseOximeter pox;
  ADXL335 accel;
  float ax = 0.0, ay = 0.0, az = 0.0;
  uint32_t tsLastReport = 0;
  
  // BLE variables
  BLEServer* bleServer;
  BLEService* bleService;
  BLECharacteristic* rawDataChar;
  BLECharacteristic* controlChar;
  
  // UUIDs for Raw Data Mode
  static const BLEUUID serviceUUID("12345678-1234-5678-1234-56789abcdef0");
  static const BLEUUID rawDataCharUUID("abcdefab-1234-5678-1234-56789abcdef1");
  static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");
  
  // Data collection variables
  String currentLabel = "unlabeled";
  bool collectingData = true;
  
  class ControlCallbacks: public BLECharacteristicCallbacks {
      void onWrite(BLECharacteristic* pCharacteristic) {
          String value = pCharacteristic->getValue().c_str();
          
          if (value.startsWith("LABEL:")) {
              currentLabel = value.substring(6);
              Serial.println("Label changed to: " + currentLabel);
          } else if (value == "RESET") {
              Serial.println("System reset requested");
              // Reset any calibration or buffers
          }
      }
  };
  
  void setup_oximeter() {
      Serial.print("Initializing pulse oximeter... ");
      if (!pox.begin()) {
          Serial.println("FAILED");
          while (1);
      } else {
          Serial.println("SUCCESS");
      }
      pox.setIRLedCurrent(MAX30100_LED_CURR_24MA);  // Set to 24mA for optimal signal strength
  }
  
  void setup_accel() {
      accel.begin();
  }
  
  void setup_ble() {
      BLEDevice::init("ESP32_Raw_Collector");
      bleServer = BLEDevice::createServer();
      bleService = bleServer->createService(serviceUUID);
  
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
      bleAdv->addServiceUUID(serviceUUID);
      bleAdv->setScanResponse(true);
      bleAdv->setMinPreferred(0x06);
      bleAdv->setMinPreferred(0x12);
      BLEDevice::startAdvertising();
      Serial.println("BLE advertising started");
  }
  
  void sendRawData(float hr, float spo2, float ax, float ay, float az) {
      char buf[200];
      snprintf(buf, sizeof(buf),
          "{\"hr\":%.1f,\"spo2\":%.1f,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"label\":\"%s\",\"timestamp\":%lu}",
          hr, spo2, ax, ay, az, currentLabel.c_str(), millis()
      );
      rawDataChar->setValue((uint8_t*)buf, strlen(buf));
      rawDataChar->notify();
  }

#endif

void setup() {
    Serial.begin(115200);
    Wire.begin();
    
#if USE_QUALITY_MODE
    Wire.setClock(100000);  // Use 100kHz for stable operation with ADXL335
    
    Serial.println("🚀 ESP32 Quality Assessment Mode Starting...");
    Serial.println("🧠 ML Model Features: " + String(NUM_FEATURES));
    Serial.println("⚡ Scale Factor: " + String(SCALE_FACTOR));
    
    setup_ble();
    setup_oximeter();
    setup_accel();
    
    // Initialize previous data
    previousData = {0};
    
    Serial.println("✅ Quality monitoring system ready!");
    Serial.println("📊 Monitoring: HR, SpO2, Accelerometer + ML Quality Assessment");
#else
    Wire.setClock(100000);  // Use 100kHz for stable operation
    
    Serial.println("🚀 ESP32 Raw Data Collection Mode Starting...");
    setup_ble();
    setup_oximeter();
    setup_accel();
    Serial.println("✅ Raw data collection system ready!");
#endif
}

void loop() {
#if USE_QUALITY_MODE
    // Quality Assessment Mode Loop
    pox.update();
    
    if (millis() - tsLastReport >= REPORTING_PERIOD_MS) {
        // Read all sensor data
        readSensorData();
        
        // Assess quality using embedded ML model
        currentData.quality = assessDataQuality();
        
        // Update statistics
        totalSamples++;
        if (currentData.quality == 1) {
            goodQualitySamples++;
        }
        
        // Send data via BLE
        sendVitalsData();
        
        // Send quality report periodically
        if (totalSamples % qualityCheckInterval == 0) {
            sendQualityReport();
        }
        
        // Print quality status to serial
        String qualityStatus = (currentData.quality == 1) ? "✅ GOOD" : "❌ POOR";
        float overallQuality = (float)goodQualitySamples / totalSamples * 100.0f;
        
        Serial.printf("📊 HR:%.1f SpO2:%.1f Accel:{%.2f,%.2f,%.2f} Quality:%s (%.1f%% overall)\n",
                      currentData.heartRate, currentData.spO2, 
                      currentData.ax, currentData.ay, currentData.az,
                      qualityStatus.c_str(), overallQuality);
        
        // Store current as previous for next iteration
        previousData = currentData;
        hasPreviousData = true;
        
        tsLastReport = millis();
    }
    
    delay(10);

#else
    // Raw Data Collection Mode Loop
    pox.update();

    if (millis() - tsLastReport > REPORTING_PERIOD_MS) {
        float hr = pox.getHeartRate();
        float spo2 = pox.getSpO2();
        accel.getAcceleration(&ax, &ay, &az);

        Serial.printf("HR: %.1f | SpO2: %.1f | Accel: {%.2f, %.2f, %.2f} | Label: %s\n", 
                      hr, spo2, ax, ay, az, currentLabel.c_str());

        sendRawData(hr, spo2, ax, ay, az);
        tsLastReport = millis();
    }
    
    delay(10);
#endif
}
