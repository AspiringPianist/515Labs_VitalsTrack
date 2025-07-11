import asyncio
import csv
import datetime
import json
from bleak import BleakScanner, BleakClient

# === Settings ===
DEVICE_NAME = "ESP32_FSR_Collector"
CSV_FILENAME = f"fsr_data_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# === BLE UUIDs ===
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
RAW_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"

# === Global variables ===
csv_file = None
csv_writer = None
data_count = 0

def setup_csv():
    """Initialize CSV file"""
    global csv_file, csv_writer
    csv_file = open(CSV_FILENAME, mode='w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["Timestamp", "IR", "Red", "FSR", "Label", "Device_Timestamp"])

def handle_data(data):
    """Handle incoming BLE data"""
    global data_count
    try:
        msg = json.loads(data.decode())
        ts = datetime.datetime.now().isoformat()
        
        # Write to CSV
        csv_writer.writerow([
            ts, 
            msg['ir'], 
            msg['red'], 
            msg['fsr'], 
            msg['label'],
            msg['timestamp']
        ])
        
        data_count += 1
        if data_count % 10 == 0:  # Show progress every 10 samples
            print(f"📊 [{msg['label']}] Samples: {data_count}, IR:{msg['ir']}, Red:{msg['red']}, FSR:{msg['fsr']}")
        
        csv_file.flush()
        
    except Exception as e:
        print(f"❌ Data error: {e}")

async def collect_data_for_label(client, label):
    """Start collection for a specific label"""
    global data_count
    data_count = 0
    
    print(f"\n🏷️  Starting collection for label: '{label}'")
    print("📊 Collecting for 10 seconds...")
    
    # Send label to ESP32
    await client.write_gatt_char(CONTROL_CHAR_UUID, f"LABEL:{label}".encode())
    
    # Wait for 10 seconds of collection
    await asyncio.sleep(11)  # Extra second to ensure completion
    
    print(f"✅ Collection complete! Collected {data_count} samples")

async def main():
    print("🔍 Scanning for ESP32...")
    devices = await BleakScanner.discover()
    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    
    if not target:
        print("❌ ESP32 not found")
        return

    print(f"✅ Found: {target.name}")
    
    # Setup CSV
    setup_csv()
    
    try:
        async with BleakClient(target.address) as client:
            print("🔗 Connected!")
            
            # Start notifications
            await client.start_notify(RAW_DATA_CHAR_UUID, lambda _, data: handle_data(data))
            
            print("\n=== Simple Data Collection ===")
            print("Enter labels one by one. Each label collects data for 10 seconds.")
            print("Press Ctrl+C to finish and save data")
            print("-" * 50)
            
            while True:
                try:
                    label = input("\nEnter label (or Ctrl+C to quit): ").strip()
                    if label:
                        await collect_data_for_label(client, label)
                    else:
                        print("Please enter a valid label")
                        
                except KeyboardInterrupt:
                    print("\n🛑 Stopping...")
                    break
                    
    except Exception as e:
        print(f"❌ Connection error: {e}")
    finally:
        if csv_file:
            csv_file.close()
        print(f"📄 Data saved to: {CSV_FILENAME}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Program terminated")
    finally:
        if csv_file:
            csv_file.close()
        print(f"📄 Final save: {CSV_FILENAME}")
