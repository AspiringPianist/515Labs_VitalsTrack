# ESP32 Project Setup with PlatformIO

This guide explains how to upload testing code for your ESP32 using [PlatformIO](https://platformio.org/), based on the following folder structure:

├───Accelerometer_ADXL335
├───Calibration
├───Distance_Test
├───HRSPO2_TemperatureMode
├───HR_SpO2
├───MAX30100lib
├───ml_inference
├───Pressure_FSR
├───QE_Test
└───Temperature


✅ **Used Libraries Only**:  
We will only use the following folders for testing:
- `Calibration/`
- `Distance_Test/`
- `HRSPO2_TemperatureMode/`
- `HR_SpO2/`
- `Temperature/`
- `QE_Test/`
- `Pressure_FSR/`
- `ml_inference/`

---

## 🚀 Requirements

- [VSCode](https://code.visualstudio.com/)
- [PlatformIO extension](https://platformio.org/install/ide?install=vscode)
- An ESP32 development board
- USB cable

---

## 📁 Folder Structure

Each folder (e.g., `Calibration/`, `Temperature/`) is treated as a *cpp* file that you can copy paste into main.cpp and upload to ESP32 using `Ctrl+Alt+U` via PlatformIO.

| Module/Test           | Folder Name               |
| --------------------- | ------------------------- |
| Temperature           | `Temperature/`            |
| Calibration           | `Calibration/`            |
| Distance (Ultrasonic) | `Distance_Test/`          |
| Heart Rate + SpO2     | `HR_SpO2/`                |
| HR + SpO2 + Temp Mode | `HRSPO2_TemperatureMode/` |
| Pressure via FSR      | `Pressure_FSR/`           |
| QE Sensor             | `QE_Test/`                |
| ML Inference          | `ml_inference/`           |


To clean previous build do 
```
pio run --target clean
```



