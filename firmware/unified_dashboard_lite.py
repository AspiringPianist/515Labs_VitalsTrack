import asyncio
import csv
import datetime
import json
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque
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

class LightweightDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("VitalsTrack Lightweight Dashboard")
        self.root.geometry("800x600")
        self.root.configure(bg='#2c3e50')

        # Asyncio event loop
        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.async_thread.start()

        # Connection state
        self.client = None
        self.connected = False
        self.current_mode = "IDLE"

        # Data buffers
        self.data_buffer = deque(maxlen=100)  # Single buffer for primary data
        self.timestamps = deque(maxlen=100)   # Timestamps for plotting

        # CSV logging
        self.csv_file = None
        self.csv_writer = None
        self.csv_headers = []
        self.export_dir = Path("../test_logs")

        # GUI elements
        self.setup_gui()
        self.setup_plot()

        # Periodic GUI updates
        self.root.after(100, self.update_gui)

    def run_async_loop(self):
        """Run asyncio event loop in a separate thread"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def setup_gui(self):
        """Setup the simplified GUI"""
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Title
        tk.Label(main_frame, text="VitalsTrack Dashboard", font=('Arial', 18, 'bold'),
                 fg='#ecf0f1', bg='#2c3e50').pack(pady=(0, 10))

        # Control panel
        control_frame = tk.LabelFrame(main_frame, text="Controls", font=('Arial', 12, 'bold'),
                                     fg='#ecf0f1', bg='#34495e')
        control_frame.pack(fill=tk.X, pady=(0, 10))

        # Mode selection
        tk.Label(control_frame, text="Mode:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(10, 5))
        self.mode_var = tk.StringVar(value="HR_SPO2")
        mode_combo = ttk.Combobox(control_frame, textvariable=self.mode_var,
                                  values=["HR_SPO2", "TEMPERATURE", "FORCE_TEST", "DISTANCE_TEST", "QUALITY", "RAW_DATA"],
                                  state="readonly", font=('Arial', 10), width=15)
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        mode_combo.bind('<<ComboboxSelected>>', self.on_mode_change)

        # Connect/Disconnect buttons
        self.connect_btn = tk.Button(control_frame, text="Connect", command=self.connect_device,
                                     bg='#27ae60', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.disconnect_btn = tk.Button(control_frame, text="Disconnect", command=self.disconnect_device,
                                        bg='#e74c3c', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Start/Stop recording buttons
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

        tk.Label(status_frame, text="Data:", font=('Arial', 10, 'bold'),
                 fg='#ecf0f1', bg='#34495e').pack(side=tk.LEFT, padx=(0, 5))
        self.data_label = tk.Label(status_frame, text="N/A", font=('Arial', 10),
                                   fg='#f39c12', bg='#34495e')
        self.data_label.pack(side=tk.LEFT)

    def setup_plot(self):
        """Setup a single matplotlib plot"""
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor('#ecf0f1')
        self.ax.set_title('Sensor Data', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('Time (s)')
        self.ax.grid(True, alpha=0.3)
        self.line, = self.ax.plot([], [], 'b-', label='Data', linewidth=2)
        self.ax.legend()

        # Embed plot in Tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def on_mode_change(self, event=None):
        """Handle mode change and update plot labels"""
        new_mode = self.mode_var.get()
        # Clear buffers when changing modes to avoid data mixing
        self.data_buffer.clear()
        self.timestamps.clear()
        
        # Add delay between mode switches to allow sensor reinitialization
        if self.connected:
            self.data_label.config(text="Switching mode...")
            self.root.update()
            time.sleep(1.5)  # Give device time for thorough reset sequence
            
        self.current_mode = new_mode
        mode_labels = {
            "HR_SPO2": ("Heart Rate (bpm)", ["HeartRate", "SpO2"]),
            "TEMPERATURE": ("Temperature (°C)", ["Temperature"]),
            "FORCE_TEST": ("Force (ADC)", ["FSR"]),
            "DISTANCE_TEST": ("IR/Red Values", ["IR", "Red"]),
            "QUALITY": ("Heart Rate (bpm)", ["HeartRate", "SpO2", "Quality"]),
            "RAW_DATA": ("Raw Values", ["IR", "Red"])
        }
        ylabel, self.csv_headers = mode_labels.get(self.current_mode, ("Data", []))
        self.ax.set_ylabel(ylabel)
        self.ax.set_title(f"{self.current_mode} Data")
        self.canvas.draw()
        if self.connected:
            asyncio.run_coroutine_threadsafe(self.send_mode_command(self.current_mode), self.loop)

    def connect_device(self):
        """Initiate BLE connection"""
        self.connect_btn.config(state=tk.DISABLED)
        self.connection_label.config(text="Connecting...", fg='#f39c12')
        asyncio.run_coroutine_threadsafe(self.async_connect(), self.loop)

    async def async_connect(self):
        """Async BLE connection with retry mechanism"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                print(f"Scanning for {BLE_CONFIG['device_name']}... (Attempt {retry_count + 1}/{max_retries})")
                devices = await BleakScanner.discover(timeout=5)
                target = None
                for device in devices:
                    if device.name and BLE_CONFIG["device_name"] in device.name:
                        target = device
                        break

                if not target:
                    print(f"Device {BLE_CONFIG['device_name']} not found")
                    retry_count += 1
                    if retry_count < max_retries:
                        print("Retrying...")
                        await asyncio.sleep(2)
                        continue
                    self.root.after(0, self.on_connect_failure)
                    return
                    
                print(f"Found: {target.name} @ {target.address}")
                self.client = BleakClient(target.address)
                await self.client.connect()
                
                # Start notifications
                await self.client.start_notify(BLE_CONFIG["characteristics"]["data"], self.handle_data)
                
                # Send initial mode command
                await self.send_mode_command(self.current_mode)
                self.connected = True
                self.root.after(0, self.on_connect_success)
                return  # Successfully connected
                
            except Exception as e:
                print(f"Connection attempt {retry_count + 1} failed: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    print("Retrying...")
                    await asyncio.sleep(2)
                else:
                    self.root.after(0, self.on_connect_failure)
                    return

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
        mode = self.current_mode
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self.export_dir / f"{mode.lower()}_data_{timestamp}.csv"
        self.export_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.csv_file = open(filename, mode='w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            headers = ["Timestamp"] + self.csv_headers + ["Device_Timestamp"]
            self.csv_writer.writerow(headers)
            print(f"CSV logging started: {filename}")
        except Exception as e:
            print(f"CSV setup error: {e}")
            messagebox.showerror("Error", f"Failed to setup CSV: {e}")

    def handle_data(self, characteristic, data):
        """Handle incoming BLE data with improved error handling"""
        try:
            obj = json.loads(data.decode())
            print(f"Received JSON: {obj}")  # Debug output
            timestamp = time.time()
            device_ts = obj.get("timestamp", 0)
            data_values = []
            
            # Check for error messages or status updates
            if "error" in obj:
                print(f"Device error: {obj['error']}")
                self.data_label.config(text=f"Error: {obj['error']}", fg='#e74c3c')
                return
                
            if "status" in obj and obj["status"] != "ready":
                self.data_label.config(text=f"Status: {obj['status']}")
                return

            if self.current_mode == "IDLE":
                self.data_label.config(text="Idle")
                return  # Skip processing idle mode data

            if self.current_mode == "HR_SPO2":
                if "hr" in obj and "spo2" in obj:
                    data_values = [float(obj.get("hr", 0)), float(obj.get("spo2", 0))]
                    self.data_label.config(text=f"HR: {obj.get('hr', 0)} bpm, SpO2: {obj.get('spo2', 0)}%")
                else:
                    print("Missing hr or spo2 in HR_SPO2 data")
                    return
            elif self.current_mode == "TEMPERATURE":
                if "temperature" in obj:
                    data_values = [float(obj.get("temperature", 0))]
                    self.data_label.config(text=f"Temp: {obj.get('temperature', 0):.1f}°C")
                else:
                    print("Missing temperature in TEMPERATURE data")
                    return
            elif self.current_mode == "FORCE_TEST":
                if "fsr" in obj:
                    data_values = [float(obj.get("fsr", 0))]
                    self.data_label.config(text=f"Force: {obj.get('fsr', 0)}")
                else:
                    print("Missing fsr in FORCE_TEST data")
                    return
            elif self.current_mode == "DISTANCE_TEST":
                if "ir" in obj and "red" in obj:
                    data_values = [float(obj.get("ir", 0)), float(obj.get("red", 0))]
                    self.data_label.config(text=f"IR: {obj.get('ir', 0)}, Red: {obj.get('red', 0)}")
                else:
                    print("Missing ir or red in DISTANCE_TEST data")
                    return
            elif self.current_mode == "QUALITY":
                if "hr" in obj and "spo2" in obj and "quality" in obj:
                    data_values = [float(obj.get("hr", 0)), float(obj.get("spo2", 0)), float(obj.get("quality", 0))]
                    self.data_label.config(text=f"HR: {obj.get('hr', 0)} bpm, SpO2: {obj.get('spo2', 0)}%, Quality: {obj.get('quality', 0)}")
                else:
                    print("Missing hr, spo2, or quality in QUALITY data")
                    return
            elif self.current_mode == "RAW_DATA":
                if "ir" in obj and "red" in obj:
                    data_values = [float(obj.get("ir", 0)), float(obj.get("red", 0))]
                    self.data_label.config(text=f"IR: {obj.get('ir', 0)}, Red: {obj.get('red', 0)}")
                else:
                    print("Missing ir or red in RAW_DATA data")
                    return

            if data_values:  # Only append if data_values is not empty
                self.data_buffer.append(data_values)
                self.timestamps.append(timestamp)
                if self.csv_writer:
                    self.csv_writer.writerow([datetime.datetime.now().isoformat()] + data_values + [device_ts])
                    self.csv_file.flush()
            else:
                print("No valid data to append")

        except Exception as e:
            print(f"Data parse error: {e}")

    async def send_mode_command(self, mode):
        """Send mode command to ESP32"""
        try:
            if self.client and self.client.is_connected:
                command = f"MODE:{mode}"
                await self.client.write_gatt_char(BLE_CONFIG["characteristics"]["control"], command.encode())
                await asyncio.sleep(1)  # Wait for mode switch
        except Exception as e:
            print(f"Mode command error: {e}")

    def update_gui(self):
        """Update plot and GUI elements with improved multi-data handling"""
        try:
            if len(self.timestamps) > 1 and len(self.data_buffer) > 1:
                time_range = [t - self.timestamps[0] for t in self.timestamps]
                
                # Clear previous lines
                self.ax.clear()
                self.ax.grid(True, alpha=0.3)
                
                # Plot based on mode
                if self.current_mode in ["HR_SPO2", "QUALITY"]:
                    hr_data = [v[0] for v in self.data_buffer if len(v) > 0]
                    spo2_data = [v[1] for v in self.data_buffer if len(v) > 1]
                    if hr_data:
                        self.ax.plot(time_range[:len(hr_data)], hr_data, 'b-', label='Heart Rate', linewidth=2)
                    if spo2_data:
                        self.ax.plot(time_range[:len(spo2_data)], spo2_data, 'r-', label='SpO2', linewidth=2)
                
                elif self.current_mode in ["DISTANCE_TEST", "RAW_DATA"]:
                    ir_data = [v[0] for v in self.data_buffer if len(v) > 0]
                    red_data = [v[1] for v in self.data_buffer if len(v) > 1]
                    if ir_data:
                        self.ax.plot(time_range[:len(ir_data)], ir_data, 'g-', label='IR', linewidth=2)
                    if red_data:
                        self.ax.plot(time_range[:len(red_data)], red_data, 'r-', label='Red', linewidth=2)
                
                else:  # Single value modes (TEMPERATURE, FORCE_TEST)
                    valid_data = [v[0] for v in self.data_buffer if len(v) > 0]
                    if valid_data:
                        self.ax.plot(time_range[:len(valid_data)], valid_data, 'b-', linewidth=2)
                
                # Update plot settings
                self.ax.set_title(f"{self.current_mode} Data")
                self.ax.legend()
                self.ax.relim()
                self.ax.autoscale_view()
                self.canvas.draw()
                
        except Exception as e:
            print(f"GUI update error: {e}")
        self.root.after(100, self.update_gui)

    def cleanup(self):
        """Cleanup resources"""
        if self.csv_file:
            self.csv_file.close()
        if self.client and self.client.is_connected:
            asyncio.run_coroutine_threadsafe(self.async_disconnect(), self.loop)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.async_thread.join()

def main():
    root = tk.Tk()
    app = LightweightDashboard(root)
    root.protocol("WM_DELETE_WINDOW", lambda: [app.cleanup(), root.destroy()])
    root.mainloop()

if __name__ == "__main__":
    main()