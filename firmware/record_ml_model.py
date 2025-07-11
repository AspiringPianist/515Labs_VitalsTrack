import asyncio
import json
import datetime
import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
import threading
import time
import queue
from bleak import BleakScanner, BleakClient

# === Settings ===
DEVICE_NAME_QUALITY = "ESP32_Quality_Monitor"
DEVICE_NAME_RAW = "ESP32_Raw_Collector"

# === BLE UUIDs ===
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
VITALS_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef3"
QUALITY_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef4"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"
RAW_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"

# === Global variables ===
ble_running = False
data_queue = queue.Queue()
command_queue = queue.Queue()

class QualityReceiver:
    def __init__(self, mode="quality", buffer_size=100):
        self.mode = mode
        self.buffer_size = buffer_size
        
        # Data buffers for plotting
        self.timestamps = deque(maxlen=buffer_size)
        self.heart_rates = deque(maxlen=buffer_size)
        self.spo2_values = deque(maxlen=buffer_size)
        self.ax_values = deque(maxlen=buffer_size)
        self.ay_values = deque(maxlen=buffer_size)
        self.az_values = deque(maxlen=buffer_size)
        self.accel_mag = deque(maxlen=buffer_size)
        self.quality_values = deque(maxlen=buffer_size)
        
        # Statistics
        self.total_samples = 0
        self.good_samples = 0
        self.current_label = "unlabeled"
        
        # Setup CSV
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        if mode == "quality":
            self.csv_filename = f"quality_data_{timestamp}.csv"
            self.csv_headers = ["Timestamp", "HR", "SpO2", "Ax", "Ay", "Az", "Quality", "Accel_Mag", "Device_Timestamp"]
        else:
            self.csv_filename = f"raw_data_{timestamp}.csv"
            self.csv_headers = ["Timestamp", "HR", "SpO2", "Ax", "Ay", "Az", "Label", "Device_Timestamp"]
        
        self.setup_csv()
        self.setup_plots()
    
    def setup_csv(self):
        """Initialize CSV file"""
        self.csv_file = open(self.csv_filename, mode='w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(self.csv_headers)
        print(f"CSV file created: {self.csv_filename}")
    
    def setup_plots(self):
        """Setup matplotlib plots"""
        plt.style.use('default')
        
        if self.mode == "quality":
            self.fig, self.axes = plt.subplots(2, 3, figsize=(15, 10))
            self.fig.suptitle('Real-time Vitals Monitor with ML Quality Assessment', 
                            fontsize=16, fontweight='bold')
            
            # Heart Rate plot
            self.ax_hr = self.axes[0, 0]
            self.ax_hr.set_title('Heart Rate (BPM)', fontweight='bold', color='red')
            self.ax_hr.set_ylabel('BPM')
            self.ax_hr.grid(True, alpha=0.3)
            
            # SpO2 plot
            self.ax_spo2 = self.axes[0, 1]
            self.ax_spo2.set_title('Blood Oxygen (SpO2)', fontweight='bold', color='blue')
            self.ax_spo2.set_ylabel('SpO2 (%)')
            self.ax_spo2.grid(True, alpha=0.3)
            
            # Quality Assessment plot
            self.ax_quality = self.axes[0, 2]
            self.ax_quality.set_title('ML Quality Assessment', fontweight='bold', color='orange')
            self.ax_quality.set_ylabel('Quality (0=Poor, 1=Good)')
            self.ax_quality.grid(True, alpha=0.3)
            
            # Accelerometer X,Y,Z
            self.ax_accel = self.axes[1, 0]
            self.ax_accel.set_title('Accelerometer (X,Y,Z)', fontweight='bold', color='green')
            self.ax_accel.set_ylabel('Acceleration (g)')
            self.ax_accel.set_xlabel('Time (s)')
            self.ax_accel.grid(True, alpha=0.3)
            
            # Accelerometer Magnitude
            self.ax_accel_mag = self.axes[1, 1]
            self.ax_accel_mag.set_title('Acceleration Magnitude', fontweight='bold', color='purple')
            self.ax_accel_mag.set_ylabel('|Acceleration| (g)')
            self.ax_accel_mag.set_xlabel('Time (s)')
            self.ax_accel_mag.grid(True, alpha=0.3)
            
            # Quality Statistics
            self.ax_stats = self.axes[1, 2]
            self.ax_stats.set_title('Quality Statistics', fontweight='bold', color='black')
            self.ax_stats.axis('off')
            
        else:
            # Raw mode: 2x2 subplot layout
            self.fig, self.axes = plt.subplots(2, 2, figsize=(12, 8))
            self.fig.suptitle('Raw Data Collection Monitor', fontsize=16, fontweight='bold')
            
            self.ax_hr = self.axes[0, 0]
            self.ax_hr.set_title('Heart Rate (BPM)', fontweight='bold', color='red')
            
            self.ax_spo2 = self.axes[0, 1]
            self.ax_spo2.set_title('Blood Oxygen (SpO2)', fontweight='bold', color='blue')
            
            self.ax_accel = self.axes[1, 0]
            self.ax_accel.set_title('Accelerometer', fontweight='bold', color='green')
            
            self.ax_label = self.axes[1, 1]
            self.ax_label.set_title('Current Label', fontweight='bold', color='orange')
            self.ax_label.axis('off')
        
        plt.tight_layout()
    
    def process_data_queue(self):
        """Process queued data from BLE thread"""
        while not data_queue.empty():
            try:
                data = data_queue.get_nowait()
                
                # Update plot data
                self.timestamps.append(time.time())
                self.heart_rates.append(data['hr'])
                self.spo2_values.append(data['spo2'])
                self.ax_values.append(data['ax'])
                self.ay_values.append(data['ay'])
                self.az_values.append(data['az'])
                self.accel_mag.append(data.get('accel_mag', 
                    np.sqrt(data['ax']**2 + data['ay']**2 + data['az']**2)))
                
                if self.mode == "quality":
                    self.quality_values.append(data['quality'])
                    self.total_samples += 1
                    if data['quality'] == 1:
                        self.good_samples += 1
                else:
                    self.current_label = data.get('label', 'unlabeled')
                
                # Save to CSV
                if self.mode == "quality":
                    self.csv_writer.writerow([
                        datetime.datetime.now().isoformat(),
                        data['hr'], data['spo2'],
                        data['ax'], data['ay'], data['az'],
                        data['quality'],
                        data.get('accel_mag', 0),
                        data['timestamp']
                    ])
                else:
                    self.csv_writer.writerow([
                        datetime.datetime.now().isoformat(),
                        data['hr'], data['spo2'],
                        data['ax'], data['ay'], data['az'],
                        data.get('label', 'unlabeled'),
                        data['timestamp']
                    ])
                
                self.csv_file.flush()
                
            except queue.Empty:
                break
    
    def update_plots(self, frame):
        """Update all plots with latest data"""
        # Process any new data from BLE thread
        self.process_data_queue()
        
        if len(self.timestamps) == 0:
            return
        
        # Convert timestamps to relative seconds for x-axis
        time_array = [t - self.timestamps[0] for t in self.timestamps]
        
        if self.mode == "quality":
            # Clear all axes
            for ax in [self.ax_hr, self.ax_spo2, self.ax_quality, self.ax_accel, self.ax_accel_mag]:
                ax.clear()
            
            # Heart Rate
            self.ax_hr.plot(time_array, list(self.heart_rates), 'r-', linewidth=2)
            self.ax_hr.set_title('Heart Rate (BPM)', fontweight='bold', color='red')
            self.ax_hr.set_ylabel('BPM')
            self.ax_hr.grid(True, alpha=0.3)
            
            # SpO2
            self.ax_spo2.plot(time_array, list(self.spo2_values), 'b-', linewidth=2)
            self.ax_spo2.set_title('Blood Oxygen (SpO2)', fontweight='bold', color='blue')
            self.ax_spo2.set_ylabel('SpO2 (%)')
            self.ax_spo2.grid(True, alpha=0.3)
            
            # Quality Assessment
            quality_colors = ['red' if q == 0 else 'green' for q in self.quality_values]
            self.ax_quality.scatter(time_array, list(self.quality_values), 
                                  c=quality_colors, s=50, alpha=0.7)
            self.ax_quality.set_title('ML Quality Assessment', fontweight='bold', color='orange')
            self.ax_quality.set_ylabel('Quality (0=Poor, 1=Good)')
            self.ax_quality.grid(True, alpha=0.3)
            self.ax_quality.set_ylim(-0.1, 1.1)
            
            # Accelerometer X,Y,Z
            self.ax_accel.plot(time_array, list(self.ax_values), 'g-', linewidth=1, label='X', alpha=0.8)
            self.ax_accel.plot(time_array, list(self.ay_values), 'b-', linewidth=1, label='Y', alpha=0.8)
            self.ax_accel.plot(time_array, list(self.az_values), 'm-', linewidth=1, label='Z', alpha=0.8)
            self.ax_accel.set_title('Accelerometer (X,Y,Z)', fontweight='bold', color='green')
            self.ax_accel.set_ylabel('Acceleration (g)')
            self.ax_accel.set_xlabel('Time (s)')
            self.ax_accel.grid(True, alpha=0.3)
            self.ax_accel.legend()
            
            # Accelerometer Magnitude
            self.ax_accel_mag.plot(time_array, list(self.accel_mag), 'purple', linewidth=2)
            self.ax_accel_mag.set_title('Acceleration Magnitude', fontweight='bold', color='purple')
            self.ax_accel_mag.set_ylabel('|Acceleration| (g)')
            self.ax_accel_mag.set_xlabel('Time (s)')
            self.ax_accel_mag.grid(True, alpha=0.3)
            
            # Quality Statistics
            self.ax_stats.clear()
            self.ax_stats.set_title('Quality Statistics', fontweight='bold', color='black')
            self.ax_stats.axis('off')
            
            if self.total_samples > 0:
                quality_pct = (self.good_samples / self.total_samples) * 100
                current_hr = self.heart_rates[-1] if self.heart_rates else 0
                current_spo2 = self.spo2_values[-1] if self.spo2_values else 0
                current_accel = self.accel_mag[-1] if self.accel_mag else 0
                current_quality = "GOOD" if self.quality_values[-1] == 1 else "POOR"
                
                stats_text = f"""CURRENT VALUES:
Heart Rate: {current_hr:.1f} BPM
SpO2: {current_spo2:.1f}%
Accel Mag: {current_accel:.3f}g
Quality: {current_quality}

STATISTICS:
Total Samples: {self.total_samples}
Good Samples: {self.good_samples}
Overall Quality: {quality_pct:.1f}%
Runtime: {time_array[-1]:.1f}s
                """
                
                self.ax_stats.text(0.05, 0.95, stats_text, transform=self.ax_stats.transAxes,
                                 fontsize=9, verticalalignment='top', fontfamily='monospace',
                                 bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
        
        plt.tight_layout()
    
    def close(self):
        """Clean up resources"""
        if self.csv_file:
            self.csv_file.close()
        print(f"Data saved to: {self.csv_filename}")

def parse_sensor_data(data: bytearray, mode: str):
    """Parse sensor data and put in queue"""
    try:
        obj = json.loads(data.decode())
        timestamp = datetime.datetime.now().isoformat()
        
        if mode == "quality":
            hr = obj.get('hr', 0)
            spo2 = obj.get('spo2', 0)
            ax = obj.get('ax', 0)
            ay = obj.get('ay', 0)
            az = obj.get('az', 0)
            quality = obj.get('quality', 0)
            accel_mag = obj.get('accel_mag', np.sqrt(ax**2 + ay**2 + az**2))
            
            print(f"[{timestamp}] HR: {hr:.1f} | SpO2: {spo2:.1f} | Quality: {'GOOD' if quality == 1 else 'POOR'} | Accel: {ax:.2f},{ay:.2f},{az:.2f}")
            
            # Put data in queue for main thread to process
            data_queue.put({
                'timestamp': timestamp,
                'hr': hr,
                'spo2': spo2,
                'ax': ax,
                'ay': ay,
                'az': az,
                'quality': quality,
                'accel_mag': accel_mag,
                'device_timestamp': obj.get('timestamp', 0)
            })
        else:
            hr = obj.get('hr', 0)
            spo2 = obj.get('spo2', 0)
            ax = obj.get('ax', 0)
            ay = obj.get('ay', 0)
            az = obj.get('az', 0)
            label = obj.get('label', 'unlabeled')
            
            print(f"[{timestamp}] HR: {hr:.1f} | SpO2: {spo2:.1f} | Label: {label} | Accel: {ax:.2f},{ay:.2f},{az:.2f}")
            
            # Put data in queue for main thread to process
            data_queue.put({
                'timestamp': timestamp,
                'hr': hr,
                'spo2': spo2,
                'ax': ax,
                'ay': ay,
                'az': az,
                'label': label,
                'device_timestamp': obj.get('timestamp', 0)
            })

    except Exception as e:
        print(f"❌ Parse error: {e}")
        print(f"Raw data: {data}")

async def ble_worker(device_name: str, mode: str):
    """BLE worker function to run in separate thread"""
    global ble_running
    
    print(f"🔍 Scanning for {device_name}...")
    devices = await BleakScanner.discover(timeout=15.0)

    target = None
    print(f"Found {len(devices)} devices:")
    for device in devices:
        if device.name:
            print(f"  - {device.name} ({device.address})")
            if device.name and device_name in device.name:
                target = device
                print(f"    *** TARGET FOUND: {device.name} ***")
                break

    if not target:
        print(f"❌ Device '{device_name}' not found.")
        print("Available ESP32 devices:")
        for device in devices:
            if device.name and "ESP32" in device.name:
                print(f"  - {device.name}")
        ble_running = False
        return

    print(f"✅ Found device: {target.name} @ {target.address}")
    
    try:
        async with BleakClient(target.address, timeout=10.0) as client:
            if not client.is_connected:
                print("❌ Failed to connect.")
                ble_running = False
                return

            print("🔗 Connected! Subscribing to sensor data...")
            
            # Subscribe to appropriate characteristic based on mode
            if mode == "quality":
                char_uuid = VITALS_DATA_CHAR_UUID
                await client.start_notify(char_uuid, lambda _, data: parse_sensor_data(data, mode))
                print("📊 Subscribed to vitals data characteristic")
                
                # Also subscribe to quality reports
                try:
                    await client.start_notify(QUALITY_CHAR_UUID, lambda _, data: print(f"Quality Report: {data.decode()}"))
                    print("📈 Subscribed to quality report characteristic")
                except Exception as e:
                    print(f"⚠️ Could not subscribe to quality reports: {e}")
            else:
                char_uuid = RAW_DATA_CHAR_UUID
                await client.start_notify(char_uuid, lambda _, data: parse_sensor_data(data, mode))
                print("📊 Subscribed to raw data characteristic")

            print("✅ Data collection started!")
            print("=" * 50)

            # Keep BLE connection alive and process commands
            while ble_running:
                # Check for commands to send
                try:
                    command = command_queue.get_nowait()
                    await client.write_gatt_char(CONTROL_CHAR_UUID, command.encode())
                    print(f"📤 Sent command: {command}")
                except queue.Empty:
                    pass
                except Exception as e:
                    print(f"❌ Command error: {e}")
                
                await asyncio.sleep(0.1)

            # Stop notifications
            await client.stop_notify(char_uuid)
            if mode == "quality":
                try:
                    await client.stop_notify(QUALITY_CHAR_UUID)
                except:
                    pass
            print("🔌 BLE connection closed.")
            
    except Exception as e:
        print(f"❌ BLE Error: {e}")
    finally:
        ble_running = False

def run_ble_in_thread(device_name: str, mode: str):
    """Run BLE in a separate thread with its own event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(ble_worker(device_name, mode))
    finally:
        loop.close()

def input_handler(mode: str):
    global ble_running
    """Handle user input in separate thread"""
    print("\n💬 COMMAND INPUT:")
    print("=" * 30)
    
    if mode == "quality":
        print("Commands: reset, recalibrate, interval X, quit")
    else:
        print("Commands: type label name, quit")
    
    while ble_running:
        try:
            command = input().strip()
            
            if command.lower() in ['quit', 'exit', 'q']:
                ble_running = False
                break
            elif mode == "quality":
                if command.lower() == 'reset':
                    command_queue.put("RESET_STATS")
                elif command.lower() == 'recalibrate':
                    command_queue.put("RECALIBRATE")
                elif command.lower().startswith('interval '):
                    try:
                        interval = int(command.split()[1])
                        command_queue.put(f"INTERVAL:{interval}")
                    except (IndexError, ValueError):
                        print("Invalid format. Use: interval X")
                else:
                    print("Available commands: reset, recalibrate, interval X, quit")
            else:  # raw mode
                if command:
                    command_queue.put(f"LABEL:{command}")
                    print(f"✅ Label set to: '{command}'")
        except (EOFError, KeyboardInterrupt):
            ble_running = False
            break
        except Exception as e:
            print(f"Input error: {e}")

def main():
    global ble_running
    
    print("Real-time Vitals Monitor with ML Quality Assessment")
    print("=" * 60)
    print("Select mode:")
    print("1. Quality Assessment Mode (with ML predictions)")
    print("2. Raw Data Collection Mode")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "1":
        mode = "quality"
        device_name = DEVICE_NAME_QUALITY
        print("🧠 Starting Quality Assessment Monitor...")
    elif choice == "2":
        mode = "raw"
        device_name = DEVICE_NAME_RAW
        print("📊 Starting Raw Data Collection Monitor...")
    else:
        print("Invalid choice")
        return
    
    # Create receiver
    receiver = QualityReceiver(mode, buffer_size=200)
    
    # Start BLE in separate thread
    ble_running = True
    ble_thread = threading.Thread(target=run_ble_in_thread, args=(device_name, mode), daemon=True)
    ble_thread.start()
    
    # Start input handler thread
    input_thread = threading.Thread(target=input_handler, args=(mode,), daemon=True)
    input_thread.start()
    
    # Wait a moment for BLE to connect
    print("⏳ Waiting for BLE connection...")
    time.sleep(3)
    
    # Run matplotlib in main thread
    try:
        print("📈 Starting real-time plots...")
        
        def on_close(event):
            """Handle plot window close"""
            global ble_running
            ble_running = False
            print("🛑 Plot window closed, stopping BLE...")

        receiver.fig.canvas.mpl_connect('close_event', on_close)

        # Create animation
        ani = FuncAnimation(
            receiver.fig, 
            receiver.update_plots, 
            interval=1000,  # Update every 1 second
            blit=False,
            cache_frame_data=False,
            repeat=True
        )

        plt.tight_layout()
        plt.show()  # This blocks until window is closed
        
    except KeyboardInterrupt:
        print("🛑 Interrupted by user.")
    finally:
        ble_running = False
        receiver.close()

if __name__ == "__main__":
    try:
        main()
    finally:
        ble_running = False
        print("💾 Program terminated")
