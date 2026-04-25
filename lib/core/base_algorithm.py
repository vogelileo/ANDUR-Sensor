"""
BaseAlgorithm - Abstract base class for all algorithm implementations

Provides the common interface and main loop for data processing algorithms.
Supports both event-based (single value) and window-based (time series) modes.
"""

import asyncio
from utils.logger import debug_print


class BaseAlgorithm:
    """
    Abstract base class for all algorithms.
    
    Handles the algorithm lifecycle: data retrieval, processing,
    and LoRa triggering. Subclasses implement the process() method
    for specific algorithm logic.
    
    Supports two modes:
    - 'event': Process single latest value
    - 'window': Process time window of historical values
    """
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface,
                 check_interval, mode, params, sensor_mac=None, monitor=None):
        """
        Initialize the base algorithm.
        
        Args:
            algo_id: Unique identifier for this algorithm instance
            sensor_id: ID of the sensor to monitor
            data_store: DataStore instance for reading sensor data
            lora_interface: LoRaInterface instance for sending messages
            check_interval: Time in seconds between algorithm checks
            mode: 'event' or 'window' processing mode
            params: dict of algorithm-specific parameters
            sensor_mac: 6-character hex MAC address for LoRa transmission
            monitor: SystemMonitor instance for tracking statistics
        """
        self.algo_id = algo_id
        self.sensor_id = sensor_id
        self.sensor_mac = sensor_mac if sensor_mac else sensor_id  # Fallback to sensor_id if no MAC
        self.data_store = data_store
        self.lora_interface = lora_interface
        self.check_interval = check_interval
        self.mode = mode
        self.params = params
        self.monitor = monitor
        self.registered = False  # Track if registered as consumer
        
        print(f"[{self.algo_id}] Algorithm initialized (sensor={sensor_id}, mac={self.sensor_mac}, mode={mode}, interval={check_interval}s)")
    
    def register_as_consumer(self):
        """
        Register this algorithm as a consumer of sensor frames.
        
        Should be called before run() starts. This enables shared frame access
        without memory duplication.
        """
        if not self.registered:
            self.data_store.register_consumer(self.sensor_id, self.algo_id)
            self.registered = True
            debug_print("[ALGO INIT]", f"{self.algo_id} registered as consumer for {self.sensor_id}")
    
    async def process(self, data):
        """
        Process data and determine if trigger condition is met.
        
        MUST be implemented by subclass.
        
        Args:
            data: For 'event' mode: dict with 'timestamp' and 'value'
                  For 'window' mode: list of dicts with 'timestamp' and 'value'
        
        Returns:
            dict with at least:
                - 'trigger': bool (True if condition met)
                - 'value': int (0-10000 normalized value) if trigger is True
            Can include additional fields for logging/debugging
            
        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError(f"Algorithm '{self.algo_id}' must implement process() method")
    
    async def run(self):
        """
        Main algorithm loop - retrieves data, processes, and triggers LoRa.
        
        Uses shared frame access to avoid memory duplication. Frames are
        released after processing so they can be reused.
        """
        try:
            # Register as consumer if not already done
            if not self.registered:
                self.register_as_consumer()
            
            debug_print("[ALGO RUN]", f"{self.algo_id} - Starting algorithm loop")
            debug_print("[ALGO RUN]", f"Mode: {self.mode}, Check interval: {self.check_interval}s, Sensor: {self.sensor_id}")
            
            loop_count = 0
            
            # Main processing loop
            while True:
                try:
                    loop_count += 1
                    debug_print("[ALGO RUN]", f"\n===== {self.algo_id} - Loop iteration #{loop_count} =====")
                    
                    import time
                    loop_start_time = time.time()
                    
                    data = None
                    frame_sequence = None
                    
                    # Retrieve data based on mode
                    if self.mode == 'event':
                        # Get next unconsumed frame (shared reference, not copy)
                        debug_print("[ALGO RUN]", f"Fetching next frame from datastore for sensor '{self.sensor_id}'")
                        frame = await self.data_store.get_next_frame(self.sensor_id, self.algo_id)
                        
                        if frame:
                            frame_sequence = frame['sequence']
                            data = {
                                'timestamp': frame['timestamp'],
                                'value': frame['value']
                            }
                            debug_print("[ALGO RUN]", f"Frame {frame_sequence} retrieved: timestamp={frame['timestamp']}")
                            debug_print("[ALGO RUN]", f"Data value type: {type(frame['value'])}")
                        else:
                            debug_print("[ALGO RUN]", "No new frames available")
                        
                    elif self.mode == 'window':
                        # Window mode still uses legacy get_window for now
                        # (could be optimized later to use frame references)
                        window_size = self.params.get('window_size', 10)
                        debug_print("[ALGO RUN]", f"Retrieving window of {window_size} data points from datastore")
                        data = await self.data_store.get_window(self.sensor_id, window_size)
                        
                        if data:
                            debug_print("[ALGO RUN]", f"Window data retrieved: {len(data)} points")
                        else:
                            debug_print("[ALGO RUN]", "No window data available from datastore")
                    
                    else:
                        print(f"[ALGO RUN] ERROR: Unknown mode '{self.mode}'")
                        await asyncio.sleep(self.check_interval)
                        continue
                    
                    # Process data if available
                    if data:
                        # For event mode, data is a dict; for window mode, it's a list
                        if (self.mode == 'event' and data) or \
                           (self.mode == 'window' and len(data) > 0):
                            
                            debug_print("[ALGO RUN]", "Calling process() method")
                            process_start = time.time()
                            result = await self.process(data)
                            process_duration_ms = (time.time() - process_start) * 1000
                            
                            debug_print("[ALGO RUN]", f"Process returned: trigger={result.get('trigger') if result else None}")
                            
                            # Release frame after processing (event mode only)
                            if self.mode == 'event' and frame_sequence is not None:
                                await self.data_store.release_frame(self.sensor_id, self.algo_id, frame_sequence)
                                debug_print("[ALGO RUN]", f"Frame {frame_sequence} released")
                            
                            # Check if trigger condition met
                            triggered = result and result.get('trigger', False)
                            if triggered:
                                debug_print("[ALGO RUN]", "Trigger condition MET - sending LoRa message")
                                await self._send_lora(result)
                            else:
                                debug_print("[ALGO RUN]", "Trigger condition NOT met")
                            
                            # Track in monitor
                            if self.monitor:
                                self.monitor.record_algorithm_execution(self.algo_id, process_duration_ms, triggered)
                        else:
                            debug_print("[ALGO RUN]", "Data validation failed - skipping processing")
                    else:
                        debug_print("[ALGO RUN]", "No data to process")
                    
                    loop_duration = time.time() - loop_start_time
                    debug_print("[ALGO RUN]", f"Loop iteration completed in {loop_duration:.3f}s")
                    
                except Exception as e:
                    print(f"[ALGO RUN ERROR] Exception in loop iteration: {e}")
                    import sys
                    sys.print_exception(e)
                
                # Wait for next check
                debug_print("[ALGO RUN]", f"Sleeping for {self.check_interval}s until next check")
                await asyncio.sleep(self.check_interval)
                
        except Exception as e:
            print(f"[{self.algo_id}] Fatal error in algorithm loop: {e}")
            raise
    
    async def _send_lora(self, result):
        """
        Send LoRa message with algorithm result.
        
        Args:
            result: dict from process() containing trigger data
        """
        try:
            debug_print("[ALGO LORA]", f"Preparing LoRa message for {self.algo_id}")
            
            # Clamp value to LoRa protocol limits (0-255 for single byte)
            original_value = result['value']
            clamped_value = int(min(max(original_value, 0), 255))
            
            if original_value != clamped_value:
                debug_print("[ALGO LORA]", f"Value clamped: {original_value} -> {clamped_value} (LoRa protocol limit 0-255)")
            
            # Extract sensor type from sensor_id
            # Handle patterns like: "microwave1", "microwave_sensor_1", "alibi_sensor"
            sensor_type = self.sensor_id.lower()
            
            # Remove common suffixes and numbers
            for suffix in ['_sensor_', '_sensor', 'sensor_', 'sensor']:
                sensor_type = sensor_type.replace(suffix, '')
            
            # Remove trailing digits and underscores
            sensor_type = sensor_type.rstrip('0123456789_')
            
            # Remove leading underscores
            sensor_type = sensor_type.lstrip('_')
            
            debug_print("[ALGO LORA]", f"Extracted sensor type: '{sensor_type}' from sensor_id: '{self.sensor_id}'")
            
            # Encode sensor and algorithm into sensor_algo_enum
            try:
                from communication.lora_interface import LoRaInterface
                sensor_algo_enum = LoRaInterface.encode_sensor_algo_enum(sensor_type, self.algo_id)
                debug_print("[ALGO LORA]", f"Encoded sensor_algo_enum: {sensor_algo_enum} (sensor={sensor_type}, algo={self.algo_id})")
            except Exception as e:
                print(f"[ALGO LORA] Warning: Could not encode sensor_algo_enum: {e}")
                print(f"[ALGO LORA] Using sensor_type='{sensor_type}', algo_id='{self.algo_id}'")
                sensor_algo_enum = 0
            
            # Prepare DataPackage payload with required fields only
            # The LoRa interface expects specific DataPackage fields
            payload = {
                'sensor_id': self.sensor_mac,  # Use MAC address for LoRa transmission
                'value': clamped_value,
                'gps_latitude': 0.0,  # Default values for now
                'gps_longitude': 0.0,
                'battery': 100,  # Default to full battery
                'hops': 0,
                'sensor_algo_enum': sensor_algo_enum,
                'version': 1
            }
            
            debug_print("[ALGO LORA]", f"DataPackage prepared: sensor_id={self.sensor_mac}, value={clamped_value}, enum={sensor_algo_enum}")
            
            # Send via LoRa (not async, don't use await)
            debug_print("[ALGO LORA]", "Sending via LoRa interface...")
            self.lora_interface.send(payload)
            debug_print("[ALGO LORA]", f"LoRa message sent successfully: value={clamped_value}")
            
        except Exception as e:
            print(f"[ALGO LORA ERROR] Exception sending LoRa: {e}")
            import sys
            sys.print_exception(e)

# Made with Bob
