# ESP32 Unified Sensor System - Quick Reference

## BLE Connection Details
- **Device Name**: `ESP32_Unified_Sensor`
- **Service UUID**: `12345678-1234-5678-1234-56789abcdef0`
- **Data Characteristic**: `abcdefab-1234-5678-1234-56789abcdef1` (NOTIFY)
- **Control Characteristic**: `abcdefab-1234-5678-1234-56789abcdef2` (WRITE)
- **Status Characteristic**: `abcdefab-1234-5678-1234-56789abcdef3` (NOTIFY)

## Mode Switching Commands

| Command | Description | Sensors Used | Reporting Rate |
|---------|-------------|--------------|----------------|
| `MODE:IDLE` | System idle mode | None | 2000ms |
| `MODE:HR_SPO2` | Heart rate & SpO2 monitoring | PulseOximeter + ADXL335 | 500ms |
| `MODE:TEMPERATURE` | Temperature monitoring | MAX30100 (raw) | 2000ms |
| `MODE:FORCE_TEST` | Force sensor testing | MAX30100 (raw) + FSR | 100ms |
| `MODE:DISTANCE_TEST` | Distance/QE testing | MAX30100 (raw) | 100ms |
| `MODE:QUALITY` | ML quality assessment | PulseOximeter + ADXL335 | 1000ms |
| `MODE:RAW_DATA` | Raw sensor data | PulseOximeter + MAX30100 (raw) | 500ms |

## Control Commands

### General Commands
| Command | Purpose |
|---------|---------|
| `STATUS` | Get system status |
| `STOP` | Stop current data collection |
| `RESET` | Reset sensor FIFO |

### Force Test Commands (MODE:FORCE_TEST)
| Command | Purpose |
|---------|---------|
| `LABEL:rest` | Start collection with "rest" label |
| `LABEL:light_press` | Start collection with "light_press" label |
| `LABEL:firm_press` | Start collection with "firm_press" label |
| `LABEL:max_force` | Start collection with "max_force" label |
| `LABEL:custom_name` | Start collection with custom label |

### Distance Test Commands (MODE:DISTANCE_TEST)  
| Command | Purpose |
|---------|---------|
| `START:red:10` | Start red LED test at 10mm distance |
| `START:ir:25` | Start IR LED test at 25mm distance |
| `START:ambient` | Start ambient light test |
| `START:red` | Start red LED test (distance = 0) |

## Data Output Examples

### HR_SPO2 Mode
```json
{"hr":75.2,"spo2":98.1,"ax":0.12,"ay":-0.05,"az":0.98,"timestamp":1234567}
```

### Temperature Mode  
```json
{"temperature":36.8,"timestamp":1234567}
```

### Force Test Mode
```json
{"ir":12350,"red":8920,"fsr":2048,"label":"light_press","collecting":true,"timestamp":1234567}
```

### Distance Test Mode
```json
{"type":"average","led":"red","distance_mm":10,"avg_ir":15420.5,"avg_red":9876.3,"samples":50,"timestamp":1234567}
```

### Quality Mode
```json
{"hr":72.8,"spo2":97.5,"ax":0.15,"ay":-0.02,"az":0.96,"quality":1,"quality_percent":85.2,"accel_mag":0.97,"timestamp":1234567}
```

## Hardware Connections

### I2C Sensors (SDA=21, SCL=22)
- MAX30100 pulse oximeter
- ADXL335 accelerometer

### Analog Sensors
- FSR (Force Sensitive Resistor) → Pin 35

### Power Requirements
- 3.3V for sensors
- USB/5V for ESP32

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| Can't find BLE device | Check ESP32 is powered and running |
| Sensor init failed | Check I2C wiring (SDA=21, SCL=22) |
| No data received | Send `STATUS` command to check mode |
| Wrong sensor readings | Try `RESET` command then restart mode |
| Mode won't switch | Wait 2-3 seconds between mode changes |
| Memory errors | Check Serial monitor for heap info |

## Serial Monitor Debug (115200 baud)
- Shows detailed status and errors
- Displays BLE connection events  
- Reports sensor initialization results
- Memory usage information

## Python Test Client
Run `python esp32_test_client.py` for interactive testing and demos.
