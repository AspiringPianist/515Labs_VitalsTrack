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
CSV_FILENAME = "../test_logs/temperature_data.csv"
DEVICE_NAME = "ESP32_Temperature"

# === BLE UUIDs ===
CUSTOM_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CUSTOM_CHAR_UUID    = "abcdefab-1234-5678-1234-56789abcdef1"

# === Data Storage ===
temperature_data = deque(maxlen=100)
time_data = deque(maxlen=100)

# === Threading control ===
ble_running = False
data_queue = queue.Queue()

# === CSV Setup ===
csv_file = open(CSV_FILENAME, mode='w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["Timestamp", "Temperature"])


def parse_sensor_data(data: bytearray):
    try:
        obj = json.loads(data.decode())
        timestamp = datetime.datetime.now().isoformat()
        tmp = float(obj["temperature"])

        print(f"[{timestamp}] temperature: {tmp:.3f}°C")

        # Put data in queue for main thread to process
        data_queue.put({
            'timestamp': timestamp,
            'temperature': tmp
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
            temperature_data.append(data['temperature'])
            
            # Save to CSV
            csv_writer.writerow([
                data['timestamp'], 
                data['temperature']
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

        fig, ax = plt.subplots(1, 1, figsize=(12, 6))
        fig.suptitle("ESP32 Temperature Sensor (Live Plot)", fontsize=14)

        temp_line, = ax.plot([], [], label="Temperature (°C)", color='crimson', linewidth=2, marker='o', markersize=3)

        ax.legend(loc="upper left")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.set_ylabel("Temperature (°C)")
        ax.set_xlabel("Time (samples)")

        def update_plot(frame):
            # Process any new data from BLE thread
            process_data_queue()
            
            if len(temperature_data) == 0:
                return temp_line,
            
            # Create x-axis as sample indices
            x = list(range(len(temperature_data)))
            
            # Update data
            temp_line.set_data(x, list(temperature_data))

            # Update axis limits
            if len(temperature_data) > 0:
                ax.set_xlim(max(0, len(temperature_data) - 50), len(temperature_data))
                
                # Auto-scale y-axis with some padding
                temp_values = list(temperature_data)
                if temp_values:
                    min_temp = min(temp_values)
                    max_temp = max(temp_values)
                    temp_range = max_temp - min_temp
                    padding = temp_range * 0.1 if temp_range > 0 else 5
                    ax.set_ylim(min_temp - padding, max_temp + padding)

            return temp_line,

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
        ble_running = True
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
