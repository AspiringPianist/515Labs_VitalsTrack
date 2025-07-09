import asyncio
import csv
import datetime
import json
from bleak import BleakScanner, BleakClient
from collections import deque
import threading
import time
import queue

# === Settings ===
LIVE_PLOT = True
CSV_FILENAME = "../test_logs/oximeter_data.csv"
DEVICE_NAME = "ESP32_Sensor"

# === BLE UUIDs ===
CUSTOM_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CUSTOM_CHAR_UUID    = "abcdefab-1234-5678-1234-56789abcdef1"

# === Data Storage ===
hr_data = deque(maxlen=100)
spo2_data = deque(maxlen=100)
ax_data = deque(maxlen=100)
ay_data = deque(maxlen=100)
az_data = deque(maxlen=100)
time_data = deque(maxlen=100)

# === Threading control ===
ble_running = False
data_queue = queue.Queue()

# === CSV Setup ===
csv_file = open(CSV_FILENAME, mode='w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["Timestamp", "HeartRate", "SpO2", "Ax", "Ay", "Az"])


def parse_sensor_data(data: bytearray):
    try:
        obj = json.loads(data.decode())
        timestamp = datetime.datetime.now().isoformat()
        hr = int(obj["hr"])
        spo2 = int(obj["spo2"])
        ax = float(obj["ax"])
        ay = float(obj["ay"])
        az = float(obj["az"])

        print(f"[{timestamp}] HR: {hr} bpm | SpO₂: {spo2}% | Acc: x={ax:.2f} y={ay:.2f} z={az:.2f}")

        # Put data in queue for main thread to process
        data_queue.put({
            'timestamp': timestamp,
            'hr': hr,
            'spo2': spo2,
            'ax': ax,
            'ay': ay,
            'az': az
        })

    except Exception as e:
        print("❌ Parse error:", e)


async def ble_worker():
    """BLE worker function to run in separate thread"""
    global ble_running
    
    print("🔍 Scanning for ESP32...")
    devices = await BleakScanner.discover()

    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    if not target:
        print(f"❌ Device with name '{DEVICE_NAME}' not found.")
        ble_running = False
        return

    print(f"✅ Found device: {target.name} @ {target.address}")
    
    try:
        async with BleakClient(target) as client:
            if not client.is_connected:
                print("❌ Failed to connect.")
                ble_running = False
                return

            print("🔗 Connected! Subscribing to sensor data...")
            await client.start_notify(CUSTOM_CHAR_UUID, lambda _, data: parse_sensor_data(data))

            # Keep BLE connection alive
            while ble_running:
                await asyncio.sleep(0.1)

            await client.stop_notify(CUSTOM_CHAR_UUID)
            print("🔌 BLE connection closed.")
            
    except Exception as e:
        print(f"❌ BLE Error: {e}")
    finally:
        ble_running = False


def run_ble_in_thread():
    """Run BLE in a separate thread with its own event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(ble_worker())
    finally:
        loop.close()


def process_data_queue():
    """Process queued data from BLE thread"""
    while not data_queue.empty():
        try:
            data = data_queue.get_nowait()
            
            # Update plot data
            time_data.append(time.time())
            hr_data.append(data['hr'])
            spo2_data.append(data['spo2'])
            ax_data.append(data['ax'])
            ay_data.append(data['ay'])
            az_data.append(data['az'])
            
            # Save to CSV
            csv_writer.writerow([
                data['timestamp'], 
                data['hr'], 
                data['spo2'], 
                data['ax'], 
                data['ay'], 
                data['az']
            ])
            csv_file.flush()
            
        except queue.Empty:
            break


def main():
    global ble_running
    
    if LIVE_PLOT:
        # Start BLE in separate thread
        ble_running = True
        ble_thread = threading.Thread(target=run_ble_in_thread, daemon=True)
        ble_thread.start()
        
        # Run matplotlib in main thread
        import matplotlib.pyplot as plt
        import matplotlib.animation as animation
        
        # Use a valid style
        try:
            plt.style.use("seaborn-v0_8")
        except OSError:
            try:
                plt.style.use("seaborn")
            except OSError:
                plt.style.use("default")
                print("ℹ️ Using default matplotlib style")

        fig, axs = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        fig.suptitle("ESP32 Pulse Oximeter + Acceleration (Live Plot)", fontsize=14)

        hr_line, = axs[0].plot([], [], label="Heart Rate (bpm)", color='crimson', linewidth=2, marker='o', markersize=3)
        spo2_line, = axs[0].plot([], [], label="SpO₂ (%)", color='dodgerblue', linewidth=2, marker='s', markersize=3)

        ax_line, = axs[1].plot([], [], label="Ax (g)", color='limegreen', linestyle='-', linewidth=1.5)
        ay_line, = axs[1].plot([], [], label="Ay (g)", color='orange', linestyle='-', linewidth=1.5)
        az_line, = axs[1].plot([], [], label="Az (g)", color='purple', linestyle='-', linewidth=1.5)

        for ax in axs:
            ax.legend(loc="upper left")
            ax.grid(True, linestyle="--", alpha=0.4)

        axs[0].set_ylabel("Vitals")
        axs[0].set_ylim(0, 120)
        axs[1].set_ylabel("Accel (g)")
        axs[1].set_ylim(-6, 6)
        axs[1].set_xlabel("Time (samples)")

        def update_plot(frame):
            # Process any new data from BLE thread
            process_data_queue()
            
            if len(hr_data) == 0:
                return hr_line, spo2_line, ax_line, ay_line, az_line
            
            # Create x-axis as sample indices
            x = list(range(len(hr_data)))
            
            # Update data
            hr_line.set_data(x, list(hr_data))
            spo2_line.set_data(x, list(spo2_data))
            ax_line.set_data(x, list(ax_data))
            ay_line.set_data(x, list(ay_data))
            az_line.set_data(x, list(az_data))

            # Update x-axis limits to show last 50 points
            if len(hr_data) > 0:
                axs[0].set_xlim(max(0, len(hr_data) - 50), len(hr_data))
                axs[1].set_xlim(max(0, len(hr_data) - 50), len(hr_data))

            return hr_line, spo2_line, ax_line, ay_line, az_line

        def on_close(event):
            """Handle plot window close"""
            global ble_running
            ble_running = False
            print("🛑 Plot window closed, stopping BLE...")

        fig.canvas.mpl_connect('close_event', on_close)

        # Create animation
        ani = animation.FuncAnimation(
            fig, 
            update_plot, 
            interval=200,
            blit=False,
            cache_frame_data=False,
            repeat=True
        )

        print("📈 Showing live plot (close window to exit)...")
        plt.tight_layout()
        
        try:
            plt.show()  # This blocks until window is closed
        except KeyboardInterrupt:
            print("🛑 Interrupted by user.")
        finally:
            ble_running = False
            
    else:
        # Non-plotting mode - run BLE in main thread
        print("📊 Logging only (plotting disabled). Press Ctrl+C to stop.")
        try:
            asyncio.run(ble_worker())
        except KeyboardInterrupt:
            print("🛑 Interrupted by user.")


if __name__ == "__main__":
    try:
        main()
    finally:
        ble_running = False
        csv_file.close()
        print(f"💾 Data saved to {CSV_FILENAME}")
