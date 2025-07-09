import asyncio
import csv
import datetime
import json
import time
from bleak import BleakScanner, BleakClient
from collections import defaultdict
import threading
import queue

# === Settings ===
DEVICE_NAME = "ESP32_QE_Test"
CSV_FILENAME = f"quantum_efficiency_test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# === BLE UUIDs ===
QE_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
RAW_DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"

# === LED wavelengths (approximate) ===
LED_WAVELENGTHS = {
    'blue': 470,    # nm
    'green': 525,   # nm  
    'red': 660,     # nm
    'ir': 940       # nm
}

# === Data storage ===
test_results = defaultdict(list)
current_led = None
ble_client = None
data_queue = queue.Queue()

# === CSV Setup ===
csv_file = open(CSV_FILENAME, mode='w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["Timestamp", "LED_Type", "Wavelength_nm", "IR_Raw", "Red_Raw", "IR_Avg", "Red_Avg", "Sample_Count"])

def parse_sensor_data(data: bytearray):
    try:
        obj = json.loads(data.decode())
        timestamp = datetime.datetime.now().isoformat()
        
        # Put data in queue for main thread to process
        data_queue.put({
            'timestamp': timestamp,
            'data': obj
        })
        
    except Exception as e:
        print(f"❌ Parse error: {e}")

def process_data_queue():
    """Process queued data from BLE thread"""
    while not data_queue.empty():
        try:
            item = data_queue.get_nowait()
            data = item['data']
            timestamp = item['timestamp']
            
            if data.get('type') == 'average':
                # This is average data
                led_type = data['led']
                avg_ir = data['avg_ir']
                avg_red = data['avg_red']
                samples = data['samples']
                wavelength = LED_WAVELENGTHS.get(led_type, 0)
                
                print(f"📊 Average for {led_type} ({wavelength}nm): IR={avg_ir:.2f}, Red={avg_red:.2f} (n={samples})")
                
                # Store results
                test_results[led_type].append({
                    'wavelength': wavelength,
                    'avg_ir': avg_ir,
                    'avg_red': avg_red,
                    'samples': samples,
                    'timestamp': timestamp
                })
                
                # Save to CSV
                csv_writer.writerow([
                    timestamp, led_type, wavelength, 
                    '', '', avg_ir, avg_red, samples
                ])
                csv_file.flush()
                
            else:
                # This is raw data
                ir_raw = data.get('ir', 0)
                red_raw = data.get('red', 0)
                led_type = data.get('led', 'none')
                collecting = data.get('collecting', False)
                
                if collecting:
                    print(f"📡 {led_type}: IR={ir_raw}, Red={red_raw}")
                
                # Save raw data to CSV
                wavelength = LED_WAVELENGTHS.get(led_type, 0)
                csv_writer.writerow([
                    timestamp, led_type, wavelength,
                    ir_raw, red_raw, '', '', ''
                ])
                csv_file.flush()
                
        except queue.Empty:
            break

async def send_control_command(command):
    """Send control command to ESP32"""
    global ble_client
    if ble_client and ble_client.is_connected:
        try:
            await ble_client.write_gatt_char(CONTROL_CHAR_UUID, command.encode())
            return True
        except Exception as e:
            print(f"❌ Failed to send command: {e}")
            return False
    return False

async def ble_worker():
    """BLE worker function"""
    global ble_client
    
    print("🔍 Scanning for ESP32...")
    devices = await BleakScanner.discover()
    
    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    if not target:
        print(f"❌ Device '{DEVICE_NAME}' not found.")
        return False
    
    print(f"✅ Found device: {target.name} @ {target.address}")
    
    try:
        ble_client = BleakClient(target)
        await ble_client.connect()
        
        if not ble_client.is_connected:
            print("❌ Failed to connect.")
            return False
        
        print("🔗 Connected! Starting data collection...")
        await ble_client.start_notify(RAW_DATA_CHAR_UUID, lambda _, data: parse_sensor_data(data))
        
        return True
        
    except Exception as e:
        print(f"❌ BLE Error: {e}")
        return False

def print_menu():
    print("\n" + "="*50)
    print("🔬 MAX30100 Quantum Efficiency Test")
    print("="*50)
    print("Available LEDs:")
    for led, wavelength in LED_WAVELENGTHS.items():
        print(f"  {led}: {wavelength}nm")
    print("\nCommands:")
    print("  start <led> - Start data collection for LED")
    print("  stop        - Stop current data collection")
    print("  reset       - Reset sensor FIFO")
    print("  results     - Show current results")
    print("  quit        - Exit program")
    print("="*50)

def show_results():
    print("\n📈 Current Test Results:")
    print("-" * 60)
    print(f"{'LED':<8} {'λ(nm)':<8} {'IR Avg':<12} {'Red Avg':<12} {'Samples':<8}")
    print("-" * 60)
    
    for led_type, results in test_results.items():
        if results:
            latest = results[-1]  # Get most recent result
            print(f"{led_type:<8} {latest['wavelength']:<8} {latest['avg_ir']:<12.2f} {latest['avg_red']:<12.2f} {latest['samples']:<8}")
    
    print("-" * 60)
    
    # Calculate quantum efficiency ratios (relative to IR)
    if 'ir' in test_results and test_results['ir']:
        ir_response = test_results['ir'][-1]['avg_ir']
        print(f"\n🔬 Relative Quantum Efficiency (IR photodiode, normalized to IR LED):")
        print(f"{'LED':<8} {'λ(nm)':<8} {'Relative QE':<12}")
        print("-" * 30)
        
        for led_type, results in test_results.items():
            if results:
                latest = results[-1]
                relative_qe = latest['avg_ir'] / ir_response if ir_response > 0 else 0
                print(f"{led_type:<8} {latest['wavelength']:<8} {relative_qe:<12.3f}")

async def main():
    global current_led
    
    print("🚀 Starting Quantum Efficiency Test System")
    
    # Connect to BLE device
    if not await ble_worker():
        print("❌ Failed to connect to device")
        return
    
    print_menu()
    
    try:
        while True:
            # Process any incoming data
            process_data_queue()
            
            # Get user input (non-blocking)
            try:
                user_input = input("\n> ").strip().lower()
                
                if user_input == 'quit':
                    break
                elif user_input == 'results':
                    show_results()
                elif user_input == 'reset':
                    if await send_control_command("RESET"):
                        print("✅ Sensor FIFO reset")
                elif user_input == 'stop':
                    if await send_control_command("STOP"):
                        print("✅ Data collection stopped")
                        current_led = None
                elif user_input.startswith('start '):
                    led_type = user_input.split(' ', 1)[1]
                    if led_type in LED_WAVELENGTHS:
                        # Confirm LED change
                        wavelength = LED_WAVELENGTHS[led_type]
                        print(f"\n🔄 Switching to {led_type.upper()} LED ({wavelength}nm)")
                        print("Please:")
                        print("1. Turn OFF current LED (if any)")
                        print(f"2. Turn ON {led_type.upper()} LED ({wavelength}nm)")
                        print("3. Ensure LED is positioned to illuminate the sensor")
                        
                        confirm = input(f"Ready to start collecting data for {led_type} LED? (y/n): ").strip().lower()
                        
                        if confirm == 'y':
                            if await send_control_command(f"START:{led_type}"):
                                current_led = led_type
                                print(f"✅ Started data collection for {led_type} LED")
                                print("💡 Data is being collected... type 'stop' when ready to finish")
                            else:
                                print("❌ Failed to start data collection")
                        else:
                            print("❌ Data collection cancelled")
                    else:
                        print(f"❌ Unknown LED type: {led_type}")
                        print(f"Available: {', '.join(LED_WAVELENGTHS.keys())}")
                elif user_input == 'help' or user_input == '?':
                    print_menu()
                elif user_input == '':
                    continue  # Empty input, just continue
                else:
                    print(f"❌ Unknown command: {user_input}")
                    print("Type 'help' for available commands")
                    
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n🛑 Interrupted by user")
                break
                
            # Small delay to prevent busy waiting
            await asyncio.sleep(0.1)
            
    except Exception as e:
        print(f"❌ Error in main loop: {e}")
    
    finally:
        # Cleanup
        if ble_client and ble_client.is_connected:
            await send_control_command("STOP")
            await ble_client.stop_notify(RAW_DATA_CHAR_UUID)
            await ble_client.disconnect()
            print("🔌 BLE connection closed")

def generate_report():
    """Generate a final test report"""
    if not test_results:
        print("📄 No test results to report")
        return
    
    print("\n" + "="*60)
    print("📊 QUANTUM EFFICIENCY TEST REPORT")
    print("="*60)
    print(f"Test Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Data saved to: {CSV_FILENAME}")
    print("\nTest Results Summary:")
    print("-" * 60)
    
    # Create summary table
    summary_data = []
    for led_type, results in test_results.items():
        if results:
            latest = results[-1]
            summary_data.append({
                'led': led_type,
                'wavelength': latest['wavelength'],
                'ir_avg': latest['avg_ir'],
                'red_avg': latest['avg_red'],
                'samples': latest['samples']
            })
    
    # Sort by wavelength
    summary_data.sort(key=lambda x: x['wavelength'])
    
    print(f"{'LED':<8} {'λ(nm)':<8} {'IR Response':<12} {'Red Response':<12} {'Samples':<8}")
    print("-" * 60)
    
    for data in summary_data:
        print(f"{data['led']:<8} {data['wavelength']:<8} {data['ir_avg']:<12.2f} {data['red_avg']:<12.2f} {data['samples']:<8}")
    
    # Calculate relative quantum efficiency
    if any(d['led'] == 'ir' for d in summary_data):
        ir_data = next(d for d in summary_data if d['led'] == 'ir')
        ir_response = ir_data['ir_avg']
        
        print(f"\nRelative Quantum Efficiency (normalized to IR @ {ir_data['wavelength']}nm):")
        print("-" * 40)
        print(f"{'LED':<8} {'λ(nm)':<8} {'IR QE':<12} {'Red QE':<12}")
        print("-" * 40)
        
        for data in summary_data:
            ir_qe = data['ir_avg'] / ir_response if ir_response > 0 else 0
            red_qe = data['red_avg'] / ir_response if ir_response > 0 else 0
            print(f"{data['led']:<8} {data['wavelength']:<8} {ir_qe:<12.3f} {red_qe:<12.3f}")
    
    print("\n📝 Notes:")
    print("- IR Response: Response of the IR photodiode")
    print("- Red Response: Response of the Red photodiode") 
    print("- Higher values indicate better quantum efficiency at that wavelength")
    print("- Results are relative measurements, not absolute quantum efficiency")
    print("="*60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Program interrupted")
    finally:
        generate_report()
        csv_file.close()
        print(f"💾 Data saved to {CSV_FILENAME}")

