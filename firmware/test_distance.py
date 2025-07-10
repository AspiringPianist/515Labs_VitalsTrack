import asyncio
import csv
import datetime
import json
import time
from bleak import BleakScanner, BleakClient

# === Settings ===
DEVICE_NAME = "ESP32_Distance_Test"
CSV_FILENAME = f"distance_test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# === BLE UUIDs ===
QE_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
RAW_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"

# === CSV Setup ===
csv_file = open(CSV_FILENAME, mode='w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["Timestamp", "LED", "Distance_mm", "IR", "Red", "Avg_IR", "Avg_Red", "Samples"])

async def send_control(client, cmd):
    await client.write_gatt_char(CONTROL_CHAR_UUID, cmd.encode())

async def main():
    print("🔍 Scanning for device...")
    devices = await BleakScanner.discover()
    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    if not target:
        print("❌ Device not found")
        return

    async with BleakClient(target.address) as client:
        await client.start_notify(RAW_DATA_CHAR_UUID, lambda _, data: handle_data(data))

        while True:
            try:
                led = input("Enter LED type (red/ir): ").strip().lower()
                dist = input("Enter distance (mm): ").strip()
                print(f"Starting for {led} at {dist}mm")
                await send_control(client, f"START:{led}:{dist}")
                time.sleep(3)
                await send_control(client, "STOP")
            except KeyboardInterrupt:
                break

        await client.stop_notify(RAW_DATA_CHAR_UUID)

def handle_data(data):
    try:
        msg = json.loads(data.decode())
        ts = datetime.datetime.now().isoformat()

        if "type" in msg and msg["type"] == "average":
            print(f"📊 {msg['led']} @ {msg['distance_mm']}mm => IR: {msg['avg_ir']:.2f}, Red: {msg['avg_red']:.2f}")
            csv_writer.writerow([ts, msg['led'], msg['distance_mm'], '', '', msg['avg_ir'], msg['avg_red'], msg['samples']])
        else:
            csv_writer.writerow([ts, msg['led'], msg.get('distance_mm', ''), msg['ir'], msg['red'], '', '', msg['samples']])
    except Exception as e:
        print("❌ Data error:", e)

if __name__ == "__main__":
    asyncio.run(main())
