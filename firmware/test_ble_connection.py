#!/usr/bin/env python3
"""
Simple BLE Test Script for ESP32_Unified_Sensor
===============================================
This script tests the basic BLE connection and data reception
without complex GUI or matplotlib issues.
"""
import asyncio
import json
import time
from bleak import BleakScanner, BleakClient

# BLE Configuration
DEVICE_NAME = "ESP32_Unified_Sensor"
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
DATA_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef1"
CONTROL_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef2"
STATUS_CHAR_UUID = "abcdefab-1234-5678-1234-56789abcdef3"

class ESP32Tester:
    def __init__(self):
        self.client = None
        self.running = True
        self.data_count = 0
        
    async def scan_and_connect(self):
        """Scan for and connect to ESP32 device"""
        print("🔍 Scanning for ESP32_Unified_Sensor...")
        
        devices = await BleakScanner.discover(timeout=10)
        target_device = None
        
        for device in devices:
            print(f"Found: {device.name} ({device.address})")
            if device.name == DEVICE_NAME:
                target_device = device
                break
                
        if not target_device:
            print("❌ ESP32_Unified_Sensor not found!")
            return False
            
        print(f"✅ Found target device: {target_device.address}")
        
        try:
            self.client = BleakClient(target_device.address)
            await self.client.connect()
            print("🔗 Connected to ESP32!")
            
            # List all services and characteristics
            print("\n📋 Available Services:")
            for service in self.client.services:
                print(f"  Service: {service.uuid}")
                for char in service.characteristics:
                    print(f"    Char: {char.uuid} - {char.properties}")
            
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
            
    async def setup_notifications(self):
        """Setup data notifications"""
        try:
            # Enable notifications on data characteristic
            await self.client.start_notify(DATA_CHAR_UUID, self.data_callback)
            print("🔔 Data notifications enabled")
            
            # Enable notifications on status characteristic  
            await self.client.start_notify(STATUS_CHAR_UUID, self.status_callback)
            print("🔔 Status notifications enabled")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to setup notifications: {e}")
            return False
            
    def data_callback(self, sender, data):
        """Handle incoming data"""
        try:
            json_str = data.decode('utf-8')
            data_obj = json.loads(json_str)
            self.data_count += 1
            
            print(f"📊 Data #{self.data_count}: {json_str}")
            
        except Exception as e:
            print(f"❌ Data parsing error: {e}")
            print(f"Raw data: {data}")
            
    def status_callback(self, sender, data):
        """Handle status updates"""
        try:
            json_str = data.decode('utf-8')
            status_obj = json.loads(json_str)
            
            print(f"📈 Status: {json_str}")
            
        except Exception as e:
            print(f"❌ Status parsing error: {e}")
            print(f"Raw status: {data}")
            
    async def send_mode_command(self, mode):
        """Send mode change command"""
        try:
            command = f"MODE:{mode}"
            await self.client.write_gatt_char(CONTROL_CHAR_UUID, command.encode('utf-8'))
            print(f"📤 Sent command: {command}")
            
        except Exception as e:
            print(f"❌ Failed to send command: {e}")
            
    async def test_sequence(self):
        """Run test sequence"""
        print("\n🧪 Starting test sequence...")
        
        # Test different modes
        modes = ["HR_SPO2", "TEMPERATURE", "RAW_DATA", "IDLE"]
        
        for mode in modes:
            print(f"\n🔄 Testing {mode} mode...")
            await self.send_mode_command(mode)
            
            # Wait and collect data
            print(f"⏰ Collecting data for 30 seconds...")
            start_time = time.time()
            start_count = self.data_count
            
            await asyncio.sleep(30)
            
            end_count = self.data_count
            data_received = end_count - start_count
            rate = data_received / 30.0
            
            print(f"📊 Mode {mode}: {data_received} samples in 30s ({rate:.1f} samples/sec)")
            
    async def run(self):
        """Main run function"""
        try:
            # Connect
            if not await self.scan_and_connect():
                return
                
            # Setup notifications
            if not await self.setup_notifications():
                await self.client.disconnect()
                return
                
            # Run tests
            await self.test_sequence()
            
            # Keep running to see continuous data
            print("\n🔄 Monitoring data (press Ctrl+C to stop)...")
            while self.running:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print("\n⏹️ Stopping...")
            self.running = False
            
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            
        finally:
            if self.client and self.client.is_connected:
                try:
                    await self.client.disconnect()
                    print("🔌 Disconnected")
                except:
                    pass

async def main():
    """Main function"""
    tester = ESP32Tester()
    await tester.run()

if __name__ == "__main__":
    print("🚀 ESP32 BLE Tester Starting...")
    print("📋 This will test basic BLE communication")
    print("🔍 Make sure ESP32_Unified_Sensor is powered on and advertising")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"💥 Fatal error: {e}")
