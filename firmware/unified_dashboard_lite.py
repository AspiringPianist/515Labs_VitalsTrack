"""
ESP32 VitalsTrack Unified Dashboard - Lightweight Version
========================================================
A lightweight dashboard for monitoring vitals data from ESP32 sensors.
Supports multiple modes: HR/SpO2, Temperature, Force Testing, Distance Testing.
No heavy ML dependencies required.
"""

import asyncio
import csv
import datetime
import json
import queue
import threading
import time
import warnings
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from bleak import BleakScanner, BleakClient

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

class LightweightDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("VitalsTrack Dashboard v1.0 - Lightweight")
        self.root.geometry("1200x800")
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
        self.current_mode = "hr_spo2"
        self.recording = False
        
        # Data buffers (using lists instead of deque for simplicity)
        self.max_buffer_size = 100
        self.data_buffers = {
            'hr': [],
            'spo2': [],
            'temperature': [],
            'force': [],
            'accel_x': [],
            'accel_y': [],
            'accel_z': [],
            'timestamps': []
        }
        
        # CSV writers
        self.csv_writers = {}
        self.csv_files = {}
        self.export_dir = "../test_logs"
        
        # Statistics
        self.sample_count = 0
        self.start_time = time.time()
        
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
        title_label = tk.Label(main_frame, text="🫀 VitalsTrack Dashboard", 
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
        control_frame = tk.LabelFrame(parent, text="🎛️ Control Panel", font=('Arial', 14, 'bold'),
                                     fg='#ecf0f1', bg='#34495e', bd=2)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Mode Selection Row
        mode_frame = tk.Frame(control_frame, bg='#34495e')
        mode_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(mode_frame, text="📡 Operating Mode:", font=('Arial', 12, 'bold'),
                fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT)
        
        self.mode_var = tk.StringVar(value="hr_spo2")
        mode_combo = ttk.Combobox(mode_frame, textvariable=self.mode_var, 
                                 values=["hr_spo2", "temperature", "force_test", "distance_test"],
                                 state="readonly", font=('Arial', 11), width=15)
        mode_combo.pack(side=tk.LEFT, padx=(10, 20))
        mode_combo.bind('<<ComboboxSelected>>', self.on_mode_change)
        
        # Device name display
        self.device_label = tk.Label(mode_frame, text="Device: ESP32_Unified_Sensor", 
                                   font=('Arial', 10), fg='#bdc3c7', bg='#34495e')
        self.device_label.pack(side=tk.LEFT, padx=(20, 0))
        
        # Buttons Row
        btn_frame = tk.Frame(control_frame, bg='#34495e')
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # Connection buttons
        self.connect_btn = tk.Button(btn_frame, text="🔗 Connect", command=self.connect_device,
                                   bg='#27ae60', fg='white', font=('Arial', 11, 'bold'),
                                   relief=tk.FLAT, padx=15, pady=5)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.disconnect_btn = tk.Button(btn_frame, text="⚡ Disconnect", command=self.disconnect_device,
                                      bg='#e74c3c', fg='white', font=('Arial', 11, 'bold'),
                                      relief=tk.FLAT, padx=15, pady=5, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Recording buttons
        self.start_btn = tk.Button(btn_frame, text="▶ Start Recording", command=self.start_recording,
                                 bg='#3498db', fg='white', font=('Arial', 11, 'bold'),
                                 relief=tk.FLAT, padx=15, pady=5, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_btn = tk.Button(btn_frame, text="⏹ Stop Recording", command=self.stop_recording,
                                bg='#f39c12', fg='white', font=('Arial', 11, 'bold'),
                                relief=tk.FLAT, padx=15, pady=5, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Analysis buttons
        self.clear_btn = tk.Button(btn_frame, text="🗑️ Clear Data", command=self.clear_data,
                                 bg='#95a5a6', fg='white', font=('Arial', 11, 'bold'),
                                 relief=tk.FLAT, padx=15, pady=5)
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.export_btn = tk.Button(btn_frame, text="💾 Export", command=self.export_data,
                                  bg='#9b59b6', fg='white', font=('Arial', 11, 'bold'),
                                  relief=tk.FLAT, padx=15, pady=5)
        self.export_btn.pack(side=tk.LEFT, padx=(0, 5))
        
    def setup_status_panel(self, parent):
        """Setup status display panel"""
        status_frame = tk.LabelFrame(parent, text="📊 System Status", font=('Arial', 14, 'bold'),
                                   fg='#ecf0f1', bg='#34495e', bd=2)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status grid
        status_grid = tk.Frame(status_frame, bg='#34495e')
        status_grid.pack(fill=tk.X, padx=10, pady=10)
        
        # Top row - Connection and Recording status
        tk.Label(status_grid, text="Connection:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.connection_label = tk.Label(status_grid, text="❌ Disconnected", font=('Arial', 11),
                                       fg='#e74c3c', bg='#34495e')
        self.connection_label.grid(row=0, column=1, sticky=tk.W, padx=(0, 30))
        
        tk.Label(status_grid, text="Recording:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
        self.recording_label = tk.Label(status_grid, text="⏸️ Stopped", font=('Arial', 11),
                                      fg='#f39c12', bg='#34495e')
        self.recording_label.grid(row=0, column=3, sticky=tk.W, padx=(0, 30))
        
        tk.Label(status_grid, text="Samples:", font=('Arial', 11, 'bold'),
                fg='#ecf0f1', bg='#34495e').grid(row=0, column=4, sticky=tk.W, padx=(0, 10))
        self.sample_label = tk.Label(status_grid, text="0", font=('Arial', 11),
                                   fg='#3498db', bg='#34495e')
        self.sample_label.grid(row=0, column=5, sticky=tk.W)
        
        # Bottom row - Current readings
        readings_frame = tk.Frame(status_frame, bg='#34495e')
        readings_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.readings_labels = {}
        readings = [
            ('hr', 'HR: --'), 
            ('spo₂', 'SpO₂: --%'), 
            ('temp', 'Temp: --°C'), 
            ('force', 'Force: --'),
            ('accel', 'Accel: --,--,--')
        ]
        
        for i, (key, text) in enumerate(readings):
            label = tk.Label(readings_frame, text=text, font=('Arial', 12, 'bold'),
                           fg='#2ecc71', bg='#34495e')
            label.pack(side=tk.LEFT, padx=(0, 15))
            self.readings_labels[key] = label
            
    def setup_data_panel(self, parent):
        """Setup data display panel with tabs"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Real-time plots tab
        self.plots_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.plots_frame, text="📈 Real-time Plots")
        
        # Statistics tab
        self.stats_frame = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(self.stats_frame, text="📋 Statistics")
        
        # Setup statistics display
        self.setup_stats_display()
        
    def setup_stats_display(self):
        """Setup statistics display"""
        stats_title = tk.Label(self.stats_frame, text="📊 Data Statistics", 
                              font=('Arial', 18, 'bold'), bg='#ecf0f1', fg='#2c3e50')
        stats_title.pack(pady=20)
        
        # Create text widget for statistics
        self.stats_text = tk.Text(self.stats_frame, height=25, font=('Consolas', 11),
                                 bg='white', fg='#2c3e50', wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        # Scrollbar for stats
        stats_scrollbar = tk.Scrollbar(self.stats_text)
        stats_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stats_text.config(yscrollcommand=stats_scrollbar.set)
        stats_scrollbar.config(command=self.stats_text.yview)
        
        # Update button
        update_stats_btn = tk.Button(self.stats_frame, text="🔄 Update Statistics", 
                                   command=self.update_statistics,
                                   bg='#3498db', fg='white', font=('Arial', 12, 'bold'),
                                   relief=tk.FLAT, padx=20)
        update_stats_btn.pack(pady=10)
        
    def setup_plots(self):
        """Setup matplotlib plots"""
        # Create figure with subplots
        self.fig, self.axes = plt.subplots(2, 2, figsize=(12, 8))
        self.fig.patch.set_facecolor('#ecf0f1')
        self.fig.suptitle('VitalsTrack Real-time Data', fontsize=16, fontweight='bold')
        
        # Configure each subplot
        plot_configs = [
            (0, 0, 'Heart Rate & SpO₂', 'HR (bpm) / SpO₂ (%)'),
            (0, 1, 'Temperature', 'Temperature (°C)'),
            (1, 0, 'Force Sensor', 'Force (ADC)'),
            (1, 1, 'Accelerometer', 'Acceleration (g)')
        ]
        
        for row, col, title, ylabel in plot_configs:
            self.axes[row, col].set_title(title, fontweight='bold')
            self.axes[row, col].set_ylabel(ylabel)
            self.axes[row, col].grid(True, alpha=0.3)
            self.axes[row, col].set_xlabel('Time (s)')
        
        # Initialize plot lines
        self.hr_line, = self.axes[0, 0].plot([], [], 'r-', label='HR', linewidth=2)
        self.spo2_line, = self.axes[0, 0].plot([], [], 'b-', label='SpO₂', linewidth=2)
        self.axes[0, 0].legend()
        
        self.temp_line, = self.axes[0, 1].plot([], [], 'g-', linewidth=2)
        self.force_line, = self.axes[1, 0].plot([], [], 'm-', linewidth=2)
        
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
        self.ani = animation.FuncAnimation(self.fig, self.update_plots, interval=200, blit=False)
        
    def on_mode_change(self, event=None):
        """Handle mode selection change"""
        new_mode = self.mode_var.get()
        mode_names = {
            "hr_spo2": "HR/SpO₂ Monitoring",
            "temperature": "Temperature Monitoring",
            "force_test": "Force Testing", 
            "distance_test": "Distance Testing"
        }
        
        device_names = {
            "hr_spo2": "ESP32_Unified_Sensor",
            "temperature": "ESP32_Unified_Sensor",
            "force_test": "ESP32_Unified_Sensor",
            "distance_test": "ESP32_Unified_Sensor"
        }
        
        self.current_mode = new_mode
        self.device_label.config(text=f"Device: {device_names.get(new_mode, 'ESP32_Unified_Sensor')}")
        
        print(f"🔄 Mode changed to: {mode_names.get(new_mode, new_mode)}")
        
    def connect_device(self):
        """Connect to ESP32 device based on current mode"""
        mode = self.mode_var.get()
        device_name = self.get_device_name(mode)
        
        self.connection_label.config(text="🔄 Connecting...", fg='#f39c12')
        self.connect_btn.config(state=tk.DISABLED)
        
        print(f"🔍 Attempting to connect to {device_name} for {mode} mode...")
        
        # Run connection in background thread
        threading.Thread(target=self.ble_connect_worker, args=(device_name, mode), daemon=True).start()
        
    def get_device_name(self, mode):
        """Get appropriate device name for mode"""
        # Using unified device for all modes as per the guide
        return "ESP32_Unified_Sensor"
        
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
            print(f"❌ Connection error: {e}")
            self.root.after(0, self.on_connect_failure)
        finally:
            loop.close()
            
    async def async_connect(self, device_name, mode):
        """Async BLE connection"""
        try:
            print(f"🔍 Scanning for {device_name}...")
            devices = await BleakScanner.discover(timeout=15.0)
            
            target = None
            print(f"Found {len(devices)} devices:")
            for device in devices:
                if device.name:
                    print(f"  - {device.name} ({device.address})")
                    if device_name in device.name:
                        target = device
                        break
                        
            if not target:
                print(f"❌ Device {device_name} not found")
                return False
                
            print(f"✅ Found: {target.name} @ {target.address}")
            
            client = BleakClient(target.address)
            await client.connect()
            print(f"🔗 Connected to {target.name}")
            
            # Setup notifications based on mode
            char_uuid = None
            if mode in ["hr_spo2"]:
                char_uuid = BLE_CONFIG["characteristics"]["raw_data"]  # Use raw_data for unified
                await client.start_notify(char_uuid, lambda _, data: self.handle_vitals_data(data))
            elif mode == "temperature":
                char_uuid = BLE_CONFIG["characteristics"]["raw_data"]
                await client.start_notify(char_uuid, lambda _, data: self.handle_temperature_data(data))
            elif mode == "force_test":
                char_uuid = BLE_CONFIG["characteristics"]["raw_data"]
                await client.start_notify(char_uuid, lambda _, data: self.handle_force_data(data))
            elif mode == "distance_test":
                char_uuid = BLE_CONFIG["characteristics"]["raw_data"]
                await client.start_notify(char_uuid, lambda _, data: self.handle_distance_data(data))
                
            print(f"📡 Notifications started on {char_uuid}")
                                        
            # Send mode command to ESP32 (following the UNIFIED_SYSTEM_GUIDE format)
            mode_commands = {
                "hr_spo2": "MODE:HR_SPO2",
                "temperature": "MODE:TEMPERATURE", 
                "force_test": "MODE:FORCE_TEST",
                "distance_test": "MODE:DISTANCE_TEST"
            }
            
            if mode in mode_commands:
                control_char = BLE_CONFIG["characteristics"]["control"]
                command = mode_commands[mode]
                await client.write_gatt_char(control_char, command.encode())
                print(f"📤 Sent command: {command}")
                await asyncio.sleep(2)  # Wait for mode switch
                
            self.ble_clients[mode] = client
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
            
    def on_connect_success(self, mode):
        """Handle successful connection"""
        self.connection_status[mode] = True
        self.connection_label.config(text="✅ Connected", fg='#27ae60')
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        print(f"✅ Successfully connected in {mode} mode")
        
    def on_connect_failure(self):
        """Handle connection failure"""
        self.connection_label.config(text="❌ Connection Failed", fg='#e74c3c')
        self.connect_btn.config(state=tk.NORMAL)
        messagebox.showerror("Connection Error", 
                           "Failed to connect to device.\n\nTroubleshooting:\n" +
                           "1. Check ESP32 is powered on\n" +
                           "2. Ensure device is in range\n" +
                           "3. Verify device name 'ESP32_Unified_Sensor'\n" +
                           "4. Try restarting the ESP32")
        
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
                print(f"🔌 Disconnected from device")
                
            self.root.after(0, self.on_disconnect_success, mode)
            
        except Exception as e:
            print(f"❌ Disconnect error: {e}")
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
        self.recording = True
        self.recording_label.config(text="🔴 Recording", fg='#e74c3c')
        self.setup_csv_logging()
            
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        print(f"▶️ Recording started in {self.mode_var.get()} mode")
        
        # Send start command to ESP32 if needed
        mode = self.mode_var.get()
        if mode in self.ble_clients:
            threading.Thread(target=self.send_start_command, args=(mode,), daemon=True).start()
            
    def stop_recording(self):
        """Stop data recording"""
        self.recording = False
        self.recording_label.config(text="⏸️ Stopped", fg='#f39c12')
        
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        
        print("⏹️ Recording stopped")
        
        # Close CSV files
        for csv_file in self.csv_files.values():
            if csv_file:
                csv_file.close()
        self.csv_files.clear()
        self.csv_writers.clear()
        
    def send_start_command(self, mode):
        """Send start command to ESP32"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            client = self.ble_clients.get(mode)
            if client and client.is_connected:
                control_char = BLE_CONFIG["characteristics"]["control"]
                
                if mode == "force_test":
                    command = "LABEL:recording"
                elif mode == "distance_test":
                    command = "START:ir:0"
                else:
                    command = "START"
                    
                loop.run_until_complete(client.write_gatt_char(control_char, command.encode()))
                print(f"📤 Sent start command: {command}")
                        
        except Exception as e:
            print(f"❌ Start command error: {e}")
        finally:
            loop.close()
            
    def setup_csv_logging(self):
        """Setup CSV logging for current mode"""
        mode = self.mode_var.get()
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        
        csv_configs = {
            "hr_spo2": {
                "filename": f"{self.export_dir}/hr_spo2_data_{timestamp}.csv",
                "headers": ["Timestamp", "HeartRate", "SpO2", "Ax", "Ay", "Az"]
            },
            "temperature": {
                "filename": f"{self.export_dir}/temperature_data_{timestamp}.csv", 
                "headers": ["Timestamp", "Temperature"]
            },
            "force_test": {
                "filename": f"{self.export_dir}/force_data_{timestamp}.csv",
                "headers": ["Timestamp", "IR", "Red", "FSR", "Label", "Device_Timestamp"]
            },
            "distance_test": {
                "filename": f"{self.export_dir}/distance_data_{timestamp}.csv",
                "headers": ["Timestamp", "LED", "Distance_mm", "IR", "Red", "Avg_IR", "Avg_Red", "Samples"]
            }
        }
        
        if mode in csv_configs:
            config = csv_configs[mode]
            try:
                # Ensure directory exists
                Path(config["filename"]).parent.mkdir(parents=True, exist_ok=True)
                
                csv_file = open(config["filename"], mode='w', newline='', encoding='utf-8')
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow(config["headers"])
                
                self.csv_files[mode] = csv_file
                self.csv_writers[mode] = csv_writer
                
                print(f"📝 CSV logging started: {config['filename']}")
                
            except Exception as e:
                print(f"❌ CSV setup error: {e}")
                messagebox.showerror("CSV Error", f"Failed to setup CSV logging: {e}")
                
    def handle_vitals_data(self, data):
        """Handle HR/SpO2/Accelerometer data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            # Extract data with defaults
            hr = int(obj.get("hr", obj.get("heart_rate", 0)))
            spo2 = int(obj.get("spo2", obj.get("oxygen", 0)))
            ax = float(obj.get("ax", obj.get("accel_x", 0)))
            ay = float(obj.get("ay", obj.get("accel_y", 0)))
            az = float(obj.get("az", obj.get("accel_z", 0)))
            
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
            print(f"❌ Vitals data parse error: {e}")
            
    def handle_temperature_data(self, data):
        """Handle temperature data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            temp = float(obj.get("temperature", obj.get("temp", 0)))
            
            self.data_queues['temperature'].put({
                'timestamp': timestamp,
                'temperature': temp
            })
            
        except Exception as e:
            print(f"❌ Temperature data parse error: {e}")
            
    def handle_force_data(self, data):
        """Handle force sensor data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            ir = float(obj.get("ir", 0))
            red = float(obj.get("red", 0))
            fsr = float(obj.get("fsr", obj.get("force", 0)))
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
            print(f"❌ Force data parse error: {e}")
            
    def handle_distance_data(self, data):
        """Handle distance test data"""
        try:
            obj = json.loads(data.decode())
            timestamp = datetime.datetime.now().isoformat()
            
            self.data_queues['distance'].put({
                'timestamp': timestamp,
                'data': obj
            })
            
            # Print distance data for debugging
            if "type" in obj and obj["type"] == "average":
                print(f"📊 {obj.get('led', 'unknown')} @ {obj.get('distance_mm', 0)}mm => " +
                      f"IR: {obj.get('avg_ir', 0):.2f}, Red: {obj.get('avg_red', 0):.2f}")
            
        except Exception as e:
            print(f"❌ Distance data parse error: {e}")
            
    def data_processor(self):
        """Background data processing thread"""
        while self.data_processor_running:
            try:
                # Process each queue
                for queue_name, data_queue in self.data_queues.items():
                    while not data_queue.empty():
                        data_item = data_queue.get_nowait()
                        self.process_data_item(queue_name, data_item)
                        self.sample_count += 1
                        
                # Update sample count in GUI thread
                self.root.after(0, self.update_sample_count, self.sample_count)
                
                time.sleep(0.01)  # Small delay to prevent excessive CPU usage
                
            except Exception as e:
                print(f"❌ Data processor error: {e}")
                
    def process_data_item(self, queue_name, data_item):
        """Process individual data items"""
        try:
            current_time = time.time() - self.start_time  # Relative time
            
            if queue_name == 'hr_spo2':
                # Add to buffers
                self.add_to_buffer('hr', data_item['hr'])
                self.add_to_buffer('spo2', data_item['spo2'])
                self.add_to_buffer('accel_x', data_item['ax'])
                self.add_to_buffer('accel_y', data_item['ay'])
                self.add_to_buffer('accel_z', data_item['az'])
                self.add_to_buffer('timestamps', current_time)
                
                # Update readings display
                self.root.after(0, self.update_readings, 'hr', f"HR: {data_item['hr']}")
                self.root.after(0, self.update_readings, 'spo₂', f"SpO₂: {data_item['spo2']}%")
                self.root.after(0, self.update_readings, 'accel', 
                              f"Accel: {data_item['ax']:.1f},{data_item['ay']:.1f},{data_item['az']:.1f}")
                
                # Write to CSV if recording
                if self.recording and 'hr_spo2' in self.csv_writers:
                    self.csv_writers['hr_spo2'].writerow([
                        data_item['timestamp'], data_item['hr'], data_item['spo2'],
                        data_item['ax'], data_item['ay'], data_item['az']
                    ])
                    self.csv_files['hr_spo2'].flush()
                    
            elif queue_name == 'temperature':
                self.add_to_buffer('temperature', data_item['temperature'])
                self.add_to_buffer('timestamps', current_time)
                
                self.root.after(0, self.update_readings, 'temp', f"Temp: {data_item['temperature']:.1f}°C")
                
                if self.recording and 'temperature' in self.csv_writers:
                    self.csv_writers['temperature'].writerow([
                        data_item['timestamp'], data_item['temperature']
                    ])
                    self.csv_files['temperature'].flush()
                    
            elif queue_name == 'force':
                self.add_to_buffer('force', data_item['fsr'])
                self.add_to_buffer('timestamps', current_time)
                
                self.root.after(0, self.update_readings, 'force', f"Force: {data_item['fsr']:.0f}")
                
                if self.recording and 'force_test' in self.csv_writers:
                    self.csv_writers['force_test'].writerow([
                        data_item['timestamp'], data_item['ir'], data_item['red'],
                        data_item['fsr'], data_item['label'], data_item['device_timestamp']
                    ])
                    self.csv_files['force_test'].flush()
                    
            elif queue_name == 'distance':
                # Handle distance test data
                obj = data_item['data']
                if self.recording and 'distance_test' in self.csv_writers:
                    if "type" in obj and obj["type"] == "average":
                        self.csv_writers['distance_test'].writerow([
                            data_item['timestamp'], obj.get('led', ''), obj.get('distance_mm', 0),
                            '', '', obj.get('avg_ir', 0), obj.get('avg_red', 0), obj.get('samples', 0)
                        ])
                    else:
                        self.csv_writers['distance_test'].writerow([
                            data_item['timestamp'], '', '', obj.get('ir', 0), obj.get('red', 0),
                            '', '', ''
                        ])
                    self.csv_files['distance_test'].flush()
                    
        except Exception as e:
            print(f"❌ Process data error: {e}")
            
    def add_to_buffer(self, buffer_name, value):
        """Add value to buffer with size limit"""
        if buffer_name in self.data_buffers:
            self.data_buffers[buffer_name].append(value)
            # Keep only last max_buffer_size items
            if len(self.data_buffers[buffer_name]) > self.max_buffer_size:
                self.data_buffers[buffer_name] = self.data_buffers[buffer_name][-self.max_buffer_size:]
            
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
                
            timestamps = self.data_buffers['timestamps']
            
            # HR/SpO2 plot
            if len(self.data_buffers['hr']) > 0:
                hr_times = timestamps[-len(self.data_buffers['hr']):]
                self.hr_line.set_data(hr_times, self.data_buffers['hr'])
                
                spo2_times = timestamps[-len(self.data_buffers['spo2']):]
                self.spo2_line.set_data(spo2_times, self.data_buffers['spo2'])
                
                self.axes[0, 0].relim()
                self.axes[0, 0].autoscale_view()
                
            # Temperature plot
            if len(self.data_buffers['temperature']) > 0:
                temp_times = timestamps[-len(self.data_buffers['temperature']):]
                self.temp_line.set_data(temp_times, self.data_buffers['temperature'])
                self.axes[0, 1].relim()
                self.axes[0, 1].autoscale_view()
                
            # Force plot
            if len(self.data_buffers['force']) > 0:
                force_times = timestamps[-len(self.data_buffers['force']):]
                self.force_line.set_data(force_times, self.data_buffers['force'])
                self.axes[1, 0].relim()
                self.axes[1, 0].autoscale_view()
                
            # Accelerometer plot
            if len(self.data_buffers['accel_x']) > 0:
                accel_times = timestamps[-len(self.data_buffers['accel_x']):]
                self.accel_x_line.set_data(accel_times, self.data_buffers['accel_x'])
                self.accel_y_line.set_data(accel_times, self.data_buffers['accel_y'])
                self.accel_z_line.set_data(accel_times, self.data_buffers['accel_z'])
                self.axes[1, 1].relim()
                self.axes[1, 1].autoscale_view()
                
        except Exception as e:
            print(f"❌ Plot update error: {e}")
            
    def clear_data(self):
        """Clear all data buffers"""
        response = messagebox.askyesno("Clear Data", "Are you sure you want to clear all data?")
        if response:
            for buffer in self.data_buffers.values():
                buffer.clear()
            self.sample_count = 0
            self.start_time = time.time()
            print("🗑️ Data cleared")
            
    def export_data(self):
        """Export current data to CSV"""
        if sum(len(buffer) for buffer in self.data_buffers.values()) == 0:
            messagebox.showwarning("No Data", "No data to export")
            return
            
        filename = filedialog.asksaveasfilename(
            title="Export Data",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialname=f"vitals_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    
                    # Write headers
                    headers = ["Timestamp", "HR", "SpO2", "Temperature", "Force", "Accel_X", "Accel_Y", "Accel_Z"]
                    writer.writerow(headers)
                    
                    # Find max length
                    max_len = max(len(buffer) for buffer in self.data_buffers.values() if buffer)
                    
                    # Write data
                    for i in range(max_len):
                        row = [
                            self.data_buffers['timestamps'][i] if i < len(self.data_buffers['timestamps']) else '',
                            self.data_buffers['hr'][i] if i < len(self.data_buffers['hr']) else '',
                            self.data_buffers['spo2'][i] if i < len(self.data_buffers['spo2']) else '',
                            self.data_buffers['temperature'][i] if i < len(self.data_buffers['temperature']) else '',
                            self.data_buffers['force'][i] if i < len(self.data_buffers['force']) else '',
                            self.data_buffers['accel_x'][i] if i < len(self.data_buffers['accel_x']) else '',
                            self.data_buffers['accel_y'][i] if i < len(self.data_buffers['accel_y']) else '',
                            self.data_buffers['accel_z'][i] if i < len(self.data_buffers['accel_z']) else ''
                        ]
                        writer.writerow(row)
                        
                messagebox.showinfo("Export Complete", f"Data exported to {filename}")
                print(f"💾 Data exported to {filename}")
                
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export data: {e}")
                
    def update_statistics(self):
        """Update statistics display"""
        self.stats_text.delete(1.0, tk.END)
        
        # Header
        self.stats_text.insert(tk.END, "📊 VITALSTRACK DATA STATISTICS\n")
        self.stats_text.insert(tk.END, "=" * 50 + "\n")
        self.stats_text.insert(tk.END, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # General stats
        self.stats_text.insert(tk.END, "📈 GENERAL STATISTICS\n")
        self.stats_text.insert(tk.END, "-" * 30 + "\n")
        self.stats_text.insert(tk.END, f"Total Samples: {self.sample_count}\n")
        self.stats_text.insert(tk.END, f"Recording Time: {time.time() - self.start_time:.1f} seconds\n")
        self.stats_text.insert(tk.END, f"Current Mode: {self.mode_var.get()}\n")
        self.stats_text.insert(tk.END, f"Connected: {'Yes' if self.connection_status else 'No'}\n")
        self.stats_text.insert(tk.END, f"Recording: {'Yes' if self.recording else 'No'}\n\n")
        
        # Data-specific statistics
        if len(self.data_buffers['hr']) > 0:
            self.stats_text.insert(tk.END, "❤️ HEART RATE STATISTICS\n")
            self.stats_text.insert(tk.END, "-" * 30 + "\n")
            hr_data = [x for x in self.data_buffers['hr'] if x > 0]
            if hr_data:
                self.stats_text.insert(tk.END, f"Samples: {len(hr_data)}\n")
                self.stats_text.insert(tk.END, f"Mean: {sum(hr_data)/len(hr_data):.1f} bpm\n")
                self.stats_text.insert(tk.END, f"Min: {min(hr_data)} bpm\n")
                self.stats_text.insert(tk.END, f"Max: {max(hr_data)} bpm\n")
                self.stats_text.insert(tk.END, f"Range: {max(hr_data) - min(hr_data)} bpm\n")
            else:
                self.stats_text.insert(tk.END, "No valid heart rate data\n")
            self.stats_text.insert(tk.END, "\n")
            
        if len(self.data_buffers['spo2']) > 0:
            self.stats_text.insert(tk.END, "🫁 SPO2 STATISTICS\n")
            self.stats_text.insert(tk.END, "-" * 30 + "\n")
            spo2_data = [x for x in self.data_buffers['spo2'] if x > 0]
            if spo2_data:
                self.stats_text.insert(tk.END, f"Samples: {len(spo2_data)}\n")
                self.stats_text.insert(tk.END, f"Mean: {sum(spo2_data)/len(spo2_data):.1f}%\n")
                self.stats_text.insert(tk.END, f"Min: {min(spo2_data)}%\n")
                self.stats_text.insert(tk.END, f"Max: {max(spo2_data)}%\n")
            else:
                self.stats_text.insert(tk.END, "No valid SpO2 data\n")
            self.stats_text.insert(tk.END, "\n")
            
        if len(self.data_buffers['temperature']) > 0:
            self.stats_text.insert(tk.END, "🌡️ TEMPERATURE STATISTICS\n")
            self.stats_text.insert(tk.END, "-" * 30 + "\n")
            temp_data = [x for x in self.data_buffers['temperature'] if x > 0]
            if temp_data:
                self.stats_text.insert(tk.END, f"Samples: {len(temp_data)}\n")
                self.stats_text.insert(tk.END, f"Mean: {sum(temp_data)/len(temp_data):.2f}°C\n")
                self.stats_text.insert(tk.END, f"Min: {min(temp_data):.2f}°C\n")
                self.stats_text.insert(tk.END, f"Max: {max(temp_data):.2f}°C\n")
            else:
                self.stats_text.insert(tk.END, "No valid temperature data\n")
            self.stats_text.insert(tk.END, "\n")
            
        if len(self.data_buffers['force']) > 0:
            self.stats_text.insert(tk.END, "💪 FORCE STATISTICS\n")
            self.stats_text.insert(tk.END, "-" * 30 + "\n")
            force_data = self.data_buffers['force']
            if force_data:
                self.stats_text.insert(tk.END, f"Samples: {len(force_data)}\n")
                self.stats_text.insert(tk.END, f"Mean: {sum(force_data)/len(force_data):.1f}\n")
                self.stats_text.insert(tk.END, f"Min: {min(force_data):.1f}\n")
                self.stats_text.insert(tk.END, f"Max: {max(force_data):.1f}\n")
            self.stats_text.insert(tk.END, "\n")
            
        # Accelerometer statistics
        if len(self.data_buffers['accel_x']) > 0:
            self.stats_text.insert(tk.END, "📱 ACCELEROMETER STATISTICS\n")
            self.stats_text.insert(tk.END, "-" * 30 + "\n")
            
            for axis, name in [('accel_x', 'X'), ('accel_y', 'Y'), ('accel_z', 'Z')]:
                data = self.data_buffers[axis]
                if data:
                    self.stats_text.insert(tk.END, f"{name}-axis: Mean={sum(data)/len(data):.3f}g, ")
                    self.stats_text.insert(tk.END, f"Min={min(data):.3f}g, Max={max(data):.3f}g\n")
            self.stats_text.insert(tk.END, "\n")
            
        # Buffer status
        self.stats_text.insert(tk.END, "📊 BUFFER STATUS\n")
        self.stats_text.insert(tk.END, "-" * 30 + "\n")
        for name, buffer in self.data_buffers.items():
            self.stats_text.insert(tk.END, f"{name}: {len(buffer)}/{self.max_buffer_size}\n")
        
    def cleanup(self):
        """Cleanup resources"""
        print("🧹 Cleaning up...")
        self.data_processor_running = False
        
        # Disconnect all devices
        for mode, client in self.ble_clients.items():
            try:
                if client.is_connected:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(client.disconnect())
                    loop.close()
                    print(f"🔌 Disconnected {mode}")
            except:
                pass
                
        # Close CSV files
        for csv_file in self.csv_files.values():
            if csv_file:
                csv_file.close()
        
        print("✅ Cleanup complete")


def main():
    """Main application entry point"""
    print("🚀 Starting VitalsTrack Unified Dashboard...")
    print("📋 Supported modes: HR/SpO2, Temperature, Force Test, Distance Test")
    print("🔗 Looking for ESP32_Unified_Sensor devices")
    
    root = tk.Tk()
    app = LightweightDashboard(root)
    
    def on_closing():
        print("🛑 Shutting down...")
        app.cleanup()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\n🛑 Keyboard interrupt received")
        on_closing()


if __name__ == "__main__":
    main()
