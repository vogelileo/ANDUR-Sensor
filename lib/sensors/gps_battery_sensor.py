"""
GPSBatterySensor - GPS location and battery monitoring sensor (Hardcoded Version)

This sensor provides hardcoded GPS coordinates and battery level since no
hardware is available on the board.

The sensor provides:
- GPS latitude: 13.13 (hardcoded)
- GPS longitude: 13.13 (hardcoded)
- Battery level: 69% (hardcoded)
"""

import asyncio
from core.base_sensor import BaseSensor


class GPSBatterySensor(BaseSensor):
    """
    GPS and battery monitoring sensor using hardcoded values.
    
    This simplified sensor returns fixed values for GPS coordinates and
    battery level since no GPS or battery monitoring hardware is available.
    """
    
    # Hardcoded constants
    GPS_LATITUDE = 13.13
    GPS_LONGITUDE = 13.13
    BATTERY_LEVEL = 69
    
    def __init__(self, sensor_id, data_store, update_interval, buffer_size, monitor=None):
        """
        Initialize the GPS and battery sensor with hardcoded values.
        
        Args:
            sensor_id: Unique identifier for this sensor
            data_store: DataStore instance for storing readings
            update_interval: Time in seconds between readings
            buffer_size: Size of ring buffer for this sensor
            monitor: SystemMonitor instance for tracking statistics
        """
        super().__init__(sensor_id, data_store, update_interval, buffer_size, monitor)
        
        # Hardcoded values
        self.gps_latitude = self.GPS_LATITUDE
        self.gps_longitude = self.GPS_LONGITUDE
        self.battery = self.BATTERY_LEVEL
        
        print(f"[{self.sensor_id}] GPSBatterySensor configured with hardcoded values:")
        print(f"  GPS Latitude: {self.gps_latitude}")
        print(f"  GPS Longitude: {self.gps_longitude}")
        print(f"  Battery Level: {self.battery}%")
    
    async def initialize(self):
        """
        Initialize the sensor (no hardware initialization needed).
        
        Simply prints a message indicating hardcoded values are being used.
        """
        print(f"[{self.sensor_id}] GPS and battery sensor initialized (using hardcoded values)")
        await asyncio.sleep(0.001)  # Minimal delay for async consistency
    
    async def read(self):
        """
        Read GPS coordinates and battery level (returns hardcoded values).
        
        Also updates the global metadata in DataStore so all algorithms
        can access current GPS/battery data.
        
        Returns:
            dict: Contains 'gps_latitude', 'gps_longitude', and 'battery' keys
        """
        await asyncio.sleep(0.001)  # Minimal delay for async consistency
        
        # Update global metadata in DataStore
        self.data_store.set_global_metadata(
            self.gps_latitude,
            self.gps_longitude,
            self.battery
        )
        
        return {
            'gps_latitude': self.gps_latitude,
            'gps_longitude': self.gps_longitude,
            'battery': self.battery
        }


# Example usage:
# from core.data_store import DataStore
#
# # Create data store
# data_store = DataStore()
# data_store.register_sensor("gps_battery_1", 1000)
#
# # Create and run GPS/battery sensor
# sensor = GPSBatterySensor("gps_battery_1", data_store, 1.0, 1000)
# await sensor.run()

# Made with Bob