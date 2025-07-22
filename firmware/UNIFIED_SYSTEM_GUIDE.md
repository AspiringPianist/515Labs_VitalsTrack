# ESP32 Unified Sensor System

## Overview

This is a modularized ESP32 firmware that combines all sensor functionality into a single codebase. Instead of uploading different firmware for different modes, you can switch between modes via BLE commands at runtime.

## Features

### Supported Modes:
1. **HR_SPO2** - Heart rate and SpO2 monitoring with accelerometer
2. **TEMPERATURE** - Temperature monitoring using MAX30100 sensor
3. **FORCE_TEST** - Force sensor testing with FSR and optical sensors
4. **DISTANCE_TEST** - Distance/quantum efficiency testing
5. **QUALITY** - ML-based sensor quality assessment
6. **RAW_DATA** - Raw sensor data collection
7. **IDLE** - System idle mode

### Key Benefits:
- **Single Upload**: No need to re-flash firmware for different modes
- **Runtime Mode Switching**: Change modes via BLE commands
- **Sensor Conflict Resolution**: Automatically handles MAX30100 vs MAX30100_PulseOximeter conflicts
- **Unified BLE Interface**: Single BLE service with consistent UUID structure
- **Memory Efficient**: Only initializes required sensors per mode

## Hardware Requirements

- ESP32 development board
- MAX30100 pulse oximeter sensor
- ADXL335 accelerometer
- FSR (Force Sensitive Resistor) on pin 35
- Standard I2C connections for sensors

## BLE Interface

### Service UUID: `12345678-1234-5678-1234-56789abcdef0`

### Characteristics:
1. **Data Characteristic** (`abcdefab-1234-5678-1234-56789abcdef1`)
   - Properties: NOTIFY, READ
   - Purpose: Streams sensor data in JSON format

2. **Control Characteristic** (`abcdefab-1234-5678-1234-56789abcdef2`)
   - Properties: WRITE
   - Purpose: Receives control commands

3. **Status Characteristic** (`abcdefab-1234-5678-1234-56789abcdef3`)
   - Properties: NOTIFY, READ
   - Purpose: System status and diagnostics

## Control Commands

### Mode Switching:
```
MODE:HR_SPO2        # Switch to heart rate/SpO2 mode
MODE:TEMPERATURE    # Switch to temperature monitoring
MODE:FORCE_TEST     # Switch to force testing mode
MODE:DISTANCE_TEST  # Switch to distance testing mode
MODE:QUALITY        # Switch to ML quality assessment
MODE:RAW_DATA       # Switch to raw data collection
MODE:IDLE           # Switch to idle mode
```

### Force Test Commands:
```
LABEL:rest          # Start force collection with label "rest"
LABEL:light_press   # Start force collection with label "light_press"
LABEL:firm_press    # Start force collection with label "firm_press"
STOP                # Stop current collection
```

### Distance Test Commands:
```
START:red:10        # Start distance test for red LED at 10mm
START:ir:25         # Start distance test for IR LED at 25mm
START:ambient       # Start ambient light test
STOP                # Stop distance test
RESET               # Reset sensor FIFO
```

### General Commands:
```
STATUS              # Request current system status
```

## Data Formats

All data is transmitted as JSON over the Data Characteristic:

### HR_SPO2 Mode:
```json
{
    "hr": 75.2,
    "spo2": 98.1,
    "ax": 0.12,
    "ay": -0.05,
    "az": 0.98,
    "timestamp": 1234567890
}
```

### Temperature Mode:
```json
{
    "temperature": 36.8,
    "timestamp": 1234567890
}
```

### Force Test Mode:
```json
{
    "ir": 12350,
    "red": 8920,
    "fsr": 2048,
    "label": "light_press",
    "collecting": true,
    "timestamp": 1234567890
}
```

### Distance Test Mode:
```json
{
    "type": "average",
    "led": "red",
    "distance_mm": 10,
    "avg_ir": 15420.5,
    "avg_red": 9876.3,
    "samples": 50,
    "timestamp": 1234567890
}
```

### Quality Assessment Mode:
```json
{
    "hr": 72.8,
    "spo2": 97.5,
    "ax": 0.15,
    "ay": -0.02,
    "az": 0.96,
    "quality": 1,
    "quality_percent": 85.2,
    "accel_mag": 0.97,
    "timestamp": 1234567890
}
```

### Raw Data Mode:
```json
{
    "hr": 74.1,
    "spo2": 98.3,
    "ir": 13250,
    "red": 8750,
    "ax": 0.11,
    "ay": -0.03,
    "az": 0.99,
    "timestamp": 1234567890
}
```

## Usage Examples

### Python Client Example:
```python
import asyncio
from bleak import BleakClient, BleakScanner

# UUIDs
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
DATA_CHAR = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR = "abcdefab-1234-5678-1234-56789abcdef2"
STATUS_CHAR = "abcdefab-1234-5678-1234-56789abcdef3"

async def notification_handler(sender, data):
    print(f"Data: {data.decode('utf-8')}")

async def main():
    # Find and connect to ESP32
    devices = await BleakScanner.discover()
    esp32_device = None
    
    for device in devices:
        if device.name == "ESP32_Unified_Sensor":
            esp32_device = device
            break
    
    if not esp32_device:
        print("ESP32 device not found")
        return
    
    async with BleakClient(esp32_device) as client:
        print(f"Connected to {esp32_device}")
        
        # Subscribe to data notifications
        await client.start_notify(DATA_CHAR, notification_handler)
        
        # Switch to HR/SpO2 mode
        await client.write_gatt_char(CONTROL_CHAR, b"MODE:HR_SPO2")
        await asyncio.sleep(2)
        
        # Switch to force test mode
        await client.write_gatt_char(CONTROL_CHAR, b"MODE:FORCE_TEST")
        await asyncio.sleep(1)
        
        # Start force collection
        await client.write_gatt_char(CONTROL_CHAR, b"LABEL:test_press")
        await asyncio.sleep(10)  # Collect for 10 seconds
        
        # Stop collection
        await client.write_gatt_char(CONTROL_CHAR, b"STOP")
        
        # Keep receiving data
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
```

## Technical Details

### Sensor Initialization Strategy:
The system intelligently initializes sensors based on mode requirements:

- **PulseOximeter class**: Used for HR_SPO2, QUALITY, and RAW_DATA modes
- **MAX30100 raw class**: Used for TEMPERATURE, FORCE_TEST, and DISTANCE_TEST modes
- **Conflict Resolution**: Only one MAX30100 class instance exists at a time

### Memory Management:
- Dynamic sensor allocation/deallocation
- Automatic cleanup when switching modes
- Free heap monitoring

### Timing and Performance:
- Mode-specific reporting periods (100ms to 2000ms)
- Non-blocking sensor updates
- Efficient BLE data transmission

## Troubleshooting

### Common Issues:

1. **Sensor initialization failure**
   - Check I2C connections
   - Verify sensor power supply
   - Try MODE:IDLE then switch back

2. **BLE connection issues**
   - Restart ESP32
   - Clear Bluetooth cache on client device
   - Check device name "ESP32_Unified_Sensor"

3. **Mode switching problems**
   - Allow 2-3 seconds between mode switches
   - Check STATUS command for current mode
   - Verify command format (case-sensitive)

### Debug Information:
- Serial monitor shows detailed status at 115200 baud
- STATUS command provides system diagnostics
- Free heap monitoring for memory issues

## Extending the System

### Adding New Modes:
1. Add new mode to `OperatingMode` enum
2. Add mode name to `switchMode()` function
3. Implement mode-specific data reading in `readSensorData()`
4. Add JSON formatting in `sendData()`

### Adding New Sensors:
1. Include sensor library
2. Add sensor object to global variables
3. Add initialization function
4. Update mode switching logic
5. Add data reading and formatting

## Version Information

- **Version**: 1.0
- **Platform**: ESP32 with PlatformIO
- **Dependencies**: 
  - MAX30100lib
  - ADXL335 library
  - ESP32 BLE libraries
- **Memory Usage**: ~320KB flash, ~45KB RAM (varies by mode)
