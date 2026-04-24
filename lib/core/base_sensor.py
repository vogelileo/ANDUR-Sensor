"""
BaseSensor - Abstract base class for all sensor implementations

Provides the common interface and main loop for sensor readings.
Subclasses must implement the read() method for specific hardware.
"""

import asyncio
import time
from utils.logger import debug_print


class BaseSensor:
    """
    Abstract base class for all sensors.
    
    Handles the sensor lifecycle: initialization, periodic reading,
    and data storage. Subclasses implement hardware-specific read() method.
    """
    
    def __init__(self, sensor_id, data_store, update_interval, buffer_size, monitor=None):
        """
        Initialize the base sensor.
        
        Args:
            sensor_id: Unique identifier for this sensor
            data_store: DataStore instance for storing readings
            update_interval: Time in seconds between readings
            buffer_size: Size of ring buffer for this sensor
            monitor: SystemMonitor instance for tracking statistics
        """
        self.sensor_id = sensor_id
        self.data_store = data_store
        self.update_interval = update_interval
        self.buffer_size = buffer_size
        self.monitor = monitor
        self.i2c_lock = asyncio.Lock()  # For I2C bus access synchronization
        
        print(f"[{self.sensor_id}] Sensor initialized (interval={update_interval}s, buffer={buffer_size})")
    
    async def read(self):
        """
        Read sensor value - MUST be implemented by subclass.
        
        Returns:
            Sensor value (float or int)
            
        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError(f"Sensor '{self.sensor_id}' must implement read() method")
    
    async def initialize(self):
        """
        Initialize sensor hardware - can be overridden by subclass.
        
        Called once before the main loop starts.
        Override this method to set up hardware connections, configure
        registers, etc.
        """
        pass
    
    async def run(self):
        """
        Main sensor loop - reads sensor and updates data store.
        
        This method runs continuously, calling read() at the configured
        interval and storing results in the data store.
        """
        try:
            # Initialize hardware
            await self.initialize()
            print(f"[{self.sensor_id}] Starting sensor loop")
            
            # Main reading loop
            reading_count = 0
            debug_print("[DEBUG]", f"[{self.sensor_id}] ENTERING WHILE LOOP - about to start reading cycles")
            while True:
                debug_print("[DEBUG]", f"[{self.sensor_id}] TOP OF WHILE LOOP - iteration starting")
                try:
                    debug_print("[DEBUG]", f"[{self.sensor_id}] INSIDE TRY BLOCK - about to increment reading_count")
                    reading_count += 1
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}] ===== Reading cycle #{reading_count} =====")
                    
                    # Read sensor value
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Calling sensor read() method...")
                    start_time = time.time()
                    value = await self.read()
                    duration_ms = (time.time() - start_time) * 1000
                    timestamp = time.time()
                    
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Read completed, received data:")
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Type: {type(value).__name__}")
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Timestamp: {timestamp}")
                    
                    # Log data structure details
                    if isinstance(value, dict):
                        debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Dict keys: {list(value.keys())}")
                        if 'value' in value:
                            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   value field: {value['value']}")
                        if 'raw_samples' in value:
                            raw = value['raw_samples']
                            if raw is not None:
                                debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples type: {type(raw).__name__}")
                                if isinstance(raw, dict):
                                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples keys: {list(raw.keys())}")
                                    if 'i' in raw:
                                        debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples.i length: {len(raw['i'])}")
                                    if 'q' in raw:
                                        debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples.q length: {len(raw['q'])}")
                            else:
                                debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples: None")
                    else:
                        debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Value: {value}")
                    
                    # Store in data store
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Calling datastore.add_data()...")
                    success = True
                    try:
                        await self.data_store.add_data(self.sensor_id, timestamp, value)
                        debug_print("[SENSOR DATA]", f"[{self.sensor_id}] ✓ Data successfully stored in datastore")
                    except Exception as store_error:
                        success = False
                        print(f"[SENSOR DATA] [{self.sensor_id}] ✗ FAILED to store data in datastore!")
                        print(f"[SENSOR DATA] [{self.sensor_id}] Store error type: {type(store_error).__name__}")
                        print(f"[SENSOR DATA] [{self.sensor_id}] Store error message: {store_error}")
                    
                    # Track in monitor
                    if self.monitor:
                        self.monitor.record_sensor_reading(self.sensor_id, duration_ms, success)
                    
                    debug_print("[SENSOR DATA]", f"[{self.sensor_id}] ===== Reading cycle #{reading_count} complete =====")
                    
                except Exception as e:
                    print(f"[SENSOR DATA] [{self.sensor_id}] ✗ ERROR in reading cycle #{reading_count}: {e}")
                    print(f"[SENSOR DATA] [{self.sensor_id}] Error type: {type(e).__name__}")
                    import sys
                    sys.print_exception(e)
                
                # Wait for next reading
                debug_print("[DEBUG]", f"[{self.sensor_id}] About to sleep for {self.update_interval} seconds...")
                await asyncio.sleep(self.update_interval)
                debug_print("[DEBUG]", f"[{self.sensor_id}] Woke up from sleep, looping back to top of while loop")
                
        except Exception as e:
            print(f"[SENSOR DATA] [{self.sensor_id}] ✗ FATAL error in sensor loop: {e}")
            print(f"[SENSOR DATA] [{self.sensor_id}] Fatal error type: {type(e).__name__}")
            import sys
            sys.print_exception(e)
            raise

# Made with Bob
