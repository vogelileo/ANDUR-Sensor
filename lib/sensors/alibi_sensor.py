"""
AlibiSensor - Fake sensor for testing without hardware

This is a simulated sensor that generates data on a timer without requiring
any actual hardware. It's useful for development, testing, and demonstrations.
"""

import asyncio
import time
from core.base_sensor import BaseSensor


class AlibiSensor(BaseSensor):
    """
    Alibi/fake sensor implementation.
    
    This sensor doesn't communicate with any hardware. Instead, it generates
    simulated data on a timer. The data pattern can be configured through
    parameters to simulate different scenarios.
    
    This is useful for:
    - Development without hardware
    - Testing the system architecture
    - Demonstrations
    - Debugging algorithms
    """
    
    def __init__(self, sensor_id, data_store, update_interval, buffer_size, 
                 base_value=50.0, variation=10.0):
        """
        Initialize the alibi sensor.
        
        Args:
            sensor_id: Unique identifier for this sensor
            data_store: DataStore instance for storing readings
            update_interval: Time in seconds between readings
            buffer_size: Size of ring buffer for this sensor
            base_value: Base value around which data oscillates (default: 50.0)
            variation: Range of variation from base value (default: 10.0)
        """
        super().__init__(sensor_id, data_store, update_interval, buffer_size)
        
        self.base_value = base_value
        self.variation = variation
        self.counter = 0
        
        print(f"[{self.sensor_id}] AlibiSensor configured (base={base_value}, variation={variation})")
    
    async def initialize(self):
        """
        Initialize the alibi sensor.
        
        Since this is a fake sensor with no hardware, initialization
        just logs that the sensor is ready.
        """
        print(f"[{self.sensor_id}] Alibi sensor initialized (no hardware required)")
        await asyncio.sleep(0.001)  # Minimal delay for consistency
    
    async def read(self):
        """
        Generate a fake sensor reading.
        
        This method generates a simple pattern that oscillates around
        the base value. The pattern is deterministic based on a counter,
        making it useful for testing.
        
        Returns:
            float: Generated sensor value
        """
        # No I2C lock needed since there's no hardware
        await asyncio.sleep(0.001)  # Minimal delay to simulate read time
        
        # Generate a simple oscillating pattern
        # This creates a smooth wave that's easy to observe in logs
        import math
        self.counter += 1
        
        # Create a sine wave pattern
        angle = self.counter * 0.1
        offset = math.sin(angle) * self.variation
        value = self.base_value + offset
        
        return round(value, 2)


# Example usage:
# from core.data_store import DataStore
#
# # Create data store
# data_store = DataStore()
# data_store.register_sensor("alibi1", 1000)
#
# # Create and run alibi sensor
# sensor = AlibiSensor("alibi1", data_store, 1.0, 1000, base_value=50.0, variation=10.0)
# await sensor.run()

# Made with Bob