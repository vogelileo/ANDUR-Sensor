"""
MicrowaveSensor - ADC-based microwave motion detector

This sensor reads I/Q signals from a microwave radar module using ADC pins.
Instead of FFT, it uses a simple time-domain detector that computes signal
energy/deviation to detect motion.

The sensor is designed to work with modules like RFBeam K-LD7 or similar
that output analog I/Q signals representing the Doppler shift.
"""

import asyncio
import time
import gc  # For explicit garbage collection
from array import array  # For memory-efficient arrays
from machine import ADC, Pin
from core.base_sensor import BaseSensor
from utils.logger import debug_print


class MicrowaveSensor(BaseSensor):
    """
    Microwave radar sensor using ADC for I/Q signal sampling.
    
    This sensor samples analog I/Q signals from a microwave radar module
    and computes a simple motion metric based on signal deviation.
    
    The detector works by:
    1. Sampling I and Q channels multiple times
    2. Computing mean values for each channel
    3. Computing average absolute deviation from mean
    4. Combining I/Q deviations into a single metric
    
    This approach avoids FFT while still detecting signal changes
    that indicate motion.
    
    Configuration parameters:
        pin_i: GPIO pin number for I channel ADC input
        pin_q: GPIO pin number for Q channel ADC input (optional)
        sample_count: Number of samples to collect per reading (default: 32)
        power_pin: GPIO pin to control sensor power (optional)
        warmup_ms: Milliseconds to wait after power-on (default: 100)
    """
    
    def __init__(self, sensor_id, data_store, update_interval, buffer_size,
                 pin_i, pin_q=None, sample_count=32, power_pin=None, warmup_ms=100,
                 target_sample_rate_hz=None, min_sample_rate_hz=None, monitor=None):
        """
        Initialize the microwave sensor.
        
        Args:
            sensor_id: Unique identifier for this sensor
            data_store: DataStore instance for storing readings
            update_interval: Time in seconds between readings
            buffer_size: Size of ring buffer for this sensor
            pin_i: GPIO pin number for I channel ADC
            pin_q: GPIO pin number for Q channel ADC (None for single channel)
            sample_count: Number of samples per reading (default: 32)
            power_pin: GPIO pin to control power (None if not used)
            warmup_ms: Warmup time in milliseconds (default: 100)
            target_sample_rate_hz: Expected sample rate in Hz (None to disable validation)
            min_sample_rate_hz: Minimum acceptable sample rate in Hz (None to use target only)
        """
        super().__init__(sensor_id, data_store, update_interval, buffer_size, monitor)
        
        self.pin_i = pin_i
        self.pin_q = pin_q
        self.sample_count = sample_count
        self.power_pin = power_pin
        self.warmup_ms = warmup_ms
        
        # Sample rate validation parameters
        self.target_sample_rate_hz = target_sample_rate_hz
        self.min_sample_rate_hz = min_sample_rate_hz
        
        # Sample rate measurement state
        self.measured_sample_rate_hz = None
        self.sample_rate_valid = None
        self.sample_rate_measured = False
        
        # ADC objects (initialized in initialize())
        self.adc_i = None
        self.adc_q = None
        self.power_control = None
        
        # Track if we have dual channel
        self.dual_channel = pin_q is not None
        
        # Pre-allocate sample buffers using array.array for memory efficiency
        # array.array uses compact C-style arrays instead of Python list objects
        # 'H' = unsigned short (16-bit), matching ADC read_u16() output
        # This significantly reduces memory usage compared to Python lists
        self.i_samples = array('H', (0 for _ in range(sample_count)))
        self.q_samples = array('H', (0 for _ in range(sample_count))) if self.dual_channel else array('H')
        
        print(f"[{self.sensor_id}] MicrowaveSensor configured:")
        print(f"  I channel: GPIO{pin_i}")
        if self.dual_channel:
            print(f"  Q channel: GPIO{pin_q}")
        else:
            print(f"  Q channel: disabled (single channel mode)")
        print(f"  Samples: {sample_count}")
        if power_pin is not None:
            print(f"  Power control: GPIO{power_pin}")
        if target_sample_rate_hz is not None:
            print(f"  Target sample rate: {target_sample_rate_hz} Hz")
            if min_sample_rate_hz is not None:
                print(f"  Minimum sample rate: {min_sample_rate_hz} Hz")
    
    async def initialize(self):
        """
        Initialize ADC hardware and power control.
        
        Sets up ADC objects for I/Q channels and optionally
        controls power pin for the sensor module.
        """
        try:
            # Initialize I channel ADC
            self.adc_i = ADC(Pin(self.pin_i))
            print(f"[{self.sensor_id}] I channel ADC initialized on GPIO{self.pin_i}")
            
            # Initialize Q channel ADC if configured
            if self.dual_channel:
                self.adc_q = ADC(Pin(self.pin_q))
                print(f"[{self.sensor_id}] Q channel ADC initialized on GPIO{self.pin_q}")
            
            # Initialize power control if configured
            if self.power_pin is not None:
                self.power_control = Pin(self.power_pin, Pin.OUT)
                self.power_control.value(1)  # Turn on sensor
                print(f"[{self.sensor_id}] Power control enabled on GPIO{self.power_pin}")
                
                # Wait for sensor warmup
                print(f"[{self.sensor_id}] Warming up for {self.warmup_ms}ms...")
                await asyncio.sleep(self.warmup_ms / 1000.0)
            
            print(f"[{self.sensor_id}] Microwave sensor initialized successfully")
            
            # Measure sample rate if validation is configured
            if self.target_sample_rate_hz is not None:
                await self._measure_sample_rate()
            
        except Exception as e:
            print(f"[{self.sensor_id}] Error initializing microwave sensor: {e}")
            raise
    
    async def _measure_sample_rate(self):
        """
        Measure the actual sample rate of the ADC sampling loop.
        
        This method performs a test sampling run to determine the effective
        sample rate achieved by the hardware. The measured rate depends on:
        - MicroPython performance
        - Board clock speed
        - ADC hardware capabilities
        - System load
        
        The measurement runs for at least 2 seconds to ensure accuracy.
        Samples continuously without delays to measure maximum achievable rate.
        Does NOT store samples in memory - just counts them for efficiency.
        The result is stored for validation and reporting.
        """
        try:
            print(f"[{self.sensor_id}] Measuring sample rate (this will take at least 2 seconds)...")
            print(f"[{self.sensor_id}] Sampling continuously at maximum hardware speed...")
            
            # Minimum measurement duration
            min_measurement_time_s = 2.0
            
            start_time = time.ticks_us()
            sample_count = 0
            
            # Sample I channel continuously for at least 10 seconds
            # NOTE: We don't store samples, just count them to avoid memory issues
            print(f"[{self.sensor_id}] Sampling I channel...")
            while True:
                self.adc_i.read_u16()  # Read but don't store
                sample_count += 1
                
                # Check elapsed time periodically (every 10000 samples to minimize overhead)
                if sample_count % 10000 == 0:
                    elapsed_us = time.ticks_diff(time.ticks_us(), start_time)
                    elapsed_s = elapsed_us / 1_000_000.0
                    current_rate = sample_count / elapsed_s
                    print(f"[{self.sensor_id}] Progress: {sample_count} samples, {elapsed_s:.1f}s, ~{current_rate:.0f} Hz")
                    
                    if elapsed_s >= min_measurement_time_s:
                        break
                
                # Yield control occasionally to prevent blocking
                if sample_count % 1000 == 0:
                    await asyncio.sleep(0)
            
            i_samples = sample_count
            i_elapsed_us = time.ticks_diff(time.ticks_us(), start_time)
            
            # Sample Q channel if available
            q_samples = 0
            q_elapsed_us = 0
            if self.dual_channel:
                print(f"[{self.sensor_id}] Sampling Q channel...")
                q_start_time = time.ticks_us()
                q_sample_count = 0
                
                while True:
                    self.adc_q.read_u16()  # Read but don't store
                    q_sample_count += 1
                    
                    # Check elapsed time periodically
                    if q_sample_count % 10000 == 0:
                        q_elapsed_us = time.ticks_diff(time.ticks_us(), q_start_time)
                        q_elapsed_s = q_elapsed_us / 1_000_000.0
                        current_rate = q_sample_count / q_elapsed_s
                        print(f"[{self.sensor_id}] Progress: {q_sample_count} samples (Q), {q_elapsed_s:.1f}s, ~{current_rate:.0f} Hz")
                        
                        if q_elapsed_s >= min_measurement_time_s:
                            break
                    
                    # Yield control occasionally
                    if q_sample_count % 1000 == 0:
                        await asyncio.sleep(0)
                
                q_samples = q_sample_count
                q_elapsed_us = time.ticks_diff(time.ticks_us(), q_start_time)
            
            # Calculate total elapsed time and samples
            total_elapsed_us = i_elapsed_us + q_elapsed_us
            total_elapsed_s = total_elapsed_us / 1_000_000.0
            total_samples = i_samples + q_samples
            
            # Calculate sample rate (samples per second)
            self.measured_sample_rate_hz = total_samples / total_elapsed_s
            
            # Validate against target and minimum thresholds
            self._validate_sample_rate()
            
            # Report results
            print(f"[{self.sensor_id}] Sample rate measurement complete:")
            print(f"  Measurement duration: {elapsed_s:.1f} seconds")
            print(f"  Total samples collected: {total_samples}")
            print(f"  Measured: {self.measured_sample_rate_hz:.0f} Hz")
            print(f"  Target: {self.target_sample_rate_hz} Hz")
            if self.min_sample_rate_hz is not None:
                print(f"  Minimum: {self.min_sample_rate_hz} Hz")
            print(f"  Status: {'PASS' if self.sample_rate_valid else 'FAIL'}")
            
            if not self.sample_rate_valid:
                deviation = abs(self.measured_sample_rate_hz - self.target_sample_rate_hz)
                deviation_pct = (deviation / self.target_sample_rate_hz) * 100
                print(f"  WARNING: Sample rate deviation: {deviation:.0f} Hz ({deviation_pct:.1f}%)")
            
            self.sample_rate_measured = True
            
        except Exception as e:
            print(f"[{self.sensor_id}] Error measuring sample rate: {e}")
            self.sample_rate_measured = False
            self.sample_rate_valid = False
    
    def _validate_sample_rate(self):
        """
        Validate the measured sample rate against configured thresholds.
        
        Sets self.sample_rate_valid based on:
        - If min_sample_rate_hz is set: measured >= min
        - Otherwise: measured is within reasonable range of target (±20%)
        """
        if self.measured_sample_rate_hz is None:
            self.sample_rate_valid = False
            return
        
        if self.min_sample_rate_hz is not None:
            # Use explicit minimum threshold
            self.sample_rate_valid = self.measured_sample_rate_hz >= self.min_sample_rate_hz
        else:
            # Use ±20% tolerance around target as default
            tolerance = 0.20
            min_acceptable = self.target_sample_rate_hz * (1.0 - tolerance)
            max_acceptable = self.target_sample_rate_hz * (1.0 + tolerance)
            self.sample_rate_valid = min_acceptable <= self.measured_sample_rate_hz <= max_acceptable
    
    def get_sample_rate_info(self):
        """
        Get sample rate measurement and validation information.
        
        Returns:
            dict: Sample rate information with keys:
                - measured_hz: Measured sample rate in Hz (None if not measured)
                - target_hz: Target sample rate in Hz (None if not configured)
                - min_hz: Minimum acceptable rate in Hz (None if not configured)
                - valid: Whether the measured rate passes validation (None if not measured)
                - measured: Whether measurement has been performed
        """
        return {
            "measured_hz": self.measured_sample_rate_hz,
            "target_hz": self.target_sample_rate_hz,
            "min_hz": self.min_sample_rate_hz,
            "valid": self.sample_rate_valid,
            "measured": self.sample_rate_measured
        }
    
    async def read(self):
        """
        Read microwave sensor and compute motion metric.
        
        Samples I/Q channels continuously at maximum hardware speed,
        then computes a simple motion detection metric based on signal deviation.
        
        Uses pre-allocated buffers to avoid memory fragmentation.
        
        Returns:
            dict: Contains 'value' (motion metric) and 'raw_samples' (I/Q data for FFT)
        """
        debug_print("[DEBUG]", f"[{self.sensor_id}] ===== READ METHOD CALLED =====")
        debug_print("[DEBUG]", f"[{self.sensor_id}] This is the FIRST line of read() method")
        try:
            debug_print("[DEBUG]", f"[{self.sensor_id}] Inside try block of read() method")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Starting sensor reading cycle")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Sample count: {self.sample_count}, Dual channel: {self.dual_channel}")
            
            # Sample I channel continuously into pre-allocated buffer
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Sampling I channel (GPIO{self.pin_i})...")
            start_time = time.ticks_us()
            for i in range(self.sample_count):
                self.i_samples[i] = self.adc_i.read_u16()
                # Yield control occasionally to prevent blocking other tasks
                if i % 10 == 0:
                    await asyncio.sleep(0)
            
            # Log first few I samples for verification
            i_sample_preview = self.i_samples[:min(5, self.sample_count)]
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] I channel samples (first 5): {i_sample_preview}")
            
            # Sample Q channel if available into pre-allocated buffer
            if self.dual_channel:
                debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Sampling Q channel (GPIO{self.pin_q})...")
                for i in range(self.sample_count):
                    self.q_samples[i] = self.adc_q.read_u16()
                    # Yield control occasionally
                    if i % 10 == 0:
                        await asyncio.sleep(0)
                
                # Log first few Q samples for verification
                q_sample_preview = self.q_samples[:min(5, self.sample_count)]
                debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Q channel samples (first 5): {q_sample_preview}")
            
            end_time = time.ticks_us()
            elapsed_us = time.ticks_diff(end_time, start_time)
            
            # Calculate effective sampling rate
            sample_rate_hz = (self.sample_count * (2 if self.dual_channel else 1)) / (elapsed_us / 1_000_000.0)
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Sampling completed in {elapsed_us} us, rate: {sample_rate_hz:.1f} Hz")
            
            # Compute motion metric using the buffers
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Computing motion metric...")
            metric = self._compute_motion_metric(self.i_samples, self.q_samples)
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Motion metric computed: {metric:.2f}")
            
            # Prepare data structure for return
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Preparing data structure for datastore...")
            
            # MEMORY OPTIMIZATION: Instead of creating full list copies, convert array.array
            # to list only when needed. The array.array objects are much more memory-efficient
            # (2 bytes per sample vs ~20 bytes per sample for Python list objects).
            # We convert to list here because the datastore/algorithm may expect list interface.
            # This is the only allocation point, and we do it efficiently.
            i_samples_list = list(self.i_samples)
            q_samples_list = list(self.q_samples) if self.dual_channel else []
            
            # Calculate memory usage of the data being prepared
            # array.array: 2 bytes per 16-bit value + small header (~64 bytes)
            # list conversion: ~20 bytes per element (Python object overhead)
            i_array_size = len(self.i_samples) * 2 + 64  # Compact array storage
            q_array_size = (len(self.q_samples) * 2 + 64) if self.dual_channel else 0
            i_list_size = len(i_samples_list) * 20  # List with object overhead
            q_list_size = len(q_samples_list) * 20 if self.dual_channel else 0
            
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Memory usage:")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   I array buffer: {len(self.i_samples)} values (~{i_array_size} bytes)")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   I list copy: {len(i_samples_list)} values (~{i_list_size} bytes)")
            if self.dual_channel:
                debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Q array buffer: {len(self.q_samples)} values (~{q_array_size} bytes)")
                debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Q list copy: {len(q_samples_list)} values (~{q_list_size} bytes)")
            total_memory = i_array_size + q_array_size + i_list_size + q_list_size
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   Total memory: ~{total_memory} bytes")
            
            # Return both the metric and raw samples for FFT processing
            result = {
                'value': round(metric, 2),
                'raw_samples': {
                    'i': i_samples_list,
                    'q': q_samples_list,
                    'sample_rate_hz': sample_rate_hz,
                    'sample_count': self.sample_count
                }
            }
            
            # MEMORY OPTIMIZATION: Explicitly delete list copies after creating result dict
            # This helps the garbage collector reclaim memory sooner
            del i_samples_list
            del q_samples_list
            
            # MEMORY OPTIMIZATION: Trigger garbage collection to free memory immediately
            # This is important in memory-constrained environments like MicroPython
            gc.collect()
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Garbage collection triggered")
            
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Data structure prepared:")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   value: {result['value']}")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples.sample_count: {result['raw_samples']['sample_count']}")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}]   raw_samples.sample_rate_hz: {result['raw_samples']['sample_rate_hz']:.1f}")
            debug_print("[SENSOR DATA]", f"[{self.sensor_id}] Returning data to base sensor for datastore ingestion")
            
            return result
            
        except Exception as e:
            print(f"[SENSOR DATA] [{self.sensor_id}] ERROR reading microwave sensor: {e}")
            print(f"[SENSOR DATA] [{self.sensor_id}] Exception type: {type(e).__name__}")
            import sys
            sys.print_exception(e)
            return {'value': 0.0, 'raw_samples': None}
    
    def _compute_motion_metric(self, i_samples, q_samples):
        """
        Compute motion detection metric from I/Q samples.
        
        This is a simple time-domain detector that measures signal
        deviation as a proxy for motion. The algorithm:
        1. Computes mean of each channel
        2. Computes average absolute deviation from mean
        3. Combines I/Q deviations into single metric
        
        MEMORY OPTIMIZATION: Works directly with array.array objects,
        avoiding unnecessary conversions or copies.
        
        Args:
            i_samples: array.array of I channel ADC readings (unsigned short)
            q_samples: array.array of Q channel ADC readings (empty if single channel)
        
        Returns:
            float: Motion metric (0-10000 range, higher = more motion)
        """
        # Compute I channel deviation
        # array.array supports sum() and len() operations efficiently
        i_count = len(i_samples)
        if i_count == 0:
            return 0.0
            
        i_mean = sum(i_samples) / i_count
        i_deviation = sum(abs(s - i_mean) for s in i_samples) / i_count
        
        # Compute Q channel deviation if available
        q_deviation = 0.0
        q_count = len(q_samples)
        if q_count > 0:
            q_mean = sum(q_samples) / q_count
            q_deviation = sum(abs(s - q_mean) for s in q_samples) / q_count
        
        # Combine I/Q deviations
        # For dual channel: use vector magnitude (sqrt(I^2 + Q^2))
        # For single channel: use I deviation only
        if q_count > 0:
            # Dual channel: compute magnitude
            combined = (i_deviation ** 2 + q_deviation ** 2) ** 0.5
        else:
            # Single channel: use I deviation directly
            combined = i_deviation
        
        # Scale to reasonable range (ADC is 16-bit, so max deviation ~32768)
        # Scale to 0-10000 range for consistency with algorithm expectations
        # Typical motion might cause deviation of 100-5000, so scale accordingly
        scaled = (combined / 32768.0) * 10000.0
        
        # Clamp to valid range
        if scaled > 10000.0:
            scaled = 10000.0
        elif scaled < 0.0:
            scaled = 0.0
        
        return scaled


# Example usage:
# from core.data_store import DataStore
#
# # Create data store
# data_store = DataStore()
# data_store.register_sensor("microwave1", 1000)
#
# # Create and run microwave sensor
# sensor = MicrowaveSensor(
#     "microwave1", data_store, 0.1, 1000,
#     pin_i=26, pin_q=27, sample_count=32,
#     power_pin=25, warmup_ms=100
# )
# await sensor.run()

# Made with Bob