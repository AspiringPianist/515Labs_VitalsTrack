import asyncio
import csv
import datetime
import json
import time
from bleak import BleakScanner, BleakClient
from collections import defaultdict
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# === Settings ===
DEVICE_NAME = "ESP32_Distance_Test"
CSV_FILENAME = f"distance_raw_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
RESULTS_FILENAME = "qe_results.csv"

# === BLE UUIDs ===
QE_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
RAW_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"

# === LED Wavelength Mapping ===
LED_WAVELENGTHS = {
    "blue": 470,
    "green": 525,
    "red": 660,
    "ir": 940
}

# === Data storage ===
data_buffer = []

async def send_control(client, cmd):
    await client.write_gatt_char(CONTROL_CHAR_UUID, cmd.encode())

async def collect_data_for_led(client, led):
    distances = list(range(0, 21, 5))
    for dist in distances:
        confirm = input(f"Ready to collect for {led.upper()} at {dist}mm? (y/n): ").strip().lower()
        if confirm != 'y':
            print(f"⏭️ Skipping {led.upper()} at {dist}mm")
            continue

        print(f"\n🔦 Starting for {led.upper()} at {dist}mm")
        await send_control(client, f"START:{led}:{dist}")
        time.sleep(3)
        await send_control(client, "STOP")

async def main():
    print("🔍 Scanning for device...")
    devices = await BleakScanner.discover()
    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    if not target:
        print("❌ Device not found")
        return

    async with BleakClient(target.address) as client:
        await client.start_notify(RAW_DATA_CHAR_UUID, lambda _, data: handle_data(data))

        for led in ["red", "ir", "green", "blue"]:
            await collect_data_for_led(client, led)

        await client.stop_notify(RAW_DATA_CHAR_UUID)
        process_and_save_results()


def handle_data(data):
    try:
        msg = json.loads(data.decode())
        ts = datetime.datetime.now().isoformat()

        if msg.get("type") == "average":
            print(f"📊 {msg['led']} @ {msg['distance_mm']}mm => IR: {msg['avg_ir']:.2f}, Red: {msg['avg_red']:.2f}")
            data_buffer.append({
                "Timestamp": ts,
                "LED": msg['led'],
                "Distance_mm": int(msg['distance_mm']),
                "Avg_IR": float(msg['avg_ir']),
                "Avg_Red": float(msg['avg_red']),
                "Samples": int(msg['samples'])
            })
    except Exception as e:
        print("❌ Data error:", e)


def process_and_save_results():
    df = pd.DataFrame(data_buffer)
    df.to_csv(CSV_FILENAME, index=False)

    # Group by and average
    df_grouped = df.groupby(['Distance_mm', 'LED']).mean(numeric_only=True).reset_index()

    # Pivot table to get curves
    pivot_ir = df_grouped.pivot(index='Distance_mm', columns='LED', values='Avg_IR')
    pivot_red = df_grouped.pivot(index='Distance_mm', columns='LED', values='Avg_Red')

    # Normalize with min-max scaling
    norm_ir = (pivot_ir - pivot_ir.min()) / (pivot_ir.max() - pivot_ir.min())
    norm_red = (pivot_red - pivot_red.min()) / (pivot_red.max() - pivot_red.min())

    # Calculate AUC
    auc_ir = norm_ir.sum()
    auc_red = norm_red.sum()

    # Compute QE ratios
    rel_qe_ir = auc_ir / auc_ir['ir']
    rel_qe_red = auc_ir / auc_ir['red']

    # Save final results
    result_df = pd.DataFrame({
        'LED': rel_qe_ir.index,
        'Wavelength_nm': [LED_WAVELENGTHS[led] for led in rel_qe_ir.index],
        'Relative_QE_vs_IR': rel_qe_ir.values,
        'Relative_QE_vs_Red': rel_qe_red.values
    })
    result_df.sort_values(by='Wavelength_nm', inplace=True)
    result_df.to_csv(RESULTS_FILENAME, index=False)

    print("\n✅ Results saved to", RESULTS_FILENAME)
    print(result_df)

    # Plotting QE vs wavelength
    plt.figure(figsize=(10, 6))
    plt.plot(result_df['Wavelength_nm'], result_df['Relative_QE_vs_IR'], 'r-o', label='QE vs IR')
    plt.plot(result_df['Wavelength_nm'], result_df['Relative_QE_vs_Red'], 'b-o', label='QE vs Red')
    plt.xlabel("Wavelength (nm)")
    plt.ylabel("Relative QE")
    plt.title("Quantum Efficiency vs Wavelength")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("qe_vs_wavelength.png")
    plt.show()

if __name__ == "__main__":
    asyncio.run(main())
