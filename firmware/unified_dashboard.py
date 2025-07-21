"""
ESP32 VitalsTrack Unified Dashboard
===================================
A comprehensive dashboard for monitoring and analyzing vitals data from ESP32 sensors.
Supports multiple modes: HR/SpO2, Temperature, Force Testing, Distance Testing, and ML Model Analysis.
"""

import asyncio
import csv
import datetime
import json
import queue
import threading
import time
import warnings
from collections import deque, defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import numpy as np
from bleak import BleakScanner, BleakClient
from scipy import signal
from scipy.stats import pearsonr
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

warnings.filterwarnings('ignore')

# === BLE Configuration ===
BLE_CONFIG = {
    "devices": {
        "hr_spo2": "ESP32_Sensor",
        "temperature": "ESP32_Temperature", 
        "force": "ESP32_FSR_Collector",
        "distance": "ESP32_Distance_Test",
        "quality": "ESP32_Quality_Monitor",
        "raw": "ESP32_Raw_Collector",
        "unified": "ESP32_Unified_Sensor"
    },
    "service_uuid": "12345678-1234-5678-1234-56789abcdef0",
    "characteristics": {
        "raw_data": "abcdefab-1234-5678-1234-56789abcdef1",
        "control": "abcdefab-1234-5678-1234-56789abcdef2", 
        "vitals_data": "abcdefab-1234-5678-1234-56789abcdef3",
        "quality": "abcdefab-1234-5678-1234-56789abcdef4"
    }
}

class UnifiedDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("VitalsTrack Unified Dashboard v1.0")
        self.root.geometry("1400x900")
        self.root.configure(bg='#2c3e50')
        
        # Data storage
        self.data_queues = {
            'hr_spo2': queue.Queue(),
            'temperature': queue.Queue(),
            'force': queue.Queue(),
            'distance': queue.Queue(),
            'ml_model': queue.Queue()
        }
        
        # Connection status
        self.ble_clients = {}
        self.connection_status = {}
        self.current_mode = "idle"
        
        # Data buffers
        self.data_buffers = {
            'hr': deque(maxlen=100),
            'spo2': deque(maxlen=100),
            'temperature': deque(maxlen=100),
            'force': deque(maxlen=100),
            'accel_x': deque(maxlen=100),
            'accel_y': deque(maxlen=100),
            'accel_z': deque(maxlen=100),
            'timestamps': deque(maxlen=100)
        }
        
        # CSV writers
        self.csv_writers = {}
        self.csv_files = {}
        
        # Initialize GUI
        self.setup_gui()
        self.setup_plots()
        
        # Start background threads
        self.data_processor_running = True
        self.data_thread = threading.Thread(target=self.data_processor, daemon=True)
        self.data_thread.start()
        
    def setup_gui(self):
        """Setup the main GUI interface"""
        # Create main frame
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = tk.Label(main_frame, text="VitalsTrack Unified Dashboard", 
                              font=('Arial', 24, 'bold'), fg='#ecf0f1', bg='#2c3e50')
        title_label.pack(pady=(0, 20))
        
        # Control Panel
        self.setup_control_panel(main_frame)
        
        # Status Panel
        self.setup_status_panel(main_frame)
        
        # Data Display Panel
        self.setup_data_panel(main_frame)
        
    def setup_control_panel(self, parent):
        """Setup control buttons and mode selection"""
        control_frame = tk.LabelFrame(parent, text="Control Panel", font=('Arial', 14, 'bold'),
                                     fg='#ecf0f1', bg='#34495e', bd=2)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Mode Selection
        mode_frame = tk.Frame(control_frame, bg='#34495e')
        mode_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(mode_frame, text="Operating Mode:", font=('Arial', 12, 'bold'),
                fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT)
        
        self.mode_var = tk.StringVar(value="hr_spo2")
        mode_combo = ttk.Combobox(mode_frame, textvariable=self.mode_var, 
                                 values=["hr_spo2", "temperature", "force_test", "distance_test", "ml_model"],
                                 state="readonly", font=('Arial', 11))
        mode_combo.pack(side=tk.LEFT, padx=(10, 20))
        mode_combo.bind('<<ComboboxSelected>>', self.on_mode_change)
        
        # Connection buttons
        btn_frame = tk.Frame(control_frame, bg='#34495e')
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.connect_btn = tk.Button(btn_frame, text="🔗 Connect", command=self.connect_device,
                                   bg='#27ae60', fg='white', font=('Arial', 11, 'bold'),
                                   relief=tk.FLAT, padx=20)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.disconnect_btn = tk.Button(btn_frame, text="⚡ Disconnect", command=self.disconnect_device,
                                      bg='#e74c3c', fg='white', font=('Arial', 11, 'bold'),
                                      relief=tk.FLAT, padx=20, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.start_btn = tk.Button(btn_frame, text="▶ Start Recording", command=self.start_recording,
                                 bg='#3498db', fg='white', font=('Arial', 11, 'bold'),
                                 relief=tk.FLAT, padx=20, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_btn = tk.Button(btn_frame, text="⏹ Stop Recording", command=self.stop_recording,
                                bg='#f39c12', fg='white', font=('Arial', 11, 'bold'),
                                relief=tk.FLAT, padx=20, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.analyze_btn = tk.Button(btn_frame, text="📊 Analyze Data", command=self.analyze_data,
                                   bg='#9b59b6', fg='white', font=('Arial', 11, 'bold'),
                                   relief=tk.FLAT, padx=20)
        self.analyze_btn.pack(side=tk.LEFT, padx=(0, 10))
        
    def setup_status_panel(self, parent):
        """Setup status display panel"""
        status_frame = tk.LabelFrame(parent, text="System Status", font=('Arial', 14, 'bold'),
                                   fg='#ecf0f1', bg='#34495e', bd=2)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status grid
        status_grid = tk.Frame(status_frame, bg='#34495e')
        status_grid.pack(fill=tk.X, padx=10, pady=10)
        
        # Connection status
        tk.Label(status_grid, text="Connection:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.connection_label = tk.Label(status_grid, text="❌ Disconnected", font=('Arial', 11),
                                       fg='#e74c3c', bg='#34495e')
        self.connection_label.grid(row=0, column=1, sticky=tk.W, padx=(0, 30))
        
        # Current mode
        tk.Label(status_grid, text="Mode:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        self.mode_label = tk.Label(status_grid, text="HR/SpO₂", font=('Arial', 11),
                                 fg='#3498db', bg='#34495e')
        self.mode_label.grid(row=0, column=3, sticky=tk.W, padx=(0, 30))
        
        # Data count
        tk.Label(status_grid, text="Samples:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=4, sticky=tk.W, padx=(0, 10))
        self.sample_label = tk.Label(status_grid, text="0", font=('Arial', 11),
                                   fg='#f39c12', bg='#34495e')
        self.sample_label.grid(row=0, column=5, sticky=tk.W)
        
        # Current readings
        readings_frame = tk.Frame(status_frame, bg='#34495e')
        readings_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.readings_labels = {}
        readings = ['HR: --', 'SpO₂: --%', 'Temp: --°C', 'Force: --', 'Accel: --']
        for i, reading in enumerate(readings):
            label = tk.Label(readings_frame, text=reading, font=('Arial', 12, 'bold'),
                           fg='#2ecc71', bg='#34495e')
            label.pack(side=tk.LEFT, padx=(0, 20))
            self.readings_labels[reading.split(':')[0].lower()] = label
            
    def setup_data_panel(self, parent):
        """Setup data display and plotting panel"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Real-time plots tab
        self.plots_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.plots_frame, text="📈 Real-time Plots")
        
        # Data table tab
        self.table_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.table_frame, text="📋 Data Table")
        
        # Analysis tab
        self.analysis_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.analysis_frame, text="🔬 Analysis")
        
        # Settings tab
        self.settings_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.settings_frame, text="⚙️ Settings")
        
        self.setup_settings_tab()
        
    def setup_plots(self):
        """Setup matplotlib plots"""
        self.fig, self.axes = plt.subplots(2, 2, figsize=(12, 8))
        self.fig.patch.set_facecolor('#ecf0f1')
        self.fig.suptitle('VitalsTrack Real-time Data', fontsize=16, fontweight='bold')
        
        # HR/SpO2 plot
        self.axes[0, 0].set_title('Heart Rate & SpO₂', fontweight='bold')
        self.axes[0, 0].set_ylabel('HR (bpm) / SpO₂ (%)')
        self.axes[0, 0].grid(True, alpha=0.3)
        self.hr_line, = self.axes[0, 0].plot([], [], 'r-', label='HR', linewidth=2)
        self.spo2_line, = self.axes[0, 0].plot([], [], 'b-', label='SpO₂', linewidth=2)
        self.axes[0, 0].legend()
        
        # Temperature plot
        self.axes[0, 1].set_title('Temperature', fontweight='bold')
        self.axes[0, 1].set_ylabel('Temperature (°C)')
        self.axes[0, 1].grid(True, alpha=0.3)
        self.temp_line, = self.axes[0, 1].plot([], [], 'g-', linewidth=2)
        
        # Force/Pressure plot
        self.axes[1, 0].set_title('Force Sensor', fontweight='bold')
        self.axes[1, 0].set_ylabel('Force (ADC)')
        self.axes[1, 0].grid(True, alpha=0.3)
        self.force_line, = self.axes[1, 0].plot([], [], 'm-', linewidth=2)
        
        # Accelerometer plot
        self.axes[1, 1].set_title('Accelerometer', fontweight='bold')
        self.axes[1, 1].set_ylabel('Acceleration (g)')
        self.axes[1, 1].grid(True, alpha=0.3)
        self.accel_x_line, = self.axes[1, 1].plot([], [], 'r-', label='X', linewidth=2)
        self.accel_y_line, = self.axes[1, 1].plot([], [], 'g-', label='Y', linewidth=2)
        self.accel_z_line, = self.axes[1, 1].plot([], [], 'b-', label='Z', linewidth=2)
        self.axes[1, 1].legend()
        
        plt.tight_layout()
        
        # Embed plot in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, self.plots_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Start animation
        self.ani = animation.FuncAnimation(self.fig, self.update_plots, interval=100, blit=False)
        
    def setup_settings_tab(self):
        """Setup settings and configuration tab"""
        settings_scroll = tk.Frame(self.settings_frame, bg='#ecf0f1')
        settings_scroll.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Data export settings
        export_frame = tk.LabelFrame(settings_scroll, text="Data Export", font=('Arial', 12, 'bold'),
                                   bg='#ecf0f1', bd=2)
        export_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.auto_save_var = tk.BooleanVar(value=True)
        tk.Checkbutton(export_frame, text="Auto-save data to CSV", variable=self.auto_save_var,
                      font=('Arial', 11), bg='#ecf0f1').pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Button(export_frame, text="📁 Choose Export Directory", command=self.choose_export_dir,
                 font=('Arial', 11), bg='#3498db', fg='white', relief=tk.FLAT, padx=20).pack(pady=10)
        
        self.export_dir_label = tk.Label(export_frame, text="Export Dir: ../test_logs/", 
                                       font=('Arial', 10), bg='#ecf0f1', fg='#7f8c8d')
        self.export_dir_label.pack(pady=5)
        
        # Device settings
        device_frame = tk.LabelFrame(settings_scroll, text="Device Settings", font=('Arial', 12, 'bold'),
                                   bg='#ecf0f1', bd=2)
        device_frame.pack(fill=tk.X, pady=(0, 20))
        
        tk.Label(device_frame, text="Scan Timeout (seconds):", font=('Arial', 11),
                bg='#ecf0f1').grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        self.scan_timeout_var = tk.IntVar(value=15)
        tk.Spinbox(device_frame, from_=5, to=60, textvariable=self.scan_timeout_var,
                  font=('Arial', 11), width=10).grid(row=0, column=1, padx=10, pady=5)
        
        # Analysis settings  
        analysis_frame = tk.LabelFrame(settings_scroll, text="Analysis Settings", font=('Arial', 12, 'bold'),
                                     bg='#ecf0f1', bd=2)
        analysis_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.enable_filtering_var = tk.BooleanVar(value=True)
        tk.Checkbutton(analysis_frame, text="Enable signal filtering", variable=self.enable_filtering_var,
                      font=('Arial', 11), bg='#ecf0f1').pack(anchor=tk.W, padx=10, pady=5)
        
        self.enable_ml_var = tk.BooleanVar(value=False)
        tk.Checkbutton(analysis_frame, text="Enable ML quality assessment", variable=self.enable_ml_var,
                      font=('Arial', 11), bg='#ecf0f1').pack(anchor=tk.W, padx=10, pady=5)
        
    def on_mode_change(self, event=None):
        """Handle mode selection change"""
        new_mode = self.mode_var.get()
        mode_names = {
            "hr_spo2": "HR/SpO₂",
            "temperature": "Temperature",
            "force_test": "Force Test", 
            "distance_test": "Distance Test",
            "ml_model": "ML Model"
        }
        self.mode_label.config(text=mode_names.get(new_mode, new_mode))
        self.current_mode = new_mode
        
    def connect_device(self):
        """Connect to ESP32 device based on current mode"""
        mode = self.mode_var.get()
        device_name = self.get_device_name(mode)
        
        self.connection_label.config(text="🔄 Connecting...", fg='#f39c12')
        self.connect_btn.config(state=tk.DISABLED)
        
        # Run connection in background thread
        threading.Thread(target=self.ble_connect_worker, args=(device_name, mode), daemon=True).start()
        
    def get_device_name(self, mode):
        """Get appropriate device name for mode"""
        device_map = {
            "hr_spo2": "unified",
            "temperature": "unified", 
            "force_test": "unified",
            "distance_test": "unified",
            "ml_model": "unified"
        }
        device_key = device_map.get(mode, "unified")
        return BLE_CONFIG["devices"][device_key]
        
    def ble_connect_worker(self, device_name, mode):
        """BLE connection worker thread"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run connection
            success = loop.run_until_complete(self.async_connect(device_name, mode))
            
            if success:
                self.root.after(0, self.on_connect_success, mode)
            else:
                self.root.after(0, self.on_connect_failure)
                
        except Exception as e:
            print(f"Connection error: {e}")
            self.root.after(0, self.on_connect_failure)
        finally:
            loop.close()
            
    async def async_connect(self, device_name, mode):
        """Async BLE connection"""
        try:
            print(f"🔍 Scanning for {device_name}...")
            devices = await BleakScanner.discover(timeout=self.scan_timeout_var.get())
            
            target = None
            for device in devices:
                if device.name and device_name in device.name:
                    target = device
                    break
                    
            if not target:
                print(f"❌ Device {device_name} not found")
                return False
                
            print(f"✅ Found: {target.name} @ {target.address}")
            
            client = BleakClient(target.address)
            await client.connect()
            
            # Setup notifications based on mode
            if mode in ["hr_spo2", "ml_model"]:
                await client.start_notify(BLE_CONFIG["characteristics"]["vitals_data"], 
                                        lambda _, data: self.handle_vitals_data(data))
            elif mode == "temperature":
                await client.start_notify(BLE_CONFIG["characteristics"]["raw_data"], 
                                        lambda _, data: self.handle_temperature_data(data))
            elif mode == "force_test":
                await client.start_notify(BLE_CONFIG["characteristics"]["raw_data"], 
                                        lambda _, data: self.handle_force_data(data))
            elif mode == "distance_test":
                await client.start_notify(BLE_CONFIG["characteristics"]["raw_data"], 
                                        lambda _, data: self.handle_distance_data(data))
                                        
            # Send mode command to ESP32
            mode_commands = {
                "hr_spo2": "MODE:HR_SPO2",
                "temperature": "MODE:TEMPERATURE", 
                "force_test": "MODE:FORCE_TEST",
                "distance_test": "MODE:DISTANCE_TEST",
                "ml_model": "MODE:QUALITY"
            }
            
            if mode in mode_commands:
                await client.write_gatt_char(BLE_CONFIG["characteristics"]["control"], 
                                           mode_commands[mode].encode())
                await asyncio.sleep(2)  # Wait for mode switch
                
            self.ble_clients[mode] = client
            return True
            
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
            
    def on_connect_success(self, mode):
        """Handle successful connection"""
        self.connection_status[mode] = True
        self.connection_label.config(text="✅ Connected", fg='#27ae60')
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        
    def on_connect_failure(self):
        """Handle connection failure"""
        self.connection_label.config(text="❌ Connection Failed", fg='#e74c3c')
        self.connect_btn.config(state=tk.NORMAL)
        messagebox.showerror("Connection Error", "Failed to connect to device. Check device is on and in range.")
        
    def disconnect_device(self):
        """Disconnect from current device"""
        mode = self.mode_var.get()
        if mode in self.ble_clients:
            threading.Thread(target=self.ble_disconnect_worker, args=(mode,), daemon=True).start()
            
    def ble_disconnect_worker(self, mode):
        """BLE disconnection worker"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            client = self.ble_clients.get(mode)
            if client and client.is_connected:
                loop.run_until_complete(client.disconnect())
                
            self.root.after(0, self.on_disconnect_success, mode)
            
        except Exception as e:
            print(f"Disconnect error: {e}")
        finally:
            loop.close()
            
    def on_disconnect_success(self, mode):
        """Handle successful disconnection"""
        if mode in self.ble_clients:
            del self.ble_clients[mode]
        if mode in self.connection_status:
            del self.connection_status[mode]
            
        self.connection_label.config(text="❌ Disconnected", fg='#e74c3c')
        self.disconnect_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        
    def start_recording(self):
        """Start data recording"""
        if self.auto_save_var.get():
            self.setup_csv_logging()
            
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # Send start command to ESP32 if needed
        mode = self.mode_var.get()
        if mode in self.ble_clients:
            threading.Thread(target=self.send_start_command, args=(mode,), daemon=True).start()
            
    def stop_recording(self):
        """Stop data recording"""
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        
        # Close CSV files
        for writer in self.csv_files.values():
            if writer:
                writer.close()
        self.csv_files.clear()
        self.csv_writers.clear()
        
    def send_start_command(self, mode):
        """Send start command to ESP32"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            client = self.ble_clients.get(mode)
            if client and client.is_connected:
                if mode == "force_test":
                    loop.run_until_complete(client.write_gatt_char(
                        BLE_CONFIG["characteristics"]["control"], "LABEL:recording".encode()))
                elif mode == "distance_test":
                    loop.run_until_complete(client.write_gatt_char(
                        BLE_CONFIG["characteristics"]["control"], "START:ir:0".encode()))
                        
        except Exception as e:
            print(f"Start command error: {e}")
        finally:
            loop.close()
            
    def setup_csv_logging(self):
        """Setup CSV logging for current mode"""
        mode = self.mode_var.get()
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        
        csv_configs = {
            "hr_spo2": {
                "filename": f"../test_logs/hr_spo2_data_{timestamp}.csv",
                "headers": ["Timestamp", "HeartRate", "SpO2", "Ax", "Ay", "Az"]
            },
            "temperature": {
                "filename": f"../test_logs/temperature_data_{timestamp}.csv", 
                "headers": ["Timestamp", "Temperature"]
            },
            "force_test": {
                "filename": f"../test_logs/force_data_{timestamp}.csv",
                "headers": ["Timestamp", "IR", "Red", "FSR", "Label", "Device_Timestamp"]
            },
            "distance_test": {
                "filename": f"../test_logs/distance_data_{timestamp}.csv",
                "headers": ["Timestamp", "LED", "Distance_mm", "IR", "Red", "Avg_IR", "Avg_Red", "Samples"]
            },
            "ml_model": {
                "filename": f"../test_logs/ml_model_data_{timestamp}.csv",
                "headers": ["Timestamp", "HeartRate", "SpO2", "Quality", "Confidence", "Ax", "Ay", "Az"]
            }
        }
        
        if mode in csv_configs:
            config = csv_configs[mode]
            try:
                # Ensure directory exists
                Path(config["filename"]).parent.mkdir(parents=True, exist_ok=True)
                
                csv_file = open(config["filename"], mode='w', newline='')
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow(config["headers"])
                
                self.csv_files[mode] = csv_file
                self.csv_writers[mode] = csv_writer
                
                print(f"✅ CSV logging started: {config['filename']}")
                
            except Exception as e:
                print(f"❌ CSV setup error: {e}")
                messagebox.showerror("CSV Error", f"Failed to setup CSV logging: {e}")
                
    def handle_vitals_data(self, data):
        """Handle HR/SpO2/Accelerometer data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            # Extract data
            hr = int(obj.get("hr", 0))
            spo2 = int(obj.get("spo2", 0))
            ax = float(obj.get("ax", 0))
            ay = float(obj.get("ay", 0))
            az = float(obj.get("az", 0))
            
            # Queue data for processing
            self.data_queues['hr_spo2'].put({
                'timestamp': timestamp,
                'hr': hr,
                'spo2': spo2,
                'ax': ax,
                'ay': ay,
                'az': az
            })
            
        except Exception as e:
            print(f"Vitals data parse error: {e}")
            
    def handle_temperature_data(self, data):
        """Handle temperature data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            temp = float(obj.get("temperature", 0))
            
            self.data_queues['temperature'].put({
                'timestamp': timestamp,
                'temperature': temp
            })
            
        except Exception as e:
            print(f"Temperature data parse error: {e}")
            
    def handle_force_data(self, data):
        """Handle force sensor data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            ir = float(obj.get("ir", 0))
            red = float(obj.get("red", 0))
            fsr = float(obj.get("fsr", 0))
            label = obj.get("label", "unknown")
            device_ts = obj.get("timestamp", 0)
            
            self.data_queues['force'].put({
                'timestamp': timestamp,
                'ir': ir,
                'red': red,
                'fsr': fsr,
                'label': label,
                'device_timestamp': device_ts
            })
            
        except Exception as e:
            print(f"Force data parse error: {e}")
            
    def handle_distance_data(self, data):
        """Handle distance test data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            self.data_queues['distance'].put({
                'timestamp': timestamp,
                'data': obj
            })
            
        except Exception as e:
            print(f"Distance data parse error: {e}")
            
    def data_processor(self):
        """Background data processing thread"""
        sample_count = 0
        
        while self.data_processor_running:
            try:
                # Process each queue
                for queue_name, data_queue in self.data_queues.items():
                    while not data_queue.empty():
                        data_item = data_queue.get_nowait()
                        self.process_data_item(queue_name, data_item)
                        sample_count += 1
                        
                # Update sample count in GUI thread
                self.root.after(0, self.update_sample_count, sample_count)
                
                time.sleep(0.01)  # Small delay to prevent excessive CPU usage
                
            except Exception as e:
                print(f"Data processor error: {e}")
                
    def process_data_item(self, queue_name, data_item):
        """Process individual data items"""
        try:
            current_time = time.time()
            
            if queue_name == 'hr_spo2':
                self.data_buffers['hr'].append(data_item['hr'])
                self.data_buffers['spo2'].append(data_item['spo2'])
                self.data_buffers['accel_x'].append(data_item['ax'])
                self.data_buffers['accel_y'].append(data_item['ay'])
                self.data_buffers['accel_z'].append(data_item['az'])
                self.data_buffers['timestamps'].append(current_time)
                
                # Update readings display
                self.root.after(0, self.update_readings, 'hr', f"HR: {data_item['hr']}")
                self.root.after(0, self.update_readings, 'spo₂', f"SpO₂: {data_item['spo2']}%")
                self.root.after(0, self.update_readings, 'accel', 
                              f"Accel: {data_item['ax']:.1f},{data_item['ay']:.1f},{data_item['az']:.1f}")
                
                # Write to CSV
                if 'hr_spo2' in self.csv_writers:
                    self.csv_writers['hr_spo2'].writerow([
                        data_item['timestamp'], data_item['hr'], data_item['spo2'],
                        data_item['ax'], data_item['ay'], data_item['az']
                    ])
                    self.csv_files['hr_spo2'].flush()
                    
            elif queue_name == 'temperature':
                self.data_buffers['temperature'].append(data_item['temperature'])
                self.data_buffers['timestamps'].append(current_time)
                
                self.root.after(0, self.update_readings, 'temp', f"Temp: {data_item['temperature']:.1f}°C")
                
                if 'temperature' in self.csv_writers:
                    self.csv_writers['temperature'].writerow([
                        data_item['timestamp'], data_item['temperature']
                    ])
                    self.csv_files['temperature'].flush()
                    
            elif queue_name == 'force':
                self.data_buffers['force'].append(data_item['fsr'])
                self.data_buffers['timestamps'].append(current_time)
                
                self.root.after(0, self.update_readings, 'force', f"Force: {data_item['fsr']:.0f}")
                
                if 'force_test' in self.csv_writers:
                    self.csv_writers['force_test'].writerow([
                        data_item['timestamp'], data_item['ir'], data_item['red'],
                        data_item['fsr'], data_item['label'], data_item['device_timestamp']
                    ])
                    self.csv_files['force_test'].flush()
                    
        except Exception as e:
            print(f"Process data error: {e}")
            
    def update_sample_count(self, count):
        """Update sample count display"""
        self.sample_label.config(text=str(count))
        
    def update_readings(self, reading_type, text):
        """Update current readings display"""
        if reading_type in self.readings_labels:
            self.readings_labels[reading_type].config(text=text)
            
    def update_plots(self, frame):
        """Update real-time plots"""
        try:
            if len(self.data_buffers['timestamps']) < 2:
                return
                
            timestamps = list(self.data_buffers['timestamps'])
            time_range = [t - timestamps[0] for t in timestamps]
            
            # HR/SpO2 plot
            if len(self.data_buffers['hr']) > 0:
                self.hr_line.set_data(time_range[-len(self.data_buffers['hr']):], 
                                     list(self.data_buffers['hr']))
                self.spo2_line.set_data(time_range[-len(self.data_buffers['spo2']):], 
                                       list(self.data_buffers['spo2']))
                self.axes[0, 0].relim()
                self.axes[0, 0].autoscale_view()
                
            # Temperature plot
            if len(self.data_buffers['temperature']) > 0:
                self.temp_line.set_data(time_range[-len(self.data_buffers['temperature']):], 
                                       list(self.data_buffers['temperature']))
                self.axes[0, 1].relim()
                self.axes[0, 1].autoscale_view()
                
            # Force plot
            if len(self.data_buffers['force']) > 0:
                self.force_line.set_data(time_range[-len(self.data_buffers['force']):], 
                                        list(self.data_buffers['force']))
                self.axes[1, 0].relim()
                self.axes[1, 0].autoscale_view()
                
            # Accelerometer plot
            if len(self.data_buffers['accel_x']) > 0:
                accel_range = time_range[-len(self.data_buffers['accel_x']):]
                self.accel_x_line.set_data(accel_range, list(self.data_buffers['accel_x']))
                self.accel_y_line.set_data(accel_range, list(self.data_buffers['accel_y']))
                self.accel_z_line.set_data(accel_range, list(self.data_buffers['accel_z']))
                self.axes[1, 1].relim()
                self.axes[1, 1].autoscale_view()
                
        except Exception as e:
            print(f"Plot update error: {e}")
            
    def choose_export_dir(self):
        """Choose export directory"""
        directory = filedialog.askdirectory()
        if directory:
            self.export_dir_label.config(text=f"Export Dir: {directory}")
            
    def analyze_data(self):
        """Open data analysis window"""
        AnalysisWindow(self.root)
        
    def cleanup(self):
        """Cleanup resources"""
        self.data_processor_running = False
        
        # Disconnect all devices
        for mode, client in self.ble_clients.items():
            try:
                if client.is_connected:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(client.disconnect())
                    loop.close()
            except:
                pass
                
        # Close CSV files
        for csv_file in self.csv_files.values():
            if csv_file:
                csv_file.close()


class AnalysisWindow:
    """Separate window for data analysis"""
    
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Data Analysis")
        self.window.geometry("800x600")
        self.window.configure(bg='#ecf0f1')
        
        self.setup_analysis_gui()
        
    def setup_analysis_gui(self):
        """Setup analysis GUI"""
        tk.Label(self.window, text="Data Analysis Tools", font=('Arial', 18, 'bold'),
                bg='#ecf0f1', fg='#2c3e50').pack(pady=20)
        
        # File selection
        file_frame = tk.Frame(self.window, bg='#ecf0f1')
        file_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Button(file_frame, text="📁 Load CSV File", command=self.load_csv_file,
                 font=('Arial', 12), bg='#3498db', fg='white', relief=tk.FLAT, padx=20).pack(side=tk.LEFT)
        
        self.file_label = tk.Label(file_frame, text="No file selected", font=('Arial', 11),
                                  bg='#ecf0f1', fg='#7f8c8d')
        self.file_label.pack(side=tk.LEFT, padx=(20, 0))
        
        # Analysis buttons
        analysis_frame = tk.Frame(self.window, bg='#ecf0f1')
        analysis_frame.pack(fill=tk.X, padx=20, pady=20)
        
        analyses = [
            ("📊 Basic Statistics", self.basic_stats),
            ("📈 Signal Analysis", self.signal_analysis),
            ("🔗 Correlation Analysis", self.correlation_analysis),
            ("🤖 ML Analysis", self.ml_analysis),
            ("📋 Generate Report", self.generate_report)
        ]
        
        for i, (text, command) in enumerate(analyses):
            btn = tk.Button(analysis_frame, text=text, command=command,
                           font=('Arial', 11), bg='#9b59b6', fg='white', 
                           relief=tk.FLAT, padx=20, width=20)
            btn.grid(row=i//2, column=i%2, padx=10, pady=10, sticky='ew')
            
        # Results area
        self.results_text = tk.Text(self.window, height=20, font=('Consolas', 10),
                                   bg='white', fg='#2c3e50')
        self.results_text.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        # Scrollbar for results
        scrollbar = tk.Scrollbar(self.results_text)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.results_text.yview)
        
    def load_csv_file(self):
        """Load CSV file for analysis"""
        file_path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                self.df = pd.read_csv(file_path)
                self.file_label.config(text=f"Loaded: {Path(file_path).name}")
                self.results_text.insert(tk.END, f"✅ Loaded file: {file_path}\n")
                self.results_text.insert(tk.END, f"📊 Shape: {self.df.shape}\n")
                self.results_text.insert(tk.END, f"📋 Columns: {list(self.df.columns)}\n\n")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")
                
    def basic_stats(self):
        """Calculate basic statistics"""
        if not hasattr(self, 'df'):
            messagebox.showwarning("Warning", "Please load a CSV file first")
            return
            
        self.results_text.insert(tk.END, "=" * 50 + "\n")
        self.results_text.insert(tk.END, "📈 BASIC STATISTICS\n")
        self.results_text.insert(tk.END, "=" * 50 + "\n")
        
        # Numeric columns only
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            stats = self.df[numeric_cols].describe()
            self.results_text.insert(tk.END, str(stats) + "\n\n")
        else:
            self.results_text.insert(tk.END, "No numeric columns found\n\n")
            
    def signal_analysis(self):
        """Perform signal analysis"""
        if not hasattr(self, 'df'):
            messagebox.showwarning("Warning", "Please load a CSV file first")
            return
            
        self.results_text.insert(tk.END, "🔬 SIGNAL ANALYSIS\n")
        self.results_text.insert(tk.END, "=" * 30 + "\n")
        
        # Sample analysis for HR data if available
        if 'HeartRate' in self.df.columns:
            hr_data = self.df['HeartRate'].dropna()
            if len(hr_data) > 10:
                # Basic signal stats
                self.results_text.insert(tk.END, f"HR Mean: {hr_data.mean():.2f} bpm\n")
                self.results_text.insert(tk.END, f"HR Std: {hr_data.std():.2f} bpm\n")
                self.results_text.insert(tk.END, f"HR Range: {hr_data.min():.0f} - {hr_data.max():.0f} bpm\n")
                
                # Variability
                hr_diff = np.diff(hr_data)
                self.results_text.insert(tk.END, f"HR Variability (RMSSD): {np.sqrt(np.mean(hr_diff**2)):.2f}\n")
                
        self.results_text.insert(tk.END, "\n")
        
    def correlation_analysis(self):
        """Perform correlation analysis"""
        if not hasattr(self, 'df'):
            messagebox.showwarning("Warning", "Please load a CSV file first")
            return
            
        self.results_text.insert(tk.END, "🔗 CORRELATION ANALYSIS\n")
        self.results_text.insert(tk.END, "=" * 35 + "\n")
        
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 1:
            corr_matrix = self.df[numeric_cols].corr()
            self.results_text.insert(tk.END, str(corr_matrix) + "\n\n")
        else:
            self.results_text.insert(tk.END, "Not enough numeric columns for correlation\n\n")
            
    def ml_analysis(self):
        """Perform ML analysis"""
        if not hasattr(self, 'df'):
            messagebox.showwarning("Warning", "Please load a CSV file first")
            return
            
        self.results_text.insert(tk.END, "🤖 ML ANALYSIS\n")
        self.results_text.insert(tk.END, "=" * 25 + "\n")
        
        # Simple clustering if we have enough numeric data
        numeric_cols = self.df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) >= 2 and len(self.df) > 10:
            try:
                # PCA analysis
                data = self.df[numeric_cols].dropna()
                if len(data) > 3:
                    scaler = StandardScaler()
                    scaled_data = scaler.fit_transform(data)
                    
                    pca = PCA()
                    pca_result = pca.fit_transform(scaled_data)
                    
                    self.results_text.insert(tk.END, "PCA Explained Variance Ratio:\n")
                    for i, ratio in enumerate(pca.explained_variance_ratio_[:3]):
                        self.results_text.insert(tk.END, f"  PC{i+1}: {ratio:.3f}\n")
                        
                    # Simple clustering
                    kmeans = KMeans(n_clusters=min(3, len(data)//5), random_state=42, n_init=10)
                    clusters = kmeans.fit_predict(scaled_data)
                    
                    unique_clusters = np.unique(clusters)
                    self.results_text.insert(tk.END, f"\nClustering Results:\n")
                    for cluster in unique_clusters:
                        count = np.sum(clusters == cluster)
                        self.results_text.insert(tk.END, f"  Cluster {cluster}: {count} samples\n")
                        
            except Exception as e:
                self.results_text.insert(tk.END, f"ML analysis error: {e}\n")
        else:
            self.results_text.insert(tk.END, "Insufficient data for ML analysis\n")
            
        self.results_text.insert(tk.END, "\n")
        
    def generate_report(self):
        """Generate comprehensive report"""
        if not hasattr(self, 'df'):
            messagebox.showwarning("Warning", "Please load a CSV file first")
            return
            
        self.results_text.delete(1.0, tk.END)
        
        # Run all analyses
        self.basic_stats()
        self.signal_analysis()
        self.correlation_analysis()
        self.ml_analysis()
        
        # Add summary
        self.results_text.insert(tk.END, "📋 ANALYSIS COMPLETE\n")
        self.results_text.insert(tk.END, "=" * 35 + "\n")
        self.results_text.insert(tk.END, f"Report generated at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def main():
    """Main application entry point"""
    root = tk.Tk()
    app = UnifiedDashboard(root)
    
    def on_closing():
        app.cleanup()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
