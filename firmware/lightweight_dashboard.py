#!/usr/bin/env python3
"""
Professional Research Dashboard for ESP32 Sensor Data
====================================================
Advanced web-based dashboard with export capabilities and robust data handling
"""

import asyncio
import csv
import io
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from bleak import BleakScanner, BleakClient
import numpy as np

# === Configuration ===
BLE_CONFIG = {
    "device_name": "ESP32_Unified_Sensor",
    "service_uuid": "12345678-1234-5678-1234-56789abcdef0",
    "characteristics": {
        "data": "abcdefab-1234-5678-1234-56789abcdef1",
        "control": "abcdefab-1234-5678-1234-56789abcdef2",
        "status": "abcdefab-1234-5678-1234-56789abcdef3",
        "vitals": "abcdefab-1234-5678-1234-56789abcdef3",
        "quality": "abcdefab-1234-5678-1234-56789abcdef4"
    }
}

DATA_CONFIG = {
    "max_buffer_size": 1000,
    "export_formats": ["csv", "json", "matlab"],
    "sampling_rates": {
        "HR_SPO2": 1.0,  # Hz
        "TEMPERATURE": 0.5,
        "RAW_DATA": 10.0,
        "FORCE_TEST": 5.0,
        "QUALITY": 2.0
    }
}

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === Flask App Setup ===
app = Flask(__name__)
app.config['SECRET_KEY'] = 'vitalstrack_research_dashboard_2025'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# === Enhanced Global State ===
class DashboardState:
    def __init__(self):
        # BLE Connection
        self.client = None
        self.connected = False
        self.device_info = {"name": None, "address": None, "rssi": None}
        
        # Operating Mode
        self.current_mode = "IDLE"
        self.mode_history = []
        
        # Data Storage
        max_size = DATA_CONFIG["max_buffer_size"]
        self.data_buffers = {
            'hr': deque(maxlen=max_size),
            'spo2': deque(maxlen=max_size),
            'temperature': deque(maxlen=max_size),
            'force': deque(maxlen=max_size),
            'ir': deque(maxlen=max_size),
            'red': deque(maxlen=max_size),
            'quality': deque(maxlen=max_size),
            'accelerometer': {'x': deque(maxlen=max_size), 'y': deque(maxlen=max_size), 'z': deque(maxlen=max_size)},
            'timestamps': deque(maxlen=max_size)
        }
        
        # Raw data storage for export
        self.raw_data_log = []
        self.max_log_size = 10000
        
        # Statistics
        self.stats = {
            'total_samples': 0,
            'session_start': None,
            'connection_time': None,
            'last_data_time': None,
            'data_rate': 0.0,
            'packet_loss': 0,
            'mode_durations': {}
        }
        
        # Real-time statistics
        self.realtime_stats = {
            'hr': {'min': 0, 'max': 0, 'avg': 0, 'current': 0},
            'spo2': {'min': 0, 'max': 0, 'avg': 0, 'current': 0},
            'temperature': {'min': 0, 'max': 0, 'avg': 0, 'current': 0},
            'quality': {'min': 0, 'max': 0, 'avg': 0, 'current': 0}
        }
        
        # Recording state
        self.recording = False
        self.recording_start_time = None
        
        # BLE Loop
        self.loop = None
        self.ble_task = None
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        
        # Data rate calculation
        self.last_sample_time = None
        self.sample_times = deque(maxlen=10)

state = DashboardState()

# === Enhanced BLE Functions ===
async def scan_for_device():
    """Enhanced device scanning with retry logic"""
    logger.info("🔍 Scanning for ESP32 devices...")
    
    for attempt in range(3):
        try:
            devices = await BleakScanner.discover(timeout=10)
            
            for device in devices:
                if device.name and BLE_CONFIG["device_name"] in device.name:
                    logger.info(f"✅ Found {device.name} at {device.address}")
                    state.device_info = {
                        "name": device.name,
                        "address": device.address,
                        "rssi": device.rssi if hasattr(device, 'rssi') else None
                    }
                    return device
            
            logger.warning(f"Attempt {attempt + 1}/3: ESP32 not found, retrying...")
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Scan attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    
    logger.error("❌ ESP32 not found after 3 attempts")
    return None

async def connect_to_device():
    """Enhanced connection with better error handling"""
    try:
        state.connection_attempts += 1
        device = await scan_for_device()
        if not device:
            return False
        
        logger.info(f"🔗 Connecting to {device.name}...")
        state.client = BleakClient(device.address, timeout=30.0)
        await state.client.connect()
        
        # Verify connection
        if not state.client.is_connected:
            logger.error("❌ Connection verification failed")
            return False
        
        # Setup notifications for all characteristics
        characteristics = BLE_CONFIG["characteristics"]
        
        try:
            await state.client.start_notify(characteristics["data"], handle_data)
            logger.info("✅ Data notifications enabled")
        except Exception as e:
            logger.warning(f"⚠️ Data notifications failed: {e}")
        
        try:
            await state.client.start_notify(characteristics["status"], handle_status)
            logger.info("✅ Status notifications enabled")
        except Exception as e:
            logger.warning(f"⚠️ Status notifications failed: {e}")
        
        # Optional characteristics
        for char_name in ["vitals", "quality"]:
            if char_name in characteristics:
                try:
                    await state.client.start_notify(characteristics[char_name], handle_specialized_data)
                    logger.info(f"✅ {char_name.capitalize()} notifications enabled")
                except Exception:
                    pass  # Optional characteristics
        
        state.connected = True
        state.connection_attempts = 0
        state.stats['connection_time'] = datetime.now()
        state.stats['session_start'] = datetime.now()
        
        # Emit connection status with device info
        socketio.emit('connection_status', {
            'connected': True, 
            'device': state.device_info,
            'connection_time': state.stats['connection_time'].isoformat()
        })
        
        logger.info("🎉 Successfully connected to ESP32!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        state.connected = False
        socketio.emit('connection_status', {'connected': False, 'error': str(e)})
        return False

async def disconnect_device():
    """Enhanced disconnection with cleanup"""
    if state.client and state.connected:
        try:
            # Stop all notifications first
            characteristics = BLE_CONFIG["characteristics"]
            for char_uuid in characteristics.values():
                try:
                    await state.client.stop_notify(char_uuid)
                except Exception:
                    pass  # Ignore errors during cleanup
            
            await state.client.disconnect()
            state.connected = False
            state.device_info = {"name": None, "address": None, "rssi": None}
            
            # Calculate session duration
            if state.stats['connection_time']:
                duration = datetime.now() - state.stats['connection_time']
                logger.info(f"� Session duration: {duration}")
            
            logger.info("�🔌 Disconnected from ESP32")
            socketio.emit('connection_status', {'connected': False})
            
        except Exception as e:
            logger.error(f"❌ Disconnect error: {e}")
            state.connected = False

def handle_data(characteristic, data):
    """Enhanced data handler with statistics"""
    try:
        json_str = data.decode('utf-8')
        data_obj = json.loads(json_str)
        
        current_time = datetime.now()
        timestamp = current_time.timestamp() * 1000  # JS timestamp
        
        # Update statistics
        state.stats['last_data_time'] = current_time
        state.stats['total_samples'] += 1
        
        # Calculate data rate
        if state.last_sample_time:
            time_diff = (current_time - state.last_sample_time).total_seconds()
            state.sample_times.append(time_diff)
            if len(state.sample_times) > 1:
                avg_interval = np.mean(list(state.sample_times))
                state.stats['data_rate'] = 1.0 / avg_interval if avg_interval > 0 else 0
        
        state.last_sample_time = current_time
        
        # Store raw data for export
        if state.recording and len(state.raw_data_log) < state.max_log_size:
            state.raw_data_log.append({
                'timestamp': current_time.isoformat(),
                'mode': state.current_mode,
                'data': data_obj.copy()
            })
        
        # Process and store data based on mode
        process_sensor_data(data_obj, timestamp)
        
        # Emit real-time data
        socketio.emit('sensor_data', {
            'mode': state.current_mode,
            'data': data_obj,
            'timestamp': timestamp,
            'stats': {
                'sample_count': state.stats['total_samples'],
                'data_rate': round(state.stats['data_rate'], 2)
            }
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parsing error: {e}")
        state.stats['packet_loss'] += 1
    except Exception as e:
        logger.error(f"❌ Data processing error: {e}")

def handle_specialized_data(characteristic, data):
    """Handle specialized data from vitals/quality characteristics"""
    try:
        json_str = data.decode('utf-8')
        data_obj = json.loads(json_str)
        
        # Emit specialized data
        socketio.emit('specialized_data', {
            'type': 'vitals' if 'hr' in data_obj else 'quality',
            'data': data_obj,
            'timestamp': datetime.now().timestamp() * 1000
        })
        
    except Exception as e:
        logger.error(f"❌ Specialized data error: {e}")

def process_sensor_data(data_obj, timestamp):
    """Process and store sensor data with statistics calculation"""
    state.data_buffers['timestamps'].append(timestamp)
    
    # Process based on current mode
    if state.current_mode == "HR_SPO2":
        hr = data_obj.get('hr', 0)
        spo2 = data_obj.get('spo2', 0)
        
        if hr > 0:  # Valid reading
            state.data_buffers['hr'].append(hr)
            update_realtime_stats('hr', hr)
        
        if spo2 > 0:  # Valid reading
            state.data_buffers['spo2'].append(spo2)
            update_realtime_stats('spo2', spo2)
    
    elif state.current_mode == "TEMPERATURE":
        temp = data_obj.get('temperature', 0)
        state.data_buffers['temperature'].append(temp)
        update_realtime_stats('temperature', temp)
    
    elif state.current_mode in ["RAW_DATA", "QUALITY"]:
        state.data_buffers['ir'].append(data_obj.get('ir', 0))
        state.data_buffers['red'].append(data_obj.get('red', 0))
        
        if 'quality' in data_obj:
            quality = data_obj['quality']
            state.data_buffers['quality'].append(quality)
            update_realtime_stats('quality', quality)
    
    elif state.current_mode == "FORCE_TEST":
        force = data_obj.get('fsr', 0)
        state.data_buffers['force'].append(force)
    
    # Handle accelerometer data if present
    if 'ax' in data_obj:
        state.data_buffers['accelerometer']['x'].append(data_obj.get('ax', 0))
        state.data_buffers['accelerometer']['y'].append(data_obj.get('ay', 0))
        state.data_buffers['accelerometer']['z'].append(data_obj.get('az', 0))

def update_realtime_stats(metric, value):
    """Update real-time statistics for a metric"""
    if metric not in state.realtime_stats:
        return
    
    stats = state.realtime_stats[metric]
    stats['current'] = value
    
    # Get current buffer for this metric
    buffer = state.data_buffers.get(metric, deque())
    if len(buffer) > 0:
        values = list(buffer)
        stats['min'] = min(values)
        stats['max'] = max(values)
        stats['avg'] = sum(values) / len(values)

def handle_status(characteristic, data):
    """Enhanced status handler"""
    try:
        json_str = data.decode('utf-8')
        status_obj = json.loads(json_str)
        
        # Track mode changes
        if 'mode' in status_obj and status_obj['mode'] != state.current_mode:
            old_mode = state.current_mode
            new_mode = status_obj['mode']
            
            # Record mode change
            mode_change = {
                'from': old_mode,
                'to': new_mode,
                'timestamp': datetime.now().isoformat()
            }
            state.mode_history.append(mode_change)
            state.current_mode = new_mode
            
            logger.info(f"🔄 Mode changed: {old_mode} → {new_mode}")
        
        # Emit enhanced status
        socketio.emit('status_update', {
            **status_obj,
            'realtime_stats': state.realtime_stats,
            'connection_quality': calculate_connection_quality()
        })
        
    except Exception as e:
        logger.error(f"❌ Status parsing error: {e}")

def calculate_connection_quality():
    """Calculate connection quality percentage"""
    if state.stats['total_samples'] == 0:
        return 100
    
    packet_loss_rate = state.stats['packet_loss'] / state.stats['total_samples']
    quality = max(0, 100 - (packet_loss_rate * 100))
    return round(quality, 1)

async def send_mode_command(mode):
    """Enhanced mode command with validation"""
    if not state.connected or not state.client:
        logger.error("❌ Cannot send command: not connected")
        return False
    
    valid_modes = ["IDLE", "HR_SPO2", "TEMPERATURE", "FORCE_TEST", "RAW_DATA", "QUALITY", "DISTANCE_TEST"]
    if mode not in valid_modes:
        logger.error(f"❌ Invalid mode: {mode}")
        return False
    
    try:
        command = f"MODE:{mode}"
        await state.client.write_gatt_char(
            BLE_CONFIG["characteristics"]["control"], 
            command.encode('utf-8')
        )
        logger.info(f"📤 Command sent: {command}")
        
        # Clear buffers when changing modes
        clear_data_buffers()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Command failed: {e}")
        return False

def clear_data_buffers():
    """Clear all data buffers"""
    for key, buffer in state.data_buffers.items():
        if isinstance(buffer, dict):
            for sub_buffer in buffer.values():
                sub_buffer.clear()
        else:
            buffer.clear()
    
    # Reset statistics
    for stats in state.realtime_stats.values():
        stats.update({'min': 0, 'max': 0, 'avg': 0, 'current': 0})

# === Data Export Functions ===
def generate_csv_export():
    """Generate CSV export of all data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    headers = ['timestamp', 'mode']
    
    # Determine all possible data fields
    data_fields = set()
    for entry in state.raw_data_log:
        data_fields.update(entry['data'].keys())
    
    headers.extend(sorted(data_fields))
    writer.writerow(headers)
    
    # Write data rows
    for entry in state.raw_data_log:
        row = [entry['timestamp'], entry['mode']]
        for field in sorted(data_fields):
            row.append(entry['data'].get(field, ''))
        writer.writerow(row)
    
    return output.getvalue()

def generate_json_export():
    """Generate JSON export with metadata"""
    export_data = {
        'metadata': {
            'export_time': datetime.now().isoformat(),
            'session_start': state.stats['session_start'].isoformat() if state.stats['session_start'] else None,
            'total_samples': state.stats['total_samples'],
            'data_rate': state.stats['data_rate'],
            'packet_loss': state.stats['packet_loss'],
            'device_info': state.device_info,
            'mode_history': state.mode_history,
            'dashboard_version': '2.0.0'
        },
        'statistics': {
            'realtime_stats': state.realtime_stats,
            'connection_quality': calculate_connection_quality(),
            'session_duration': str(datetime.now() - state.stats['session_start']) if state.stats['session_start'] else None
        },
        'data': state.raw_data_log,
        'buffer_data': {
            'timestamps': list(state.data_buffers['timestamps']),
            'hr': list(state.data_buffers['hr']),
            'spo2': list(state.data_buffers['spo2']),
            'temperature': list(state.data_buffers['temperature']),
            'force': list(state.data_buffers['force']),
            'ir': list(state.data_buffers['ir']),
            'red': list(state.data_buffers['red']),
            'quality': list(state.data_buffers['quality'])
        }
    }
    
    return json.dumps(export_data, indent=2)

def generate_matlab_export():
    """Generate MATLAB-compatible data export"""
    output = io.StringIO()
    
    # MATLAB header
    output.write(f'%% VitalsTrack Data Export - Generated {datetime.now().isoformat()}\n')
    output.write(f'%% Total Samples: {state.stats["total_samples"]}\n')
    output.write(f'%% Data Rate: {state.stats["data_rate"]:.2f} Hz\n\n')
    
    # Create structure
    output.write('vitals_data = struct();\n\n')
    
    # Metadata
    output.write('% Metadata\n')
    output.write(f'vitals_data.total_samples = {state.stats["total_samples"]};\n')
    output.write(f'vitals_data.data_rate = {state.stats["data_rate"]:.2f};\n')
    output.write(f'vitals_data.packet_loss = {state.stats["packet_loss"]};\n\n')
    
    # Export buffer data
    buffer_data = {
        'timestamps': list(state.data_buffers['timestamps']),
        'hr': list(state.data_buffers['hr']),
        'spo2': list(state.data_buffers['spo2']),
        'temperature': list(state.data_buffers['temperature']),
        'force': list(state.data_buffers['force']),
        'ir': list(state.data_buffers['ir']),
        'red': list(state.data_buffers['red']),
        'quality': list(state.data_buffers['quality'])
    }
    
    for field_name, data_list in buffer_data.items():
        if data_list:
            output.write(f'% {field_name.upper()} Data\n')
            output.write(f'vitals_data.{field_name} = [')
            output.write(', '.join(map(str, data_list)))
            output.write('];\n\n')
    
    # Statistics
    output.write('% Statistics\n')
    for metric, stats in state.realtime_stats.items():
        if any(stats.values()):
            output.write(f'vitals_data.{metric}_stats.min = {stats["min"]};\n')
            output.write(f'vitals_data.{metric}_stats.max = {stats["max"]};\n')
            output.write(f'vitals_data.{metric}_stats.avg = {stats["avg"]:.2f};\n')
            output.write(f'vitals_data.{metric}_stats.current = {stats["current"]};\n\n')
    
    return output.getvalue()

# === BLE Event Loop ===
def run_ble_loop():
    """Run BLE operations in separate thread with error handling"""
    try:
        state.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(state.loop)
        logger.info("🔄 BLE event loop started")
        state.loop.run_forever()
    except Exception as e:
        logger.error(f"❌ BLE loop error: {e}")
    finally:
        logger.info("🔄 BLE event loop stopped")

# === Enhanced Flask Routes ===
@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to ESP32 with enhanced error handling"""
    if state.connected:
        return jsonify({'success': True, 'message': 'Already connected'})
    
    if not state.loop:
        return jsonify({'success': False, 'error': 'BLE loop not running'})

    if state.connection_attempts >= state.max_connection_attempts:
        logger.warning("Max connection attempts reached. Resetting count.")
        state.connection_attempts = 0

    asyncio.run_coroutine_threadsafe(connect_to_device(), state.loop)
    
    return jsonify({'success': True, 'message': 'Connection process started. Check status panel.'})

@app.route('/api/disconnect', methods=['POST'])
def api_disconnect():
    """Disconnect from ESP32"""
    if not state.connected:
        return jsonify({'success': True, 'message': 'Already disconnected'})
    
    if state.loop:
        try:
            future = asyncio.run_coroutine_threadsafe(disconnect_device(), state.loop)
            future.result(timeout=10)
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"❌ API disconnect error: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    return jsonify({'success': True})

@app.route('/api/mode', methods=['POST'])
def api_change_mode():
    """Change sensor mode with validation"""
    data = request.get_json()
    if not data or 'mode' not in data:
        return jsonify({'success': False, 'error': 'No mode specified'})
    
    mode = data['mode']
    
    if not state.connected and mode != 'IDLE':
        return jsonify({'success': False, 'error': 'Not connected to device'})
    
    if state.loop:
        try:
            future = asyncio.run_coroutine_threadsafe(send_mode_command(mode), state.loop)
            result = future.result(timeout=10)
            
            if result:
                state.current_mode = mode
                logger.info(f"✅ API: Mode changed to {mode}")
                
                # Emit mode update to all clients
                socketio.emit('mode_update', {'mode': mode})
            
            return jsonify({'success': result})
            
        except Exception as e:
            logger.error(f"❌ API mode change error: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    return jsonify({'success': False, 'error': 'BLE loop not available'})

@app.route('/api/status')
def api_status():
    """Get comprehensive system status"""
    session_duration = None
    if state.stats['session_start']:
        session_duration = str(datetime.now() - state.stats['session_start'])
    
    return jsonify({
        'connected': state.connected,
        'mode': state.current_mode,
        'device_info': state.device_info,
        'stats': {
            **state.stats,
            'session_duration': session_duration,
            'connection_quality': calculate_connection_quality(),
            'buffer_sizes': {k: len(v) if not isinstance(v, dict) else {sk: len(sv) for sk, sv in v.items()} 
                           for k, v in state.data_buffers.items()}
        },
        'realtime_stats': state.realtime_stats,
        'recording': state.recording,
        'mode_history': state.mode_history[-10:],  # Last 10 mode changes
        'system_info': {
            'version': '2.0.0',
            'uptime': session_duration,
            'max_buffer_size': DATA_CONFIG['max_buffer_size']
        }
    })

@app.route('/api/data')
def api_get_data():
    """Get current data buffers"""
    return jsonify({
        'timestamps': list(state.data_buffers['timestamps']),
        'data': {
            'hr': list(state.data_buffers['hr']),
            'spo2': list(state.data_buffers['spo2']),
            'temperature': list(state.data_buffers['temperature']),
            'force': list(state.data_buffers['force']),
            'ir': list(state.data_buffers['ir']),
            'red': list(state.data_buffers['red']),
            'quality': list(state.data_buffers['quality']),
            'accelerometer': {
                'x': list(state.data_buffers['accelerometer']['x']),
                'y': list(state.data_buffers['accelerometer']['y']),
                'z': list(state.data_buffers['accelerometer']['z'])
            }
        },
        'mode': state.current_mode,
        'stats': state.realtime_stats
    })

@app.route('/api/recording', methods=['POST'])
def api_toggle_recording():
    """Toggle data recording"""
    data = request.get_json()
    action = data.get('action', 'toggle') if data else 'toggle'
    
    if action == 'start' or (action == 'toggle' and not state.recording):
        state.recording = True
        state.recording_start_time = datetime.now()
        state.raw_data_log = []  # Clear previous recording
        message = 'Recording started'
        logger.info("🔴 Recording started")
        
    elif action == 'stop' or (action == 'toggle' and state.recording):
        state.recording = False
        duration = datetime.now() - state.recording_start_time if state.recording_start_time else timedelta(0)
        message = f'Recording stopped (Duration: {duration})'
        logger.info("⏹️ Recording stopped")
        
    else:
        message = 'Recording state unchanged'
    
    return jsonify({
        'success': True,
        'recording': state.recording,
        'message': message,
        'recorded_samples': len(state.raw_data_log)
    })

@app.route('/api/clear', methods=['POST'])
def api_clear_data():
    """Clear all data buffers"""
    clear_data_buffers()
    state.stats['total_samples'] = 0
    state.raw_data_log = []
    
    socketio.emit('data_cleared', {'timestamp': datetime.now().isoformat()})
    logger.info("🗑️ All data cleared")
    
    return jsonify({'success': True, 'message': 'Data cleared'})

@app.route('/api/export/<format>')
def api_export_data(format):
    """Export data in specified format"""
    if not state.raw_data_log and sum(len(buffer) for buffer in state.data_buffers.values() if isinstance(buffer, deque)) == 0:
        return jsonify({'success': False, 'error': 'No data to export'})
    
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if format == 'csv':
            content = generate_csv_export()
            filename = f'vitals_data_{timestamp}.csv'
            mimetype = 'text/csv'
            
        elif format == 'json':
            content = generate_json_export()
            filename = f'vitals_data_{timestamp}.json'
            mimetype = 'application/json'
            
        elif format == 'matlab':
            content = generate_matlab_export()
            filename = f'vitals_data_{timestamp}.m'
            mimetype = 'text/plain'
            
        else:
            return jsonify({'success': False, 'error': 'Unsupported format'})
        
        # Create file-like object
        output = io.BytesIO()
        output.write(content.encode('utf-8'))
        output.seek(0)
        
        logger.info(f"📥 Data exported as {format.upper()} ({filename})")
        
        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"❌ Export error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'ble_connected': state.connected,
        'total_samples': state.stats['total_samples']
    })

# === Enhanced SocketIO Events ===
@socketio.on('connect')
def handle_connect(auth):
    """Handle client connection"""
    logger.info("🌐 Web client connected")
    
    # Send current state to new client
    emit('connection_status', {
        'connected': state.connected,
        'device': state.device_info if state.connected else None
    })
    emit('mode_update', {'mode': state.current_mode})
    
    # Convert datetime objects to ISO strings for JSON serialization
    system_stats = state.stats.copy()
    if system_stats.get('session_start'):
        system_stats['session_start'] = system_stats['session_start'].isoformat()
    if system_stats.get('connection_time'):
        system_stats['connection_time'] = system_stats['connection_time'].isoformat()
    if system_stats.get('last_data_time'):
        system_stats['last_data_time'] = system_stats['last_data_time'].isoformat()
    
    emit('stats_update', {
        'realtime_stats': state.realtime_stats,
        'system_stats': system_stats
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info("🌐 Web client disconnected")

@socketio.on('toggle_recording')
def handle_toggle_recording():
    """Toggle recording state from client"""
    action = 'start' if not state.recording else 'stop'
    
    if action == 'start':
        state.recording = True
        state.recording_start_time = datetime.now()
        state.raw_data_log = []  # Clear previous recording
        message = 'Recording started'
        logger.info("🔴 Recording started")
    else: # stop
        state.recording = False
        duration = datetime.now() - state.recording_start_time if state.recording_start_time else timedelta(0)
        message = f'Recording stopped (Duration: {duration})'
        logger.info("⏹️ Recording stopped")

    status = {
        'recording': state.recording,
        'message': message
    }
    emit('recording_status', status, broadcast=True)


@socketio.on('toggle_recording')
def handle_toggle_recording():
    """Toggle recording state from client"""
    action = 'start' if not state.recording else 'stop'
    
    if action == 'start':
        state.recording = True
        state.recording_start_time = datetime.now()
        state.raw_data_log = []  # Clear previous recording
        message = 'Recording started'
        logger.info("🔴 Recording started")
    else: # stop
        state.recording = False
        duration = datetime.now() - state.recording_start_time if state.recording_start_time else timedelta(0)
        message = f'Recording stopped (Duration: {duration})'
        logger.info("⏹️ Recording stopped")

    status = {
        'recording': state.recording,
        'message': message
    }
    emit('recording_status', status, broadcast=True)


@socketio.on('request_data')
def handle_data_request():
    """Handle client data request"""
    emit('data_update', {
        'timestamps': list(state.data_buffers['timestamps']),
        'data': {
            'hr': list(state.data_buffers['hr']),
            'spo2': list(state.data_buffers['spo2']),
            'temperature': list(state.data_buffers['temperature']),
            'force': list(state.data_buffers['force']),
            'ir': list(state.data_buffers['ir']),
            'red': list(state.data_buffers['red']),
            'quality': list(state.data_buffers['quality'])
        }
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# === Enhanced Main Function ===
def main():
    """Enhanced main function with proper startup sequence"""
    logger.info("🚀 Starting VitalsTrack Research Dashboard v2.0")
    logger.info("=" * 50)
    
    # Startup information
    logger.info("📱 Web interface: http://localhost:5000")
    logger.info("🔧 API endpoints: http://localhost:5000/api/")
    logger.info("📊 Dashboard features:")
    logger.info("   • Real-time sensor monitoring")
    logger.info("   • Data export (CSV, JSON, MATLAB)")
    logger.info("   • Statistics tracking")
    logger.info("   • Session recording")
    logger.info("   • Professional research-grade UI")
    
    # Initialize session
    state.stats['session_start'] = datetime.now()
    
    # Start BLE event loop in separate thread
    logger.info("🔄 Starting BLE event loop...")
    ble_thread = threading.Thread(target=run_ble_loop, daemon=True)
    ble_thread.start()
    
    # Wait for loop to initialize
    time.sleep(1)
    
    if not state.loop:
        logger.error("❌ Failed to start BLE event loop")
        return
    
    logger.info("✅ BLE event loop started successfully")
    
    try:
        # Start Flask app with production settings
        logger.info("🌐 Starting web server...")
        socketio.run(
            app, 
            host='0.0.0.0', 
            port=5000, 
            debug=False,
            use_reloader=False,  # Disable reloader in production
            log_output=False     # Use our custom logging
        )
        
    except KeyboardInterrupt:
        logger.info("\n👋 Shutdown requested by user")
        
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up...")
        
        # Disconnect BLE if connected
        if state.connected and state.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(disconnect_device(), state.loop)
                future.result(timeout=5)
            except Exception as e:
                logger.error(f"❌ Cleanup disconnect error: {e}")
        
        # Stop BLE loop
        if state.loop:
            try:
                state.loop.call_soon_threadsafe(state.loop.stop)
            except Exception as e:
                logger.error(f"❌ Loop cleanup error: {e}")
        
        # Export final session data if recording
        if state.recording and state.raw_data_log:
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'session_data_{timestamp}.json'
                
                with open(filename, 'w') as f:
                    f.write(generate_json_export())
                    
                logger.info(f"💾 Session data saved to {filename}")
                
            except Exception as e:
                logger.error(f"❌ Final export error: {e}")
        
        # Final statistics
        if state.stats['session_start']:
            session_duration = datetime.now() - state.stats['session_start']
            logger.info(f"📊 Session Statistics:")
            logger.info(f"   • Duration: {session_duration}")
            logger.info(f"   • Total Samples: {state.stats['total_samples']}")
            logger.info(f"   • Average Data Rate: {state.stats['data_rate']:.2f} Hz")
            logger.info(f"   • Packet Loss: {state.stats['packet_loss']}")
            logger.info(f"   • Connection Quality: {calculate_connection_quality():.1f}%")
        
        logger.info("✅ Dashboard shutdown complete")

if __name__ == "__main__":
    main()
