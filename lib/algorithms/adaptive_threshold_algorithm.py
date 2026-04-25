"""
AdaptiveThresholdAlgorithm - Dynamic baseline motion detection for microwave sensors

This algorithm uses an adaptive threshold approach that automatically adjusts to
ambient conditions. It maintains a moving average of recent "quiet" readings to
establish a dynamic baseline, then detects motion when the signal exceeds this
baseline by a configurable margin.

Key features:
- Adaptive baseline that adjusts to environmental changes
- Moving average filter for noise reduction
- Configurable sensitivity and adaptation rate
- Streak logic to filter transient events
- Works with both raw sensor values and I/Q samples

Algorithm approach:
1. Maintain a moving average of recent readings (baseline)
2. Only update baseline when no motion is detected (quiet periods)
3. Detect motion when current reading exceeds baseline + threshold
4. Use exponential moving average for smooth adaptation
5. Apply streak logic to confirm sustained motion

This is particularly useful in environments with:
- Varying ambient conditions (temperature, humidity)
- Gradual environmental changes
- Need for automatic calibration
- Different sensitivity requirements over time
"""

import time
from core.base_algorithm import BaseAlgorithm
from utils.logger import debug_print


class AdaptiveThresholdAlgorithm(BaseAlgorithm):
    """
    Adaptive threshold motion detection with dynamic baseline adjustment.
    
    This algorithm automatically adapts to changing environmental conditions
    by maintaining a moving average baseline of "quiet" periods. Motion is
    detected when the signal exceeds the baseline by a configurable margin.
    
    Parameters:
        initial_baseline: float - Starting baseline value (default: 100.0)
        threshold_margin: float - Detection margin above baseline (default: 50.0)
        adaptation_rate: float - Baseline adaptation speed 0-1 (default: 0.1)
        streak_required: int - Consecutive detections needed (default: 3)
        max_output: int - Maximum output value (default: 10000)
        scale_factor: float - Output scaling multiplier (default: 1.0)
        baseline_update_delay: float - Seconds to wait before updating baseline after motion (default: 2.0)
        use_raw_samples: bool - Use I/Q samples instead of sensor value (default: False)
    
    Example usage:
        params = {
            "initial_baseline": 100.0,
            "threshold_margin": 50.0,
            "adaptation_rate": 0.1,
            "streak_required": 3,
            "max_output": 10000,
            "scale_factor": 1.0,
            "baseline_update_delay": 2.0,
            "use_raw_samples": False
        }
        algo = AdaptiveThresholdAlgorithm(
            "adaptive1", "microwave1", data_store, lora, 0.1, params
        )
        await algo.run()
    """
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface,
                 check_interval, params, sensor_mac=None, monitor=None):
        """
        Initialize the adaptive threshold algorithm.
        
        Args:
            algo_id: Unique identifier for this algorithm instance
            sensor_id: ID of the microwave sensor to monitor
            data_store: DataStore instance for reading sensor data
            lora_interface: LoRaInterface instance for sending messages
            check_interval: Time in seconds between algorithm checks
            params: dict with algorithm parameters
            sensor_mac: 6-character hex MAC address for LoRa transmission
            monitor: SystemMonitor instance for tracking statistics
        """
        # Initialize base class with event mode
        super().__init__(algo_id, sensor_id, data_store, lora_interface,
                        check_interval, mode='event', params=params,
                        sensor_mac=sensor_mac, monitor=monitor)
        
        # Algorithm parameters
        self.initial_baseline = params.get('initial_baseline', 100.0)
        self.threshold_margin = params.get('threshold_margin', 50.0)
        self.adaptation_rate = params.get('adaptation_rate', 0.1)
        self.streak_required = params.get('streak_required', 3)
        self.max_output = params.get('max_output', 10000)
        self.scale_factor = params.get('scale_factor', 1.0)
        self.baseline_update_delay = params.get('baseline_update_delay', 2.0)
        self.use_raw_samples = params.get('use_raw_samples', False)
        
        # Validate parameters
        if self.threshold_margin < 0:
            print(f"[{self.algo_id}] Warning: threshold_margin {self.threshold_margin} < 0, using 0")
            self.threshold_margin = 0.0
        
        if self.adaptation_rate < 0 or self.adaptation_rate > 1:
            print(f"[{self.algo_id}] Warning: adaptation_rate {self.adaptation_rate} out of range [0,1], using 0.1")
            self.adaptation_rate = 0.1
        
        if self.streak_required < 1:
            print(f"[{self.algo_id}] Warning: streak_required {self.streak_required} < 1, using 1")
            self.streak_required = 1
        
        if self.max_output < 1 or self.max_output > 10000:
            print(f"[{self.algo_id}] Warning: max_output {self.max_output} out of range, using 10000")
            self.max_output = 10000
        
        if self.scale_factor <= 0:
            print(f"[{self.algo_id}] Warning: scale_factor {self.scale_factor} <= 0, using 1.0")
            self.scale_factor = 1.0
        
        if self.baseline_update_delay < 0:
            print(f"[{self.algo_id}] Warning: baseline_update_delay {self.baseline_update_delay} < 0, using 0")
            self.baseline_update_delay = 0.0
        
        # State tracking
        self.current_baseline = self.initial_baseline
        self.current_streak = 0
        self.last_motion_time = 0
        self.last_trigger_time = 0
        
        # Statistics
        self.total_readings = 0
        self.baseline_updates = 0
        self.min_baseline = self.initial_baseline
        self.max_baseline = self.initial_baseline
        
        print(f"[{self.algo_id}] AdaptiveThresholdAlgorithm configured:")
        print(f"  Initial baseline: {self.initial_baseline}")
        print(f"  Threshold margin: {self.threshold_margin}")
        print(f"  Adaptation rate: {self.adaptation_rate}")
        print(f"  Streak required: {self.streak_required}")
        print(f"  Max output: {self.max_output}")
        print(f"  Scale factor: {self.scale_factor}")
        print(f"  Baseline update delay: {self.baseline_update_delay}s")
        print(f"  Use raw samples: {self.use_raw_samples}")
    
    def _extract_signal_value(self, sensor_data):
        """
        Extract signal value from sensor data.
        
        Args:
            sensor_data: Either a float or dict with 'value' and optionally 'raw_samples'
        
        Returns:
            float: Signal value to use for detection
        """
        if isinstance(sensor_data, dict):
            if self.use_raw_samples and 'raw_samples' in sensor_data:
                # Use RMS of I/Q samples for more robust detection
                raw_samples = sensor_data['raw_samples']
                i_samples = raw_samples.get('i', [])
                q_samples = raw_samples.get('q', [])
                
                if i_samples:
                    # Calculate RMS (root mean square) of I channel
                    i_rms = (sum(x**2 for x in i_samples) / len(i_samples)) ** 0.5
                    
                    if q_samples:
                        # Calculate RMS of Q channel and combine
                        q_rms = (sum(x**2 for x in q_samples) / len(q_samples)) ** 0.5
                        # Use magnitude of I/Q vector
                        return (i_rms**2 + q_rms**2) ** 0.5
                    else:
                        return i_rms
            
            # Fall back to sensor value
            return sensor_data.get('value', 0.0)
        else:
            return sensor_data
    
    def _update_baseline(self, current_value):
        """
        Update the adaptive baseline using exponential moving average.
        
        Only updates during quiet periods (no recent motion detected).
        Uses exponential moving average for smooth adaptation:
        baseline = baseline * (1 - rate) + current_value * rate
        
        Args:
            current_value: Current sensor reading
        """
        current_time = time.time()
        
        # Only update baseline if enough time has passed since last motion
        if current_time - self.last_motion_time >= self.baseline_update_delay:
            # Exponential moving average
            self.current_baseline = (
                self.current_baseline * (1.0 - self.adaptation_rate) +
                current_value * self.adaptation_rate
            )
            
            # Track baseline statistics
            self.baseline_updates += 1
            if self.current_baseline < self.min_baseline:
                self.min_baseline = self.current_baseline
            if self.current_baseline > self.max_baseline:
                self.max_baseline = self.current_baseline
            
            debug_print("[ALGO BASELINE]", f"Baseline updated to {self.current_baseline:.2f}")
    
    async def process(self, data):
        """
        Process microwave sensor data with adaptive threshold detection.
        
        Args:
            data: dict with 'timestamp' and 'value' keys
        
        Returns:
            dict with:
                - 'trigger': bool (True if streak threshold met)
                - 'value': int (scaled sensor value, 0-max_output)
                - 'timestamp': int (from input data)
                - 'baseline': float (current adaptive baseline)
                - 'margin': float (detection margin above baseline)
                - 'signal_value': float (current signal value)
        """
        debug_print("[ALGO PROCESS]", f"{self.algo_id} - process() called")
        
        try:
            timestamp = data.get('timestamp', 0)
            sensor_data = data.get('value', 0.0)
            
            self.total_readings += 1
            
            # Extract signal value
            signal_value = self._extract_signal_value(sensor_data)
            debug_print("[ALGO DATA]", f"Signal value: {signal_value:.2f}")
            
            # Calculate detection threshold
            detection_threshold = self.current_baseline + self.threshold_margin
            debug_print("[ALGO THRESHOLD]", f"Baseline: {self.current_baseline:.2f}, Threshold: {detection_threshold:.2f}")
            
            # Detect motion
            detected = signal_value >= detection_threshold
            
            current_time = time.time()
            
            if detected:
                self.current_streak += 1
                self.last_motion_time = current_time
                debug_print("[ALGO STREAK]", f"Detection! Streak: {self.current_streak}/{self.streak_required}")
            else:
                self.current_streak = 0
                # Update baseline during quiet periods
                self._update_baseline(signal_value)
                debug_print("[ALGO STREAK]", "No detection, streak reset")
            
            # Determine if we should trigger
            triggered = self.current_streak >= self.streak_required
            
            # Calculate output value
            if triggered:
                # Scale based on how much signal exceeds baseline
                excess = signal_value - self.current_baseline
                scaled = (excess / self.threshold_margin) * self.scale_factor * 1000
                output_value = int(min(max(scaled, 0), self.max_output))
            else:
                output_value = 0
            
            # Prepare result
            result = {
                'trigger': triggered,
                'value': output_value,
                'timestamp': timestamp,
                'baseline': round(self.current_baseline, 2),
                'margin': round(self.threshold_margin, 2),
                'signal_value': round(signal_value, 2),
                'streak': self.current_streak
            }
            
            # Log trigger events
            if triggered and current_time - self.last_trigger_time > 1.0:
                debug_print("[ALGO TRIGGER EVENT]", "*** ADAPTIVE MOTION DETECTED ***")
                debug_print("[ALGO TRIGGER EVENT]", f"  Signal: {signal_value:.2f}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Baseline: {self.current_baseline:.2f}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Excess: {signal_value - self.current_baseline:.2f}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Streak: {self.current_streak}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Output: {output_value}")
                self.last_trigger_time = current_time
            
            return result
            
        except Exception as e:
            print(f"[ALGO ERROR] Exception in process(): {e}")
            import sys
            sys.print_exception(e)
            self.current_streak = 0
            return {'trigger': False, 'value': 0}
    
    def get_statistics(self):
        """
        Get algorithm statistics.
        
        Returns:
            dict: Statistics including baseline info and detection counts
        """
        return {
            'total_readings': self.total_readings,
            'baseline_updates': self.baseline_updates,
            'current_baseline': round(self.current_baseline, 2),
            'min_baseline': round(self.min_baseline, 2),
            'max_baseline': round(self.max_baseline, 2),
            'baseline_range': round(self.max_baseline - self.min_baseline, 2)
        }


# Made with Bob