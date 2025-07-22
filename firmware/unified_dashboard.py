import asyncio
import csv
import datetime
import json
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque
import numpy as np
from bleak import BleakScanner, BleakClient

# === BLE Configuration ===
BLE_CONFIG = {
    "device_name": "ESP32_Unified_Sensor",
    "service_uuid": "12345678-1234-5678-1234-56789abcdef0",
    "characteristics": {
        "data": "abcdefab-1234-5678-1234-56789abcdef1",
        "control": "abcdefab-1234-5678-1234-56789abcdef2",
        "status": "abcdefab-1234-5678-1234-56789abcdef3"
    }
}

class SimplifiedDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("VitalsTrack Simplified Dashboard")
        self.root.geometry("1200x800")
        self.root.configure(bg='#2c3e50')

        # Connection state
        self.client = None
        self.connected = False
        self.current_mode = "IDLE"
        self.mode_lock = threading.Lock()

        # Data buffers
        self.data_buffers = {
            'hr': deque(maxlen=100),
            'spo2': deque(maxlen=100),
            'temperature': deque(maxlen=100),
            'force': deque(maxlen=100),
            'accel_x': deque(maxlen=100),
            'accel_y': deque(maxlen=100),
            'accel_z': deque(maxlen=100),
            'ir': deque(maxlen=100),
            'red': deque(maxlen=100),
            'quality': deque(maxlen=100),
            'accel_mag': deque(maxlen=100),
            'timestamps': deque(maxlen=100)
        }

        # Quality statistics
        self.total_samples = 0
        self.good_samples = 0

        # CSV logging
        self.csv_file = None
        self.csv_writer = None
        self.csv_headers = []
        self.export_dir = Path("../test_logs")

        # GUI and plots
        self.canvas = None
        self.ani = None
        self.setup_gui()
        self.setup_plots()

        # Asyncio event loop
        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.async_thread.start()

    def run_async_loop(self):
        """Run asyncio event loop in a separate thread"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def setup_gui(self):
        """Setup the simplified GUI"""
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Title
        tk.Label(main_frame, text="VitalsTrack Dashboard", font=('Arial', 20, 'bold'),
                 fg='#ecf0f1', bg='#2c3e50').pack(pady=(0, 10))

        # Control panel
        control_frame = tk.LabelFrame(main_frame, text="Controls", font=('Arial', 12, 'bold'),
                                     fg='#ecf0f1', bg='#34495e')
        control_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(control_frame, text="Mode:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(10, 5))
        self.mode_var = tk.StringVar(value="hr_spo2")
        mode_combo = ttk.Combobox(control_frame, textvariable=self.mode_var,
                                  values=["hr_spo2", "temperature", "force_test", "distance_test", "quality", "raw_data"],
                                  state="readonly", font=('Arial', 10), width=15)
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        mode_combo.bind('<<ComboboxSelected>>', self.on_mode_change)

        self.connect_btn = tk.Button(control_frame, text="Connect", command=self.connect_device,
                                     bg='#27ae60', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.disconnect_btn = tk.Button(control_frame, text="Disconnect", command=self.disconnect_device,
                                        bg='#e74c3c', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.start_btn = tk.Button(control_frame, text="Start Recording", command=self.start_recording,
                                   bg='#3498db', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.stop_btn = tk.Button(control_frame, text="Stop Recording", command=self.stop_recording,
                                  bg='#f39c12', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        # Status panel
        status_frame = tk.LabelFrame(main_frame, text="Status", font=('Arial', 12, 'bold'),
                                    fg='#ecf0f1', bg='#34495e')
        status_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(status_frame, text="Connection:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(10, 5))
        self.connection_label = tk.Label(status_frame, text="Disconnected", font=('Arial', 10),
                                         fg='#e74c3c', bg='#34495e')
        self.connection_label.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(status_frame, text="Mode:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(0, 5))
        self.mode_label = tk.Label(status_frame, text="Idle", font=('Arial', 10),
                                   fg='#3498db', bg='#34495e')
        self.mode_label.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(status_frame, text="Data:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(0, 5))
        self.data_label = tk.Label(status_frame, text="N/A", font=('Arial', 10),
                                   fg='#f39c12', bg='#34495e')
        self.data_label.pack(side=tk.LEFT)

    def setup_plots(self):
        """Setup matplotlib plots based on current mode"""
        with self.mode_lock:
            # Clean up existing canvas and animation
            if self.canvas:
                self.canvas.get_tk_widget().destroy()
                self.canvas = None
            if self.ani:
                self.ani.event_source.stop()
                self.ani = None

            # Clear buffers
            for buffer in self.data_buffers.values():
                buffer.clear()
            self.total_samples = 0
            self.good_samples = 0

            # Reset update counters and line references
            if hasattr(self, 'stats_update_counter'):
                delattr(self, 'stats_update_counter')
            if hasattr(self, 'regular_update_counter'):
                delattr(self, 'regular_update_counter')
            if hasattr(self, 'last_quality_len'):
                delattr(self, 'last_quality_len')
            
            # Clear quality mode line references
            for attr in ['hr_line_q', 'spo2_line_q', 'accel_x_line_q', 'accel_y_line_q', 'accel_z_line_q', 'accel_mag_line_q']:
                if hasattr(self, attr):
                    delattr(self, attr)

            # Create new figure
            if self.current_mode == "QUALITY":
                self.fig, self.axes = plt.subplots(2, 3, figsize=(12, 8))
                self.fig.suptitle('Quality Assessment Monitor', fontsize=14, fontweight='bold')

                # Heart Rate
                self.ax_hr = self.axes[0, 0]
                self.ax_hr.set_title('Heart Rate (BPM)', fontweight='bold', color='red')
                self.ax_hr.set_ylabel('BPM')
                self.ax_hr.grid(True, alpha=0.3)
                self.hr_line, = self.ax_hr.plot([], [], 'r-', linewidth=2)

                # SpO2
                self.ax_spo2 = self.axes[0, 1]
                self.ax_spo2.set_title('Blood Oxygen (SpO2)', fontweight='bold', color='blue')
                self.ax_spo2.set_ylabel('SpO2 (%)')
                self.ax_spo2.grid(True, alpha=0.3)
                self.spo2_line, = self.ax_spo2.plot([], [], 'b-', linewidth=2)

                # Quality Assessment
                self.ax_quality = self.axes[0, 2]
                self.ax_quality.set_title('ML Quality Assessment', fontweight='bold', color='orange')
                self.ax_quality.set_ylabel('Quality (0=Poor, 1=Good)')
                self.ax_quality.grid(True, alpha=0.3)
                self.ax_quality.set_ylim(-0.1, 1.1)

                # Accelerometer X/Y/Z
                self.ax_accel = self.axes[1, 0]
                self.ax_accel.set_title('Accelerometer (X,Y,Z)', fontweight='bold', color='green')
                self.ax_accel.set_ylabel('Acceleration (g)')
                self.ax_accel.set_xlabel('Time (s)')
                self.ax_accel.grid(True, alpha=0.3)
                self.accel_x_line, = self.ax_accel.plot([], [], 'r-', label='X', linewidth=1)
                self.accel_y_line, = self.ax_accel.plot([], [], 'g-', label='Y', linewidth=1)
                self.accel_z_line, = self.ax_accel.plot([], [], 'b-', label='Z', linewidth=1)
                self.ax_accel.legend()

                # Acceleration Magnitude
                self.ax_accel_mag = self.axes[1, 1]
                self.ax_accel_mag.set_title('Acceleration Magnitude', fontweight='bold', color='purple')
                self.ax_accel_mag.set_ylabel('|Acceleration| (g)')
                self.ax_accel_mag.set_xlabel('Time (s)')
                self.ax_accel_mag.grid(True, alpha=0.3)
                self.accel_mag_line, = self.ax_accel_mag.plot([], [], 'purple', linewidth=2)

                # Quality Statistics
                self.ax_stats = self.axes[1, 2]
                self.ax_stats.set_title('Quality Statistics', fontweight='bold', color='black')
                self.ax_stats.axis('off')

            else:
                self.fig, self.axes = plt.subplots(2, 2, figsize=(10, 6))
                self.fig.suptitle('Sensor Data', fontsize=14, fontweight='bold')

                # HR/SpO2
                self.ax_hr = self.axes[0, 0]
                self.ax_hr.set_title('Heart Rate & SpO2', fontsize=10)
                self.ax_hr.set_ylabel('HR (bpm) / SpO2 (%)')
                self.ax_hr.grid(True, alpha=0.3)
                self.hr_line, = self.ax_hr.plot([], [], 'r-', label='HR', linewidth=2)
                self.spo2_line, = self.ax_hr.plot([], [], 'b-', label='SpO2', linewidth=2)
                self.ax_hr.legend()

                # Temperature
                self.ax_spo2 = self.axes[0, 1]  # Reusing ax_spo2 for temperature
                self.ax_spo2.set_title('Temperature', fontsize=10)
                self.ax_spo2.set_ylabel('Temperature (°C)')
                self.ax_spo2.grid(True, alpha=0.3)
                self.temp_line, = self.ax_spo2.plot([], [], 'g-', linewidth=2)

                # Force/IR/Red
                self.ax_quality = self.axes[1, 0]  # Reusing ax_quality for force/ir/red
                self.ax_quality.set_title('Force & IR/Red', fontsize=10)
                self.ax_quality.set_ylabel('Force (ADC) / IR/Red')
                self.ax_quality.grid(True, alpha=0.3)
                self.force_line, = self.ax_quality.plot([], [], 'm-', label='Force', linewidth=2)
                self.ir_line, = self.ax_quality.plot([], [], 'c-', label='IR', linewidth=2)
                self.red_line, = self.ax_quality.plot([], [], 'y-', label='Red', linewidth=2)
                self.ax_quality.legend()

                # Accelerometer
                self.ax_accel = self.axes[1, 1]
                self.ax_accel.set_title('Accelerometer', fontsize=10)
                self.ax_accel.set_ylabel('Acceleration (g)')
                self.ax_accel.grid(True, alpha=0.3)
                self.accel_x_line, = self.ax_accel.plot([], [], 'r-', label='X', linewidth=2)
                self.accel_y_line, = self.ax_accel.plot([], [], 'g-', label='Y', linewidth=2)
                self.accel_z_line, = self.ax_accel.plot([], [], 'b-', label='Z', linewidth=2)
                self.ax_accel.legend()

            plt.tight_layout()

            # Embed plot
            self.canvas = FigureCanvasTkAgg(self.fig, self.root)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # Start animation with better performance settings
            self.ani = animation.FuncAnimation(self.fig, self.update_plots, interval=200, 
                                             cache_frame_data=False, save_count=50, blit=False)

    def on_mode_change(self, event=None):
        """Handle mode change and update GUI"""
        with self.mode_lock:
            new_mode = self.mode_var.get()
            mode_names = {
                "hr_spo2": "HR/SpO2",
                "temperature": "Temperature",
                "force_test": "Force Test",
                "distance_test": "Distance Test",
                "quality": "Quality",
                "raw_data": "Raw Data"
            }
            self.current_mode = new_mode.upper()
            self.mode_label.config(text=mode_names.get(new_mode, new_mode))

            # Update CSV headers
            self.csv_headers = self.get_csv_headers(new_mode)

            # Update plots
            self.setup_plots()

            # Send mode command if connected
            if self.connected:
                asyncio.run_coroutine_threadsafe(self.send_mode_command(new_mode), self.loop)

    def get_csv_headers(self, mode):
        """Return CSV headers for the current mode"""
        headers = {
            "hr_spo2": ["Timestamp", "HeartRate", "SpO2", "AccelX", "AccelY", "AccelZ", "Device_Timestamp"],
            "temperature": ["Timestamp", "Temperature", "Device_Timestamp"],
            "force_test": ["Timestamp", "IR", "Red", "FSR", "Label", "Device_Timestamp"],
            "distance_test": ["Timestamp", "IR", "Red", "LED", "Distance_mm", "Device_Timestamp"],
            "quality": ["Timestamp", "HeartRate", "SpO2", "Quality", "QualityPercent", "AccelX", "AccelY", "AccelZ", "AccelMag", "Device_Timestamp"],
            "raw_data": ["Timestamp", "HeartRate", "SpO2", "IR", "Red", "AccelX", "AccelY", "AccelZ", "Device_Timestamp"]
        }
        return headers.get(mode, ["Timestamp", "Data"])

    def connect_device(self):
        """Initiate BLE connection"""
        self.connect_btn.config(state=tk.DISABLED)
        self.connection_label.config(text="Connecting...", fg='#f39c12')
        asyncio.run_coroutine_threadsafe(self.async_connect(), self.loop)

    async def async_connect(self):
        """Async BLE connection"""
        try:
            print(f"Scanning for {BLE_CONFIG['device_name']}...")
            devices = await BleakScanner.discover(timeout=10)
            target = None
            for device in devices:
                if device.name and BLE_CONFIG["device_name"] in device.name:
                    target = device
                    break

            if not target:
                print(f"Device {BLE_CONFIG['device_name']} not found")
                self.root.after(0, self.on_connect_failure)
                return

            print(f"Found: {target.name} @ {target.address}")
            self.client = BleakClient(target.address)
            await self.client.connect()

            # Start notifications
            await self.client.start_notify(BLE_CONFIG["characteristics"]["data"], self.handle_data)
            await self.client.start_notify(BLE_CONFIG["characteristics"]["status"], self.handle_status)

            # Send initial mode command
            await self.send_mode_command(self.mode_var.get())
            self.connected = True
            self.root.after(0, self.on_connect_success)

        except Exception as e:
            print(f"Connection failed: {e}")
            self.root.after(0, self.on_connect_failure)

    def on_connect_success(self):
        """Handle successful connection"""
        self.connection_label.config(text="Connected", fg='#27ae60')
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)

    def on_connect_failure(self):
        """Handle connection failure"""
        self.connection_label.config(text="Disconnected", fg='#e74c3c')
        self.connect_btn.config(state=tk.NORMAL)
        messagebox.showerror("Error", "Failed to connect. Check device is on and in range.")

    def disconnect_device(self):
        """Initiate BLE disconnection"""
        self.disconnect_btn.config(state=tk.DISABLED)
        asyncio.run_coroutine_threadsafe(self.async_disconnect(), self.loop)

    async def async_disconnect(self):
        """Async BLE disconnection"""
        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
            self.connected = False
            self.root.after(0, self.on_disconnect_success)
        except Exception as e:
            print(f"Disconnect error: {e}")

    def on_disconnect_success(self):
        """Handle successful disconnection"""
        self.client = None
        self.connection_label.config(text="Disconnected", fg='#e74c3c')
        self.disconnect_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        for buffer in self.data_buffers.values():
            buffer.clear()
        self.total_samples = 0
        self.good_samples = 0

    def start_recording(self):
        """Start CSV logging"""
        self.setup_csv_logging()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        if self.current_mode in ["FORCE_TEST", "DISTANCE_TEST"]:
            asyncio.run_coroutine_threadsafe(self.send_start_command(), self.loop)

    def stop_recording(self):
        """Stop CSV logging"""
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    async def send_start_command(self):
        """Send start command for FORCE_TEST or DISTANCE_TEST"""
        try:
            if self.client and self.client.is_connected:
                command = "LABEL:recording" if self.current_mode == "FORCE_TEST" else "START:ir:0"
                await self.client.write_gatt_char(BLE_CONFIG["characteristics"]["control"], command.encode())
        except Exception as e:
            print(f"Start command error: {e}")

    def setup_csv_logging(self):
        """Setup CSV logging"""
        mode = self.mode_var.get()
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self.export_dir / f"{mode}_data_{timestamp}.csv"
        self.export_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.csv_file = open(filename, mode='w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(self.csv_headers)
            print(f"CSV logging started: {filename}")
        except Exception as e:
            print(f"CSV setup error: {e}")
            messagebox.showerror("Error", f"Failed to setup CSV: {e}")

    def handle_status(self, characteristic, data):
        """Handle status updates from ESP32"""
        try:
            status = json.loads(data.decode())
            mode = status.get("mode", "IDLE")
            print(f"Status: {status}")
            
            # Use after_idle for thread-safe GUI updates
            if mode != self.current_mode:
                print(f"Mode mismatch: expected {self.current_mode}, got {mode}")
                self.root.after_idle(lambda: self._update_mode_safe(mode))
                
        except Exception as e:
            print(f"Status parse error: {e}")
    
    def _update_mode_safe(self, mode):
        """Update mode safely in the main GUI thread"""
        self.current_mode = mode
        self.mode_label.config(text=mode)
        self.setup_plots()

    def handle_data(self, characteristic, data):
        """Handle incoming BLE data"""
        try:
            obj = json.loads(data.decode())
            print(f"Received JSON: {obj}")
            
            # Use after_idle to safely update GUI from BLE thread
            self.root.after_idle(lambda: self._process_data_safe(obj))
            
        except Exception as e:
            print(f"Data receive error: {e}")
    
    def _process_data_safe(self, obj):
        """Process data safely in the main GUI thread"""
        with self.mode_lock:
            try:
                timestamp = time.time()
                device_ts = obj.get("timestamp", 0)

                if self.current_mode == "IDLE":
                    self.data_label.config(text="Idle")
                    return

                data_values = []

                if self.current_mode == "HR_SPO2":
                    if all(k in obj for k in ["hr", "spo2", "ax", "ay", "az"]):
                        self.data_buffers['hr'].append(float(obj["hr"]))
                        self.data_buffers['spo2'].append(float(obj["spo2"]))
                        self.data_buffers['accel_x'].append(float(obj["ax"]))
                        self.data_buffers['accel_y'].append(float(obj["ay"]))
                        self.data_buffers['accel_z'].append(float(obj["az"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.data_label.config(text=f"HR: {obj['hr']:.1f} bpm, SpO2: {obj['spo2']:.1f}%")
                        data_values = [obj["hr"], obj["spo2"], obj["ax"], obj["ay"], obj["az"], device_ts]
                    else:
                        print("Missing hr, spo2, or accel data")
                        return

                elif self.current_mode == "TEMPERATURE":
                    if "temperature" in obj:
                        self.data_buffers['temperature'].append(float(obj["temperature"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.data_label.config(text=f"Temp: {obj['temperature']:.1f}°C")
                        data_values = [obj["temperature"], device_ts]
                    else:
                        print("Missing temperature data")
                        return

                elif self.current_mode == "FORCE_TEST":
                    if all(k in obj for k in ["ir", "red", "fsr", "label"]):
                        self.data_buffers['ir'].append(float(obj["ir"]))
                        self.data_buffers['red'].append(float(obj["red"]))
                        self.data_buffers['force'].append(float(obj["fsr"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.data_label.config(text=f"Force: {obj['fsr']:.0f}, Label: {obj['label']}")
                        data_values = [obj["ir"], obj["red"], obj["fsr"], obj["label"], device_ts]
                    else:
                        print("Missing ir, red, fsr, or label")
                        return

                elif self.current_mode == "DISTANCE_TEST":
                    if all(k in obj for k in ["ir", "red", "led", "distance_mm"]):
                        self.data_buffers['ir'].append(float(obj["ir"]))
                        self.data_buffers['red'].append(float(obj["red"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.data_label.config(text=f"IR: {obj['ir']:.0f}, Red: {obj['red']:.0f}, Distance: {obj['distance_mm']}mm")
                        data_values = [obj["ir"], obj["red"], obj["led"], obj["distance_mm"], device_ts]
                    else:
                        print("Missing ir, red, led, or distance_mm")
                        return

                elif self.current_mode == "QUALITY":
                    if all(k in obj for k in ["hr", "spo2", "quality", "quality_percent", "ax", "ay", "az", "accel_mag"]):
                        self.data_buffers['hr'].append(float(obj["hr"]))
                        self.data_buffers['spo2'].append(float(obj["spo2"]))
                        self.data_buffers['quality'].append(float(obj["quality"]))
                        self.data_buffers['accel_x'].append(float(obj["ax"]))
                        self.data_buffers['accel_y'].append(float(obj["ay"]))
                        self.data_buffers['accel_z'].append(float(obj["az"]))
                        self.data_buffers['accel_mag'].append(float(obj["accel_mag"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.total_samples += 1
                        if obj["quality"] == 1:
                            self.good_samples += 1
                        self.data_label.config(text=f"HR: {obj['hr']:.1f}, SpO2: {obj['spo2']:.1f}, Quality: {obj['quality']}")
                        data_values = [obj["hr"], obj["spo2"], obj["quality"], obj["quality_percent"], obj["ax"], obj["ay"], obj["az"], obj["accel_mag"], device_ts]
                    else:
                        print("Missing hr, spo2, quality, or accel data")
                        return

                elif self.current_mode == "RAW_DATA":
                    if all(k in obj for k in ["hr", "spo2", "ir", "red", "ax", "ay", "az"]):
                        self.data_buffers['hr'].append(float(obj["hr"]))
                        self.data_buffers['spo2'].append(float(obj["spo2"]))
                        self.data_buffers['ir'].append(float(obj["ir"]))
                        self.data_buffers['red'].append(float(obj["red"]))
                        self.data_buffers['accel_x'].append(float(obj["ax"]))
                        self.data_buffers['accel_y'].append(float(obj["ay"]))
                        self.data_buffers['accel_z'].append(float(obj["az"]))
                        self.data_buffers['timestamps'].append(timestamp)
                        self.data_label.config(text=f"HR: {obj['hr']:.1f}, IR: {obj['ir']:.0f}, Red: {obj['red']:.0f}")
                        data_values = [obj["hr"], obj["spo2"], obj["ir"], obj["red"], obj["ax"], obj["ay"], obj["az"], device_ts]
                    else:
                        print("Missing hr, spo2, ir, red, or accel data")
                        return

                # Write to CSV
                if self.csv_writer:
                    self.csv_writer.writerow([datetime.datetime.now().isoformat()] + data_values)
                    self.csv_file.flush()

            except Exception as e:
                print(f"Data parse error: {e}")

    async def send_mode_command(self, mode):
        """Send mode command to ESP32"""
        try:
            if self.client and self.client.is_connected:
                mode_map = {
                    "hr_spo2": "MODE:HR_SPO2",
                    "temperature": "MODE:TEMPERATURE",
                    "force_test": "MODE:FORCE_TEST",
                    "distance_test": "MODE:DISTANCE_TEST",
                    "quality": "MODE:QUALITY",
                    "raw_data": "MODE:RAW_DATA"
                }
                command = mode_map.get(mode, "MODE:IDLE")
                await self.client.write_gatt_char(BLE_CONFIG["characteristics"]["control"], command.encode())
                await asyncio.sleep(3)  # Increased delay for ESP32 stabilization
        except Exception as e:
            print(f"Mode command error: {e}")

    def update_plots(self, frame):
        """Update real-time plots"""
        # Check if GUI is still alive
        if not self.root.winfo_exists():
            return
            
        with self.mode_lock:
            try:
                if len(self.data_buffers['timestamps']) < 2:
                    return []

                timestamps = list(self.data_buffers['timestamps'])
                time_range = [t - timestamps[0] for t in timestamps]

                if self.current_mode == "QUALITY":
                    # Update Heart Rate more efficiently
                    if hasattr(self, 'hr_line_q'):
                        self.hr_line_q.set_data(time_range[-len(self.data_buffers['hr']):], self.data_buffers['hr'])
                    else:
                        self.ax_hr.clear()
                        self.hr_line_q, = self.ax_hr.plot(time_range[-len(self.data_buffers['hr']):], self.data_buffers['hr'], 'r-', linewidth=2)
                        self.ax_hr.set_title('Heart Rate (BPM)', fontweight='bold', color='red')
                        self.ax_hr.set_ylabel('BPM')
                        self.ax_hr.grid(True, alpha=0.3)

                    # Update SpO2 more efficiently
                    if hasattr(self, 'spo2_line_q'):
                        self.spo2_line_q.set_data(time_range[-len(self.data_buffers['spo2']):], self.data_buffers['spo2'])
                    else:
                        self.ax_spo2.clear()
                        self.spo2_line_q, = self.ax_spo2.plot(time_range[-len(self.data_buffers['spo2']):], self.data_buffers['spo2'], 'b-', linewidth=2)
                        self.ax_spo2.set_title('Blood Oxygen (SpO2)', fontweight='bold', color='blue')
                        self.ax_spo2.set_ylabel('SpO2 (%)')
                        self.ax_spo2.grid(True, alpha=0.3)

                    # Update Quality Assessment - only clear when necessary
                    if len(self.data_buffers['quality']) > 0:
                        if not hasattr(self, 'last_quality_len') or len(self.data_buffers['quality']) != self.last_quality_len:
                            self.ax_quality.clear()
                            quality_colors = ['red' if q == 0 else 'green' for q in self.data_buffers['quality']]
                            self.ax_quality.scatter(time_range[-len(self.data_buffers['quality']):], self.data_buffers['quality'],
                                                    c=quality_colors, s=50, alpha=0.7)
                            self.ax_quality.set_title('ML Quality Assessment', fontweight='bold', color='orange')
                            self.ax_quality.set_ylabel('Quality (0=Poor, 1=Good)')
                            self.ax_quality.grid(True, alpha=0.3)
                            self.ax_quality.set_ylim(-0.1, 1.1)
                            self.last_quality_len = len(self.data_buffers['quality'])

                    # Update Accelerometer more efficiently
                    if hasattr(self, 'accel_x_line_q') and len(self.data_buffers['accel_x']) > 0:
                        accel_range = time_range[-len(self.data_buffers['accel_x']):]
                        self.accel_x_line_q.set_data(accel_range, self.data_buffers['accel_x'])
                        self.accel_y_line_q.set_data(accel_range, self.data_buffers['accel_y'])
                        self.accel_z_line_q.set_data(accel_range, self.data_buffers['accel_z'])
                    else:
                        self.ax_accel.clear()
                        accel_range = time_range[-len(self.data_buffers['accel_x']):]
                        self.accel_x_line_q, = self.ax_accel.plot(accel_range, self.data_buffers['accel_x'], 'r-', label='X', linewidth=1)
                        self.accel_y_line_q, = self.ax_accel.plot(accel_range, self.data_buffers['accel_y'], 'g-', label='Y', linewidth=1)
                        self.accel_z_line_q, = self.ax_accel.plot(accel_range, self.data_buffers['accel_z'], 'b-', label='Z', linewidth=1)
                        self.ax_accel.set_title('Accelerometer (X,Y,Z)', fontweight='bold', color='green')
                        self.ax_accel.set_ylabel('Acceleration (g)')
                        self.ax_accel.set_xlabel('Time (s)')
                        self.ax_accel.grid(True, alpha=0.3)
                        self.ax_accel.legend()

                    # Update Acceleration Magnitude more efficiently
                    if hasattr(self, 'accel_mag_line_q') and len(self.data_buffers['accel_mag']) > 0:
                        self.accel_mag_line_q.set_data(time_range[-len(self.data_buffers['accel_mag']):], self.data_buffers['accel_mag'])
                    else:
                        self.ax_accel_mag.clear()
                        self.accel_mag_line_q, = self.ax_accel_mag.plot(time_range[-len(self.data_buffers['accel_mag']):], self.data_buffers['accel_mag'], 'purple', linewidth=2)
                        self.ax_accel_mag.set_title('Acceleration Magnitude', fontweight='bold', color='purple')
                        self.ax_accel_mag.set_ylabel('|Acceleration| (g)')
                        self.ax_accel_mag.set_xlabel('Time (s)')
                        self.ax_accel_mag.grid(True, alpha=0.3)

                    # Update Quality Statistics - only update every 10 frames to reduce overhead
                    if not hasattr(self, 'stats_update_counter'):
                        self.stats_update_counter = 0
                    
                    if self.stats_update_counter % 10 == 0:  # Update stats every 2 seconds (200ms * 10)
                        self.ax_stats.clear()
                        self.ax_stats.set_title('Quality Statistics', fontweight='bold', color='black')
                        self.ax_stats.axis('off')
                        if self.total_samples > 0:
                            quality_pct = (self.good_samples / self.total_samples) * 100
                            current_hr = self.data_buffers['hr'][-1] if self.data_buffers['hr'] else 0
                            current_spo2 = self.data_buffers['spo2'][-1] if self.data_buffers['spo2'] else 0
                            current_accel = self.data_buffers['accel_mag'][-1] if self.data_buffers['accel_mag'] else 0
                            current_quality = "GOOD" if self.data_buffers['quality'][-1] == 1 else "POOR"
                            stats_text = f"""CURRENT VALUES:
Heart Rate: {current_hr:.1f} BPM
SpO2: {current_spo2:.1f}%
Accel Mag: {current_accel:.3f}g
Quality: {current_quality}

STATISTICS:
Total Samples: {self.total_samples}
Good Samples: {self.good_samples}
Overall Quality: {quality_pct:.1f}%
Runtime: {time_range[-1]:.1f}s
"""
                            self.ax_stats.text(0.05, 0.95, stats_text, transform=self.ax_stats.transAxes,
                                               fontsize=9, verticalalignment='top', fontfamily='monospace',
                                               bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
                    
                    self.stats_update_counter += 1
                    
                    # Auto-scale axes less frequently
                    if self.stats_update_counter % 5 == 0:  # Every 1 second
                        self.ax_hr.relim()
                        self.ax_hr.autoscale_view()
                        self.ax_spo2.relim() 
                        self.ax_spo2.autoscale_view()
                        self.ax_accel.relim()
                        self.ax_accel.autoscale_view()
                        self.ax_accel_mag.relim()
                        self.ax_accel_mag.autoscale_view()

                else:
                    # Initialize frame counter for less frequent axis updates
                    if not hasattr(self, 'regular_update_counter'):
                        self.regular_update_counter = 0
                    
                    # HR/SpO2
                    if len(self.data_buffers['hr']) > 0:
                        self.hr_line.set_data(time_range[-len(self.data_buffers['hr']):], self.data_buffers['hr'])
                        self.spo2_line.set_data(time_range[-len(self.data_buffers['spo2']):], self.data_buffers['spo2'])
                        
                        # Only update axis scaling every 10 frames (2 seconds)
                        if self.regular_update_counter % 10 == 0:
                            self.ax_hr.relim()
                            self.ax_hr.autoscale_view()

                    # Temperature
                    if len(self.data_buffers['temperature']) > 0:
                        self.temp_line.set_data(time_range[-len(self.data_buffers['temperature']):], self.data_buffers['temperature'])
                        
                        if self.regular_update_counter % 10 == 0:
                            self.ax_spo2.relim()
                            self.ax_spo2.autoscale_view()

                    # Force/IR/Red
                    if len(self.data_buffers['force']) > 0 or len(self.data_buffers['ir']) > 0:
                        if len(self.data_buffers['force']) > 0:
                            self.force_line.set_data(time_range[-len(self.data_buffers['force']):], self.data_buffers['force'])
                        if len(self.data_buffers['ir']) > 0:
                            self.ir_line.set_data(time_range[-len(self.data_buffers['ir']):], self.data_buffers['ir'])
                            self.red_line.set_data(time_range[-len(self.data_buffers['red']):], self.data_buffers['red'])
                        
                        if self.regular_update_counter % 10 == 0:
                            self.ax_quality.relim()
                            self.ax_quality.autoscale_view()

                    # Accelerometer
                    if len(self.data_buffers['accel_x']) > 0:
                        accel_range = time_range[-len(self.data_buffers['accel_x']):]
                        self.accel_x_line.set_data(accel_range, self.data_buffers['accel_x'])
                        self.accel_y_line.set_data(accel_range, self.data_buffers['accel_y'])
                        self.accel_z_line.set_data(accel_range, self.data_buffers['accel_z'])
                        
                        if self.regular_update_counter % 10 == 0:
                            self.ax_accel.relim()
                            self.ax_accel.autoscale_view()
                    
                    self.regular_update_counter += 1

                # Only draw if canvas is still valid
                if self.canvas and hasattr(self.canvas, 'get_tk_widget'):
                    try:
                        self.canvas.draw_idle()  # Use draw_idle() instead of draw() for better performance
                    except Exception as draw_error:
                        print(f"Canvas draw error: {draw_error}")

            except Exception as e:
                print(f"Plot update error: {e}")
            
            return []  # Return empty list for blitting compatibility

    def cleanup(self):
        """Cleanup resources"""
        print("Starting cleanup...")
        try:
            # Stop animation first
            if self.ani:
                self.ani.event_source.stop()
                self.ani = None
                
            # Close CSV file
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
                
            # Disconnect BLE
            if self.client and hasattr(self.client, 'is_connected'):
                try:
                    if self.client.is_connected:
                        asyncio.run_coroutine_threadsafe(self.async_disconnect(), self.loop)
                        time.sleep(1)  # Give time for disconnect
                except:
                    pass
                    
            # Stop async loop
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
                
            # Join thread
            if self.async_thread and self.async_thread.is_alive():
                self.async_thread.join(timeout=2)
                
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        print("Cleanup completed.")

def main():
    try:
        root = tk.Tk()
        app = SimplifiedDashboard(root)
        
        def safe_exit():
            try:
                app.cleanup()
                root.quit()
                root.destroy()
            except Exception as e:
                print(f"Exit error: {e}")
                root.destroy()
        
        root.protocol("WM_DELETE_WINDOW", safe_exit)
        root.mainloop()
        
    except Exception as e:
        print(f"Main error: {e}")
    finally:
        print("Application terminated.")

if __name__ == "__main__":
    main()