
# ESP32 Sensor Project Setup Guide

## Option 1: PlatformIO (Recommended)

1. Install [Visual Studio Code](https://code.visualstudio.com/)
2. Install [PlatformIO Extension](https://platformio.org/install/ide?install=vscode)
3. Clone/download this repository
4. Open VS Code
5. Click "Open Folder" and select the `firmware` folder
6. PlatformIO will automatically:
   - Configure the ESP32 environment
   - Install required dependencies
   - Set up the build system
7. Connect your ESP32 via USB
8. Click the "Upload" button (→) in the PlatformIO toolbar

## Option 2: Arduino IDE

1. Install [Arduino IDE](https://www.arduino.cc/en/software)
2. Install ESP32 board support: (!*Library Manager (recommended), or follow this*!)
   - Go to File → Preferences
   - Add `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json` to Additional Board URLs
   - Go to Tools → Board → Boards Manager
   - Search for "esp32" and install
3. Install required libraries via Library Manager/Board Manager:
   - Wire (built-in)
   - BLEDevice (built-in with ESP32 if board firmware installed)
   - MAX30100lib
   - ADXL335
4. Copy contents of `firmware/src/main.cpp` to a new Arduino sketch
5. Select your ESP32 board from Tools → Board menu
6. Select the correct COM port
7. Click Upload button

## PlatformIO Project Structure

```
firmware/
├── src/
│   └── main.cpp          # Main application code
├── include/
├── lib/                  # Project-specific libraries
└── platformio.ini        # PlatformIO configuration
```

## Mode Selection

- Edit `USE_TEMPERATURE_MODE` in `main.cpp`:
  - Set to `1` for Temperature Mode
  - Set to `0` for HR/SpO2 Mode

## Data logging

Two Python scripts are provided for data logging and visualization:

(Located in `firmware./`)

1. `record_hr_spo2.py` - For heart rate and SpO2 mode:
   - Logs heart rate, SpO2, and accelerometer data
   - Creates live plots of vitals and acceleration
   - Saves data to CSV at `test_logs/oximeter_data.csv`

2. `record_temperature.py` - For temperature mode:
   - Logs temperature readings
   - Creates live plot of temperature
   - Saves data to CSV at `test_logs/temperature_data.csv`

To use:
1. Install required Python packages: `pip install -r requirements.txt`
2. Run the appropriate script based on your mode:
   ```bash
   python firmware/record_hr_spo2.py     # For HR/SpO2 mode
   python firmware/record_temperature.py  # For temperature mode
   ```
3. The script will:
   - Automatically discover and connect to your ESP32
   - Show real-time plots (can be disabled with LIVE_PLOT=False)
   - Save all readings to CSV files

