# VitalsTrack Unified Dashboard - Quick Start Guide

## Overview
The VitalsTrack Unified Dashboard provides a comprehensive interface for monitoring and analyzing data from your ESP32-based vital signs sensors. It supports multiple operating modes and real-time data visualization.

## Files Created
- `unified_dashboard.py` - Full-featured dashboard with ML analysis capabilities
- `unified_dashboard_lite.py` - Lightweight version with core functionality only
- `requirements_dashboard.txt` - Dependencies for full version
- `requirements_lite.txt` - Dependencies for lightweight version

## Installation

### Option 1: Lightweight Version (Recommended for most users)
```bash
cd firmware
pip install -r requirements_lite.txt
python unified_dashboard_lite.py
```

### Option 2: Full Version (Advanced users with ML features)
```bash
cd firmware
pip install -r requirements_dashboard.txt
python unified_dashboard.py
```

## Features

### 🎛️ Control Panel
- **Mode Selection**: Choose between HR/SpO2, Temperature, Force Test, Distance Test
- **Connection Management**: Connect/Disconnect from ESP32 devices
- **Recording Control**: Start/Stop data recording with automatic CSV logging
- **Data Management**: Clear data buffers and export data

### 📊 Real-time Monitoring
- **Live Plots**: Four real-time charts showing:
  - Heart Rate & SpO₂ levels
  - Temperature readings
  - Force sensor data
  - 3-axis accelerometer data
- **Current Readings**: Live display of latest sensor values
- **Statistics**: Comprehensive data analysis and statistics

### 💾 Data Logging
- **Automatic CSV Export**: Data automatically saved during recording
- **Manual Export**: Export current buffer data at any time
- **Timestamped Files**: All files include date/time stamps
- **Mode-specific Headers**: CSV columns adapt to current operating mode

## Supported Operating Modes

### 1. HR/SpO₂ Mode (`MODE:HR_SPO2`)
- Monitors heart rate and blood oxygen saturation
- Includes accelerometer data for motion detection
- Real-time cardiovascular analysis

### 2. Temperature Mode (`MODE:TEMPERATURE`)
- Continuous temperature monitoring
- Drift analysis and statistics
- Environmental monitoring

### 3. Force Test Mode (`MODE:FORCE_TEST`)
- Force sensor calibration and testing
- Pressure mapping and analysis
- Multiple test label support

### 4. Distance Test Mode (`MODE:DISTANCE_TEST`)
- Optical distance measurements
- LED wavelength testing (IR, Red, Green, Blue)
- Quantum efficiency analysis

## BLE Connection Details

### Device Discovery
The dashboard automatically scans for ESP32 devices with the name pattern:
- Primary: `ESP32_Unified_Sensor` (recommended)
- Fallback: Mode-specific device names

### Connection Protocol
1. **Service UUID**: `12345678-1234-5678-1234-56789abcdef0`
2. **Characteristics**:
   - Data: `abcdefab-1234-5678-1234-56789abcdef1`
   - Control: `abcdefab-1234-5678-1234-56789abcdef2`
   - Vitals: `abcdefab-1234-5678-1234-56789abcdef3`
   - Quality: `abcdefab-1234-5678-1234-56789abcdef4`

### Mode Commands
The dashboard sends these commands to switch ESP32 modes:
- `MODE:HR_SPO2` - Heart rate and SpO₂ monitoring
- `MODE:TEMPERATURE` - Temperature sensing
- `MODE:FORCE_TEST` - Force sensor testing
- `MODE:DISTANCE_TEST` - Distance/optical testing

## Usage Instructions

### Basic Operation
1. **Start the Dashboard**
   ```bash
   python unified_dashboard_lite.py
   ```

2. **Select Operating Mode**
   - Choose from dropdown: HR/SpO₂, Temperature, Force Test, Distance Test

3. **Connect to ESP32**
   - Click "🔗 Connect" 
   - Dashboard will scan for and connect to your ESP32
   - Status will show "✅ Connected" when successful

4. **Start Recording**
   - Click "▶ Start Recording" to begin data collection
   - Data automatically saves to CSV files in `../test_logs/`
   - Watch real-time plots update

5. **Monitor Data**
   - View live readings in status panel
   - Check real-time plots for trends
   - Monitor sample count and connection status

6. **Stop and Analyze**
   - Click "⏹ Stop Recording" when done
   - Use "📊 Statistics" tab for data analysis
   - Export data with "💾 Export" button

### Advanced Features

#### Data Analysis
- Switch to "📋 Statistics" tab
- Click "🔄 Update Statistics" for latest analysis
- View comprehensive statistics for all sensor types

#### Data Export
- Manual export via "💾 Export" button
- Automatic CSV logging during recording
- Files saved with timestamps in `../test_logs/`

#### Data Management
- "🗑️ Clear Data" to reset all buffers
- Real-time sample counting
- Buffer status monitoring

## Troubleshooting

### Connection Issues
1. **Device Not Found**
   - Ensure ESP32 is powered and running unified firmware
   - Check device name is "ESP32_Unified_Sensor"
   - Verify ESP32 is in BLE advertising mode

2. **Connection Timeout**
   - Move closer to ESP32 (within 10m)
   - Restart ESP32 and try again
   - Check for BLE interference

3. **Mode Switch Failures**
   - Allow 2-3 seconds between mode changes
   - Use "STATUS" command on ESP32 serial monitor
   - Restart ESP32 if stuck in one mode

### Data Issues
1. **No Data Received**
   - Check ESP32 serial monitor for errors
   - Verify sensor connections (I2C, power)
   - Ensure proper sensor initialization

2. **Erratic Readings**
   - Check sensor placement and contact
   - Verify power supply stability
   - Look for loose connections

### Performance Issues
1. **Slow Plot Updates**
   - Reduce plot update frequency in code
   - Close other Bluetooth applications
   - Use lightweight version for better performance

2. **High CPU Usage**
   - Increase data processor sleep time
   - Reduce buffer sizes
   - Close unnecessary applications

## File Outputs

### CSV File Formats

#### HR/SpO₂ Mode
```csv
Timestamp,HeartRate,SpO2,Ax,Ay,Az
2025-07-21T10:30:00.123,72,98,0.1,-0.05,0.98
```

#### Temperature Mode
```csv
Timestamp,Temperature
2025-07-21T10:30:00.123,36.7
```

#### Force Test Mode
```csv
Timestamp,IR,Red,FSR,Label,Device_Timestamp
2025-07-21T10:30:00.123,1024.5,896.2,245,recording,1234567890
```

#### Distance Test Mode
```csv
Timestamp,LED,Distance_mm,IR,Red,Avg_IR,Avg_Red,Samples
2025-07-21T10:30:00.123,ir,10,,,,1024.5,896.2,50
```

## Hardware Requirements
- ESP32 with unified firmware
- MAX30100/MAX30102 sensor (HR/SpO₂)
- Temperature sensor (DS18B20 or similar)
- Force sensor (FSR)
- Accelerometer (ADXL335)
- Stable power supply
- BLE capability enabled

## Software Requirements
- Python 3.7+
- Windows/Linux/macOS with Bluetooth support
- Required Python packages (see requirements files)

## Support
For issues or questions:
1. Check ESP32 serial monitor for debug info
2. Verify hardware connections per hardware guide
3. Ensure firmware matches UNIFIED_SYSTEM_GUIDE.md specifications
4. Check CSV output files for data integrity

## Version History
- v1.0 - Initial unified dashboard release
- Supports all four operating modes
- Real-time plotting and data logging
- Comprehensive statistics and analysis
