// Force testing version of MAX30102 with FSR sensor
#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <SPIFFS.h>
#include "MAX30100.h"

#define REPORTING_PERIOD_MS 100
#define SAMPLES_PER_BATCH 10
#define FSR_PIN A0        // Analog pin for FSR sensor
#define FSR_POWER_PIN 3.3 // Power supply voltage for FSR

MAX30100 sensor;
uint32_t tsLastReport = 0;

// BLE variables
BLEServer *bleServer;
BLEService *bleService;
BLECharacteristic *rawDataChar;
BLECharacteristic *controlChar;

// UUIDs for force testing
static const BLEUUID forceServiceUUID("12345678-1234-5678-1234-56789abcdef0");
static const BLEUUID rawDataCharUUID("abcdefab-1234-5678-1234-56789abcdef1");
static const BLEUUID controlCharUUID("abcdefab-1234-5678-1234-56789abcdef2");

// Data collection variables
uint32_t irSum = 0;
uint32_t redSum = 0;
uint32_t forceSum = 0;
uint16_t sampleCount = 0;
bool collectingData = false;
String currentTest = "none";
int testNumber = 0;
unsigned long testStartTime = 0;

// CSV logging
String csvData = "";
bool csvHeaderWritten = false;

class ControlCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        String value = pCharacteristic->getValue().c_str();

        if (value.startsWith("START:"))
        {
            currentTest = value.substring(6);
            testNumber++;
            collectingData = true;
            sampleCount = 0;
            irSum = 0;
            redSum = 0;
            forceSum = 0;
            testStartTime = millis();
            Serial.println("Started force test: " + currentTest + " (Test #" + String(testNumber) + ")");
        }
        else if (value == "STOP")
        {
            collectingData = false;
            saveBatchData();
            Serial.println("Stopped data collection");
        }
        else if (value == "RESET")
        {
            sensor.resetFifo();
            Serial.println("FIFO reset");
        }
        else if (value == "SAVE_CSV")
        {
            saveCSVFile();
            Serial.println("CSV file saved");
        }
        else if (value == "CLEAR_DATA")
        {
            csvData = "";
            csvHeaderWritten = false;
            testNumber = 0;
            Serial.println("Data cleared");
        }
    }
};

void setup_sensor()
{
    Serial.print("Initializing MAX30100 sensor... ");
    if (!sensor.begin())
    {
        Serial.println("FAILED");
        while (1)
            ;
    }
    else
    {
        Serial.println("SUCCESS");
    }
    sensor.setMode(MAX30100_MODE_SPO2_HR);
    sensor.setLedsCurrent(MAX30100_LED_CURR_50MA, MAX30100_LED_CURR_50MA);
    sensor.setHighresModeEnabled(true);
    Serial.println("Sensor configured for force testing");
}

void setup_ble()
{
    BLEDevice::init("ESP32_Force_Test");
    bleServer = BLEDevice::createServer();
    bleService = bleServer->createService(forceServiceUUID);

    rawDataChar = bleService->createCharacteristic(
        rawDataCharUUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ);
    rawDataChar->addDescriptor(new BLE2902());

    controlChar = bleService->createCharacteristic(
        controlCharUUID,
        BLECharacteristic::PROPERTY_WRITE);
    controlChar->setCallbacks(new ControlCallbacks());

    bleService->start();

    BLEAdvertising *bleAdv = BLEDevice::getAdvertising();
    bleAdv->addServiceUUID(forceServiceUUID);
    bleAdv->setScanResponse(true);
    BLEDevice::startAdvertising();
    Serial.println("BLE advertising started");
}

void setup_storage()
{
    if (!SPIFFS.begin(true))
    {
        Serial.println("SPIFFS mount failed");
        return;
    }
    Serial.println("SPIFFS mounted successfully");
}

float readForce()
{
    int fsrReading = analogRead(FSR_PIN);
    // Convert ADC reading to voltage (ESP32 ADC is 12-bit, 0-4095)
    float voltage = fsrReading * (3.3 / 4095.0);

    // Convert voltage to approximate force (this is sensor-specific)
    // You may need to calibrate this based on your specific FSR
    float force = 0;
    if (voltage > 0.1)
    { // Threshold to avoid noise
        // Simple linear approximation - calibrate based on your FSR datasheet
        force = voltage * 10; // Approximate force in arbitrary units
    }

    return force;
}

void sendRawData(uint16_t ir, uint16_t red, float force)
{
    char buf[200];
    snprintf(buf, sizeof(buf),
             "{\"ir\":%u,\"red\":%u,\"force\":%.2f,\"test\":\"%s\",\"samples\":%u,\"time_ms\":%lu,\"collecting\":%s}",
             ir, red, force, currentTest.c_str(), sampleCount, millis() - testStartTime, collectingData ? "true" : "false");
    rawDataChar->setValue((uint8_t *)buf, strlen(buf));
    rawDataChar->notify();
}

void saveBatchData()
{
    if (sampleCount > 0)
    {
        float avgIR = (float)irSum / sampleCount;
        float avgRed = (float)redSum / sampleCount;
        float avgForce = (float)forceSum / sampleCount;

        // Add CSV header if not written
        if (!csvHeaderWritten)
        {
            csvData += "TestNumber,TestName,AvgIR,AvgRed,AvgForce,SampleCount,Duration_ms\n";
            csvHeaderWritten = true;
        }

        // Add data row
        csvData += String(testNumber) + "," + currentTest + "," +
                   String(avgIR, 2) + "," + String(avgRed, 2) + "," +
                   String(avgForce, 2) + "," + String(sampleCount) + "," +
                   String(millis() - testStartTime) + "\n";

        // Send average data via BLE
        char buf[200];
        snprintf(buf, sizeof(buf),
                 "{\"type\":\"average\",\"test\":\"%s\",\"test_num\":%d,\"avg_ir\":%.2f,\"avg_red\":%.2f,\"avg_force\":%.2f,\"samples\":%u}",
                 currentTest.c_str(), testNumber, avgIR, avgRed, avgForce, sampleCount);
        rawDataChar->setValue((uint8_t *)buf, strlen(buf));
        rawDataChar->notify();

        Serial.printf("Test %d (%s): IR=%.2f, Red=%.2f, Force=%.2f (samples=%u)\n",
                      testNumber, currentTest.c_str(), avgIR, avgRed, avgForce, sampleCount);
    }
}

void saveCSVFile()
{
    if (csvData.length() > 0)
    {
        File file = SPIFFS.open("/force_test_data.csv", FILE_WRITE);
        if (file)
        {
            file.print(csvData);
            file.close();
            Serial.println("CSV data saved to /force_test_data.csv");

            // Also send via BLE
            char buf[100];
            snprintf(buf, sizeof(buf), "{\"type\":\"csv_saved\",\"size\":%d}", csvData.length());
            rawDataChar->setValue((uint8_t *)buf, strlen(buf));
            rawDataChar->notify();
        }
        else
        {
            Serial.println("Failed to open CSV file for writing");
        }
    }
}

void printCSVData()
{
    if (csvData.length() > 0)
    {
        Serial.println("=== CSV DATA ===");
        Serial.print(csvData);
        Serial.println("=== END CSV DATA ===");
    }
    else
    {
        Serial.println("No CSV data available");
    }
}

void setup()
{
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);

    // Setup FSR pin
    pinMode(FSR_PIN, INPUT);

    setup_storage();
    setup_ble();
    setup_sensor();

    Serial.println("=== Force Test Mode ===");
    Serial.println("Commands:");
    Serial.println("- START:<test_name> - Start data collection");
    Serial.println("- STOP - Stop collection and save batch");
    Serial.println("- SAVE_CSV - Save all data to CSV file");
    Serial.println("- CLEAR_DATA - Clear all collected data");
    Serial.println("- PRINT_CSV - Print CSV data to serial");
    Serial.println("- RESET - Reset sensor FIFO");
}

void loop()
{
    sensor.update();
    uint16_t ir, red;
    float force = readForce();

    if (sensor.getRawValues(&ir, &red))
    {
        if (collectingData)
        {
            irSum += ir;
            redSum += red;
            forceSum += (uint32_t)(force * 100); // Store force * 100 to avoid floating point in sum
            sampleCount++;

            if (sampleCount % SAMPLES_PER_BATCH == 0)
            {
                saveBatchData();
            }
        }

        if (millis() - tsLastReport > REPORTING_PERIOD_MS)
        {
            sendRawData(ir, red, force);
            tsLastReport = millis();
        }
    }

    // Handle serial commands
    if (Serial.available())
    {
        String command = Serial.readStringUntil('\n');
        command.trim();

        if (command.startsWith("START:"))
        {
            currentTest = command.substring(6);
            testNumber++;
            collectingData = true;
            sampleCount = 0;
            irSum = 0;
            redSum = 0;
            forceSum = 0;
            testStartTime = millis();
            Serial.println("Started force test: " + currentTest + " (Test #" + String(testNumber) + ")");
        }
        else if (command == "STOP")
        {
            collectingData = false;
            saveBatchData();
            Serial.println("Stopped data collection");
        }
        else if (command == "SAVE_CSV")
        {
            saveCSVFile();
        }
        else if (command == "CLEAR_DATA")
        {
            csvData = "";
            csvHeaderWritten = false;
            testNumber = 0;
            Serial.println("Data cleared");
        }
        else if (command == "PRINT_CSV")
        {
            printCSVData();
        }
        else if (command == "RESET")
        {
            sensor.resetFifo();
            Serial.println("FIFO reset");
        }
    }

    delay(10);
}