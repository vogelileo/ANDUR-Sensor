"""
MicrowaveDetectionAlgorithm - FFT-based motion detection for microwave sensors

This algorithm processes microwave sensor I/Q data using FFT to detect motion.
It computes the frequency spectrum, identifies the peak frequency, and compares
the peak magnitude against the noise floor to determine if motion is present.

Uses a custom Cooley-Tukey radix-2 FFT implementation (no external dependencies).

The algorithm supports two modes:
1. FFT mode (use_fft=True): Uses FFT analysis like the C++ RFBeam implementation
   - Removes DC offset from I/Q samples
   - Computes FFT to get frequency spectrum (custom implementation)
   - Finds peak frequency with parabolic interpolation
   - Calculates noise floor (average of non-peak bins)
   - Compares peak to noise with threshold multiplier
   
2. Simple mode (use_fft=False): Uses time-domain threshold detection
   - Direct threshold comparison on sensor value
   - Faster but less sophisticated

Both modes use streak logic to filter transient events.
"""

import asyncio
import time
from core.base_algorithm import BaseAlgorithm
from utils.logger import debug_print
from utils import fft as custom_fft

# Custom FFT is always available
ULAB_AVAILABLE = True


class MicrowaveDetectionAlgorithm(BaseAlgorithm):
    """
    Event-based microwave motion detection with threshold and streak logic.
    
    This algorithm monitors microwave sensor readings and triggers when:
    1. The sensor value exceeds the configured threshold
    2. The condition persists for a required number of consecutive readings
    
    The streak logic is inspired by legacy microwave detector implementations
    and helps reduce false positives from noise or brief disturbances.
    
    When triggered, the algorithm outputs a scaled value based on the
    sensor reading, allowing downstream systems to gauge motion intensity.
    
    Parameters:
        threshold: float - Minimum sensor value to consider as motion (default: 100.0)
        streak_required: int - Number of consecutive readings above threshold (default: 3)
        max_output: int - Maximum output value for scaling (default: 10000)
        scale_factor: float - Multiplier for sensor value to output (default: 1.0)
    
    Example usage:
        params = {
            "threshold": 150.0,
            "streak_required": 3,
            "max_output": 10000,
            "scale_factor": 1.0
        }
        algo = MicrowaveDetectionAlgorithm(
            "mw_detect1", "microwave1", data_store, lora, 0.1, params
        )
        await algo.run()
    """
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface,
                 check_interval, params, sensor_mac=None, monitor=None, installed_sensors=None):
        """
        Initialize the microwave detection algorithm.
        
        Args:
            algo_id: Unique identifier for this algorithm instance
            sensor_id: ID of the microwave sensor to monitor
            data_store: DataStore instance for reading sensor data
            lora_interface: LoRaInterface instance for sending messages
            check_interval: Time in seconds between algorithm checks
            params: dict with algorithm parameters
            sensor_mac: 6-character hex MAC address for LoRa transmission
            monitor: SystemMonitor instance for tracking statistics
            installed_sensors: List of sensor config dicts for building payload
        """
        # Initialize base class with event mode
        super().__init__(algo_id, sensor_id, data_store, lora_interface,
                        check_interval, mode='event', params=params,
                        sensor_mac=sensor_mac, monitor=monitor,
                        installed_sensors=installed_sensors)
        
        # FFT mode parameters
        self.use_fft = params.get('use_fft', False)
        self.fft_threshold_mult = params.get('fft_threshold_mult', 5.0)
        
        # Simple threshold parameters (used when FFT disabled or as fallback)
        self.threshold = params.get('threshold', 100.0)
        self.scale_factor = params.get('scale_factor', 1.0)
        
        # Common parameters
        self.streak_required = params.get('streak_required', 3)
        self.max_output = params.get('max_output', 10000)
        
        # Validate parameters
        if self.threshold < 0:
            print(f"[{self.algo_id}] Warning: threshold {self.threshold} < 0, using 0")
            self.threshold = 0.0
        
        if self.streak_required < 1:
            print(f"[{self.algo_id}] Warning: streak_required {self.streak_required} < 1, using 1")
            self.streak_required = 1
        
        if self.max_output < 1 or self.max_output > 10000:
            print(f"[{self.algo_id}] Warning: max_output {self.max_output} out of range, using 10000")
            self.max_output = 10000
        
        if self.scale_factor <= 0:
            print(f"[{self.algo_id}] Warning: scale_factor {self.scale_factor} <= 0, using 1.0")
            self.scale_factor = 1.0
        
        if self.fft_threshold_mult <= 0:
            print(f"[{self.algo_id}] Warning: fft_threshold_mult {self.fft_threshold_mult} <= 0, using 5.0")
            self.fft_threshold_mult = 5.0
        
        # FFT is always available with custom implementation
        # No need to check availability
        
        # State tracking for streak detection
        self.current_streak = 0
        self.last_trigger_time = 0
        
        # FFT state tracking
        self.last_peak_freq_hz = 0.0
        self.last_peak_mag = 0.0
        self.last_noise_avg = 0.0
        self.last_snr = 0.0
        
        print(f"[{self.algo_id}] MicrowaveDetectionAlgorithm configured:")
        print(f"  Mode: {'FFT' if self.use_fft else 'Simple threshold'}")
        if self.use_fft:
            print(f"  FFT threshold multiplier: {self.fft_threshold_mult}")
        else:
            print(f"  Threshold: {self.threshold}")
            print(f"  Scale factor: {self.scale_factor}")
        print(f"  Streak required: {self.streak_required}")
        print(f"  Max output: {self.max_output}")
    
    async def _fft_peak_and_noise(self, i_samples, q_samples, sample_rate_hz):
        """
        Perform FFT analysis on I/Q samples to detect motion (async with yielding).
        
        Based on the C++ RFBeam implementation:
        1. Remove DC offset from I/Q samples
        2. Compute FFT (with cooperative yielding)
        3. Calculate magnitudes and find peak
        4. Calculate noise floor (average of non-peak bins)
        5. Use parabolic interpolation for accurate peak frequency
        
        Args:
            i_samples: List of I channel samples
            q_samples: List of Q channel samples
            sample_rate_hz: Sampling rate in Hz
        
        Returns:
            dict with:
                - 'peak_freq_hz': Peak frequency in Hz
                - 'peak_mag': Peak magnitude
                - 'noise_avg': Average noise magnitude
                - 'detected': True if peak >= noise * threshold_mult
        """
        debug_print("[ALGO FFT]", "Starting FFT analysis")
        debug_print("[ALGO FFT]", f"Sample count: {len(i_samples)}, Sample rate: {sample_rate_hz} Hz")
        
        try:
            N = len(i_samples)
            
            # Prepare I/Q data (use lists directly, no numpy needed)
            vReal = list(i_samples)
            vImag = list(q_samples) if q_samples else [0.0] * N
            
            # Remove DC offset
            mean_i = custom_fft.mean(vReal)
            mean_q = custom_fft.mean(vImag)
            debug_print("[ALGO FFT]", f"DC offset - I mean: {mean_i:.4f}, Q mean: {mean_q:.4f}")
            vReal = [x - mean_i for x in vReal]
            vImag = [x - mean_q for x in vImag]
            
            # Compute FFT with complex input (I + jQ)
            # Yield control periodically during FFT computation
            debug_print("[ALGO FFT]", "Computing FFT...")
            complex_signal = [complex(i, q) for i, q in zip(vReal, vImag)]
            
            # Run FFT in chunks to allow cooperative yielding
            # For small FFTs (<256 samples), run directly
            # For larger FFTs, yield every 100 butterfly operations
            if N < 256:
                fft_result = custom_fft.fft(complex_signal)
            else:
                # For larger FFTs, yield control periodically
                fft_result = custom_fft.fft(complex_signal, yield_interval=100)
                # Yield after FFT computation
                await asyncio.sleep(0)
            
            # Calculate magnitudes for positive frequencies only
            N_half = len(fft_result) // 2  # Use padded length
            magnitudes = custom_fft.abs_spectrum(fft_result[:N_half])
            debug_print("[ALGO FFT]", f"FFT computed, analyzing {N_half} frequency bins")
            
            # Find peak (skip DC bin at index 0)
            peak_idx = custom_fft.argmax(magnitudes, start=1)
            peak_mag = float(magnitudes[peak_idx])
            debug_print("[ALGO FFT]", f"Peak found at bin {peak_idx}, magnitude: {peak_mag:.2f}")
            
            # Calculate noise average (exclude DC and peak bin)
            noise_sum = 0.0
            noise_count = 0
            for k in range(1, N_half):
                if k != peak_idx:
                    noise_sum += float(magnitudes[k])
                    noise_count += 1
            
            noise_avg = noise_sum / noise_count if noise_count > 0 else 0.0
            debug_print("[ALGO FFT]", f"Noise floor calculated from {noise_count} bins: {noise_avg:.2f}")
            
            # Parabolic interpolation for accurate peak frequency
            if peak_idx > 0 and peak_idx < N_half - 1:
                a = float(magnitudes[peak_idx - 1])
                b = float(magnitudes[peak_idx])
                c = float(magnitudes[peak_idx + 1])
                denom = a - 2.0 * b + c
                delta = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
                peak_freq_hz = ((peak_idx + delta) * sample_rate_hz) / N
                debug_print("[ALGO FFT]", f"Parabolic interpolation applied, delta: {delta:.4f}")
            else:
                peak_freq_hz = (peak_idx * sample_rate_hz) / N
                debug_print("[ALGO FFT]", "Peak at edge, no interpolation")
            
            # Determine if motion detected
            threshold_value = noise_avg * self.fft_threshold_mult
            detected = peak_mag >= threshold_value
            debug_print("[ALGO FFT]", f"Detection threshold: {threshold_value:.2f} (noise {noise_avg:.2f} * {self.fft_threshold_mult})")
            debug_print("[ALGO FFT]", f"Motion detected: {detected}")
            
            return {
                'peak_freq_hz': peak_freq_hz,
                'peak_mag': peak_mag,
                'noise_avg': noise_avg,
                'detected': detected,
                'snr': peak_mag / noise_avg if noise_avg > 0 else float('inf')
            }
            
        except Exception as e:
            print(f"[ALGO FFT ERROR] Exception in FFT processing: {e}")
            import sys
            sys.print_exception(e)
            return {
                'peak_freq_hz': 0.0,
                'peak_mag': 0.0,
                'noise_avg': 0.0,
                'detected': False,
                'snr': 0.0
            }
    
    async def process(self, data):
        """
        Process microwave sensor data with FFT or simple threshold detection.
        
        Args:
            data: dict with 'timestamp' and 'value' keys
                  'value' can be a float (simple mode) or dict with 'value' and 'raw_samples'
        
        Returns:
            dict with:
                - 'trigger': bool (True if streak threshold met)
                - 'value': int (scaled sensor value, 0-max_output)
                - 'timestamp': int (from input data)
                - Additional fields depending on mode (FFT or simple)
        """
        debug_print("[ALGO PROCESS]", f"{self.algo_id} - process() called")
        
        try:
            timestamp = data.get('timestamp', 0)
            sensor_data = data.get('value', 0.0)
            
            debug_print("[ALGO DATA]", f"Received data: timestamp={timestamp}")
            debug_print("[ALGO DATA]", f"Raw sensor_data type: {type(sensor_data)}")
            
            # Handle both dict and simple value formats
            if isinstance(sensor_data, dict):
                sensor_value = sensor_data.get('value', 0.0)
                raw_samples = sensor_data.get('raw_samples')
                debug_print("[ALGO DATA]", f"Dict format - sensor_value={sensor_value}, has_raw_samples={raw_samples is not None}")
                if raw_samples:
                    i_samples = raw_samples.get('i', [])
                    q_samples = raw_samples.get('q', [])
                    sample_rate = raw_samples.get('sample_rate_hz', 40000)
                    debug_print("[ALGO DATA]", f"Raw samples - I count={len(i_samples)}, Q count={len(q_samples)}, rate={sample_rate}Hz")
                    if i_samples:
                        debug_print("[ALGO DATA]", f"I sample preview (first 5): {i_samples[:5]}")
                    if q_samples:
                        debug_print("[ALGO DATA]", f"Q sample preview (first 5): {q_samples[:5]}")
            else:
                sensor_value = sensor_data
                raw_samples = None
                debug_print("[ALGO DATA]", f"Simple value format - sensor_value={sensor_value}")
            
            detected = False
            output_value = 0
            result_extras = {}
            
            # FFT mode processing
            if self.use_fft and raw_samples:
                debug_print("[ALGO STEP]", "Using FFT mode")
                i_samples = raw_samples.get('i', [])
                q_samples = raw_samples.get('q', [])
                sample_rate_hz = raw_samples.get('sample_rate_hz', 40000)
                
                if i_samples:
                    debug_print("[ALGO STEP]", f"Calling FFT analysis with {len(i_samples)} samples")
                    fft_result = await self._fft_peak_and_noise(i_samples, q_samples, sample_rate_hz)
                    detected = fft_result['detected']
                    
                    debug_print("[ALGO FFT]", f"Peak freq: {fft_result['peak_freq_hz']:.2f} Hz")
                    debug_print("[ALGO FFT]", f"Peak magnitude: {fft_result['peak_mag']:.2f}")
                    debug_print("[ALGO FFT]", f"Noise average: {fft_result['noise_avg']:.2f}")
                    debug_print("[ALGO FFT]", f"SNR: {fft_result['snr']:.2f}")
                    debug_print("[ALGO FFT]", f"Threshold multiplier: {self.fft_threshold_mult}")
                    debug_print("[ALGO FFT]", f"Detection result: {detected}")
                    
                    # Store FFT metrics
                    self.last_peak_freq_hz = fft_result['peak_freq_hz']
                    self.last_peak_mag = fft_result['peak_mag']
                    self.last_noise_avg = fft_result['noise_avg']
                    self.last_snr = fft_result['snr']
                    
                    # Scale peak magnitude to output range
                    # Normalize by sample count for consistency
                    sample_count = len(i_samples)
                    scaled = (fft_result['peak_mag'] / sample_count) * self.scale_factor
                    output_value = int(min(max(scaled, 0), self.max_output))
                    
                    debug_print("[ALGO STEP]", f"Scaled output: {scaled:.2f} -> clamped: {output_value}")
                    
                    result_extras = {
                        'peak_freq_hz': round(fft_result['peak_freq_hz'], 2),
                        'peak_mag': round(fft_result['peak_mag'], 2),
                        'noise_avg': round(fft_result['noise_avg'], 2),
                        'snr': round(fft_result['snr'], 2)
                    }
                else:
                    debug_print("[ALGO STEP]", "No I samples available, falling back to simple mode")
                    # No samples available, fall back to simple mode
                    detected = sensor_value >= self.threshold
                    output_value = int(min(max(sensor_value * self.scale_factor, 0), self.max_output))
                    debug_print("[ALGO STEP]", f"Simple fallback - detected={detected}, output={output_value}")
            
            # Simple threshold mode
            else:
                debug_print("[ALGO STEP]", "Using simple threshold mode")
                debug_print("[ALGO STEP]", f"Sensor value: {sensor_value}, Threshold: {self.threshold}")
                detected = sensor_value >= self.threshold
                output_value = int(min(max(sensor_value * self.scale_factor, 0), self.max_output))
                debug_print("[ALGO STEP]", f"Detection result: {detected}, Output value: {output_value}")
                result_extras = {'sensor_value': sensor_value}
            
            # Update streak counter
            if detected:
                self.current_streak += 1
                debug_print("[ALGO STREAK]", f"Detection! Streak increased to {self.current_streak}/{self.streak_required}")
            else:
                self.current_streak = 0
                debug_print("[ALGO STREAK]", "No detection, streak reset to 0")
            
            # Determine if we should trigger
            triggered = self.current_streak >= self.streak_required
            debug_print("[ALGO TRIGGER]", f"Trigger condition: {triggered} (streak {self.current_streak} >= required {self.streak_required})")
            
            # Prepare result
            result = {
                'trigger': triggered,
                'value': output_value,
                'timestamp': timestamp,
                'streak': self.current_streak
            }
            result.update(result_extras)
            
            debug_print("[ALGO RESULT]", "Final result prepared:")
            debug_print("[ALGO RESULT]", f"  trigger={triggered}, value={output_value}, streak={self.current_streak}")
            debug_print("[ALGO RESULT]", f"  extras={result_extras}")
            
            # Log trigger events
            if triggered:
                current_time = time.time()
                if current_time - self.last_trigger_time > 1.0:
                    debug_print("[ALGO TRIGGER EVENT]", "*** MOTION DETECTED ***")
                    if self.use_fft:
                        debug_print("[ALGO TRIGGER EVENT]", f"  Peak freq: {self.last_peak_freq_hz:.2f} Hz")
                        debug_print("[ALGO TRIGGER EVENT]", f"  SNR: {self.last_snr:.2f}")
                    else:
                        debug_print("[ALGO TRIGGER EVENT]", f"  Sensor value: {sensor_value:.2f}")
                    debug_print("[ALGO TRIGGER EVENT]", f"  Streak: {self.current_streak}")
                    debug_print("[ALGO TRIGGER EVENT]", f"  Output: {output_value}")
                    self.last_trigger_time = current_time
            
            return result
            
        except Exception as e:
            print(f"[ALGO ERROR] Exception in process(): {e}")
            import sys
            sys.print_exception(e)
            # Reset streak on error
            self.current_streak = 0
            print(f"[ALGO ERROR] Streak reset, returning no trigger")
            return {'trigger': False, 'value': 0}


# Example usage:
# from core.data_store import DataStore
# from communication.lora_interface import LoRaInterface
#
# # Create data store and LoRa interface
# data_store = DataStore()
# data_store.register_sensor("microwave1", 1000)
# lora = LoRaInterface(spi_id=0, cs_pin=5, reset_pin=14, frequency=915000000)
#
# # Create and run microwave detection algorithm
# params = {
#     "threshold": 150.0,
#     "streak_required": 3,
#     "max_output": 10000,
#     "scale_factor": 1.0
# }
# algo = MicrowaveDetectionAlgorithm(
#     "mw_detect1", "microwave1", data_store, lora, 0.1, params
# )
# await algo.run()

# Made with Bob