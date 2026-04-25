"""
MagnetometerDetectionAlgorithm - Magnetic field disturbance detection for vehicle/metal detection

This algorithm detects significant changes in the magnetic field that could indicate
a car or large metal object passing by. It uses a combination of baseline tracking,
deviation detection, and rate-of-change analysis to identify magnetic disturbances.

Key features:
- Adaptive baseline tracking of ambient magnetic field
- Deviation threshold detection for field magnitude changes
- Rate-of-change (gradient) detection for rapid field variations
- Moving average filter for noise reduction
- Configurable sensitivity and adaptation parameters
- Works with 3-axis magnetometer data (X, Y, Z) and magnitude

Algorithm approach:
1. Maintain a moving average baseline of the magnetic field magnitude
2. Calculate deviation from baseline (absolute difference)
3. Calculate rate of change (gradient) between consecutive readings
4. Detect disturbances when deviation or gradient exceed thresholds
5. Use streak logic to confirm sustained disturbances
6. Adapt baseline during quiet periods to handle environmental drift

This is particularly useful for:
- Vehicle detection (cars passing by cause magnetic disturbances)
- Metal object detection
- Perimeter security applications
- Traffic monitoring
- Parking space occupancy detection
"""

import time
from core.base_algorithm import BaseAlgorithm
from utils.logger import debug_print


class MagnetometerDetectionAlgorithm(BaseAlgorithm):
    """
    Magnetometer-based detection of magnetic field disturbances.
    
    This algorithm detects significant changes in the magnetic field by tracking
    deviations from a baseline and monitoring the rate of change. It's designed
    to detect vehicles, large metal objects, or other sources of magnetic disturbance.
    
    Parameters:
        initial_baseline: float - Starting baseline magnitude in raw counts (default: 0.0 for auto-init)
        deviation_threshold: float - Magnitude deviation to trigger detection in raw counts (default: 500.0)
        gradient_threshold: float - Rate of change threshold in raw counts/reading (default: 300.0)
        adaptation_rate: float - Baseline adaptation speed 0-1 (default: 0.05)
        baseline_window_size: int - Size of moving average window (default: 10)
        streak_required: int - Consecutive detections needed (default: 2)
        max_output: int - Maximum output value (default: 10000)
        scale_factor: float - Output scaling multiplier (default: 1.0)
        baseline_update_delay: float - Seconds to wait before updating baseline after detection (default: 3.0)
        use_magnitude: bool - Use magnitude instead of individual axes (default: True)
    
    Example usage:
        params = {
            "initial_baseline": 50.0,
            "deviation_threshold": 5.0,
            "gradient_threshold": 3.0,
            "adaptation_rate": 0.05,
            "baseline_window_size": 10,
            "streak_required": 2,
            "max_output": 10000,
            "scale_factor": 1.0,
            "baseline_update_delay": 3.0,
            "use_magnitude": True
        }
        algo = MagnetometerDetectionAlgorithm(
            "mag_detect1", "magnetometer1", data_store, lora, 0.2, params
        )
        await algo.run()
    """
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface,
                 check_interval, params, sensor_mac=None, monitor=None, installed_sensors=None):
        """
        Initialize the magnetometer detection algorithm.
        
        Args:
            algo_id: Unique identifier for this algorithm instance
            sensor_id: ID of the magnetometer sensor to monitor
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
        
        # Algorithm parameters
        self.initial_baseline = params.get('initial_baseline', 50.0)
        self.deviation_threshold = params.get('deviation_threshold', 5.0)
        self.gradient_threshold = params.get('gradient_threshold', 3.0)
        self.adaptation_rate = params.get('adaptation_rate', 0.05)
        self.baseline_window_size = params.get('baseline_window_size', 10)
        self.streak_required = params.get('streak_required', 2)
        self.max_output = params.get('max_output', 10000)
        self.scale_factor = params.get('scale_factor', 1.0)
        self.baseline_update_delay = params.get('baseline_update_delay', 3.0)
        self.use_magnitude = params.get('use_magnitude', True)
        
        # Validate parameters
        if self.deviation_threshold < 0:
            print(f"[{self.algo_id}] Warning: deviation_threshold {self.deviation_threshold} < 0, using 0")
            self.deviation_threshold = 0.0
        
        if self.gradient_threshold < 0:
            print(f"[{self.algo_id}] Warning: gradient_threshold {self.gradient_threshold} < 0, using 0")
            self.gradient_threshold = 0.0
        
        if self.adaptation_rate < 0 or self.adaptation_rate > 1:
            print(f"[{self.algo_id}] Warning: adaptation_rate {self.adaptation_rate} out of range [0,1], using 0.05")
            self.adaptation_rate = 0.05
        
        if self.baseline_window_size < 1:
            print(f"[{self.algo_id}] Warning: baseline_window_size {self.baseline_window_size} < 1, using 1")
            self.baseline_window_size = 1
        
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
        self.baseline_history = []
        self.last_magnitude = None
        self.current_streak = 0
        self.last_detection_time = 0
        self.last_trigger_time = 0
        self.baseline_initialized = (self.initial_baseline != 0.0)  # Track if baseline needs auto-init
        
        # Statistics
        self.total_readings = 0
        self.baseline_updates = 0
        self.deviation_detections = 0
        self.gradient_detections = 0
        self.min_baseline = self.initial_baseline
        self.max_baseline = self.initial_baseline
        self.max_deviation_seen = 0.0
        self.max_gradient_seen = 0.0
        
        print(f"[{self.algo_id}] MagnetometerDetectionAlgorithm configured:")
        print(f"  Initial baseline: {self.initial_baseline} counts")
        print(f"  Deviation threshold: {self.deviation_threshold} counts")
        print(f"  Gradient threshold: {self.gradient_threshold} counts/reading")
        print(f"  Adaptation rate: {self.adaptation_rate}")
        print(f"  Baseline window size: {self.baseline_window_size}")
        print(f"  Streak required: {self.streak_required}")
        print(f"  Max output: {self.max_output}")
        print(f"  Scale factor: {self.scale_factor}")
        print(f"  Baseline update delay: {self.baseline_update_delay}s")
        print(f"  Use magnitude: {self.use_magnitude}")
    
    def _extract_field_value(self, sensor_data):
        """
        Extract magnetic field value from sensor data using raw counts.
        
        Args:
            sensor_data: dict with 'raw_samples' containing {'x', 'y', 'z'} raw counts
        
        Returns:
            float: Magnetic field value to use for detection (in raw counts)
        """
        if isinstance(sensor_data, dict):
            # Get raw samples from sensor data
            raw_samples = sensor_data.get('raw_samples', {})
            raw_x = raw_samples.get('x', 0)
            raw_y = raw_samples.get('y', 0)
            raw_z = raw_samples.get('z', 0)
            
            if self.use_magnitude:
                # Calculate magnitude from raw counts: sqrt(x² + y² + z²)
                import math
                magnitude = math.sqrt(raw_x * raw_x + raw_y * raw_y + raw_z * raw_z)
                return magnitude
            else:
                # Use maximum absolute value across all three axes
                # This ensures detection works for disturbances in ANY axis direction
                return max(abs(raw_x), abs(raw_y), abs(raw_z))
        else:
            return sensor_data
    
    def _update_baseline_history(self, field_value):
        """
        Update the baseline history window.
        
        Maintains a sliding window of recent field values for
        calculating the moving average baseline.
        
        Args:
            field_value: Current magnetic field value
        """
        self.baseline_history.append(field_value)
        
        # Keep only the most recent values
        if len(self.baseline_history) > self.baseline_window_size:
            self.baseline_history.pop(0)
    
    def _calculate_baseline(self):
        """
        Calculate the current baseline from history window.
        
        Returns:
            float: Average of values in baseline history
        """
        if not self.baseline_history:
            return self.current_baseline
        return sum(self.baseline_history) / len(self.baseline_history)
    
    def _update_baseline(self, field_value):
        """
        Update the adaptive baseline using exponential moving average.
        
        Only updates during quiet periods (no recent detection).
        
        Args:
            field_value: Current magnetic field reading
        """
        current_time = time.time()
        
        # Only update baseline if enough time has passed since last detection
        if current_time - self.last_detection_time >= self.baseline_update_delay:
            # Add to history window
            self._update_baseline_history(field_value)
            
            # Calculate new baseline from window
            window_baseline = self._calculate_baseline()
            
            # Apply exponential moving average for smooth adaptation
            self.current_baseline = (
                self.current_baseline * (1.0 - self.adaptation_rate) +
                window_baseline * self.adaptation_rate
            )
            
            # Track baseline statistics
            self.baseline_updates += 1
            if self.current_baseline < self.min_baseline:
                self.min_baseline = self.current_baseline
            if self.current_baseline > self.max_baseline:
                self.max_baseline = self.current_baseline
    
    async def process(self, data):
        """
        Process magnetometer sensor data for disturbance detection.
        
        Args:
            data: dict with 'timestamp' and 'value' keys
                  'value' contains dict with 'value' (magnitude), 'x', 'y', 'z'
        
        Returns:
            dict with:
                - 'trigger': bool (True if streak threshold met)
                - 'value': int (scaled disturbance value, 0-max_output)
                - 'timestamp': int (from input data)
                - 'baseline': float (current adaptive baseline in raw counts)
                - 'field_value': float (current field value in raw counts)
                - 'deviation': float (deviation from baseline in raw counts)
                - 'gradient': float (rate of change in raw counts/reading)
                - 'detection_type': str (what triggered: 'deviation', 'gradient', 'both', or 'none')
        """
        try:
            timestamp = data.get('timestamp', 0)
            sensor_data = data.get('value', {})
            
            self.total_readings += 1
            
            # Extract field value
            field_value = self._extract_field_value(sensor_data)
            
            # Auto-initialize baseline from first readings if initial_baseline was 0.0
            if not self.baseline_initialized:
                if len(self.baseline_history) < self.baseline_window_size:
                    # Collect initial readings to establish baseline
                    self.baseline_history.append(field_value)
                    
                    if len(self.baseline_history) == self.baseline_window_size:
                        # Calculate initial baseline from collected readings
                        self.current_baseline = sum(self.baseline_history) / len(self.baseline_history)
                        self.baseline_initialized = True
                        print(f"[{self.algo_id}] BASELINE AUTO-INITIALIZED to {self.current_baseline:.2f} counts from {self.baseline_window_size} readings")
                    
                    # Return no detection during initialization phase
                    return {
                        'trigger': False,
                        'value': 0,
                        'timestamp': timestamp,
                        'baseline': round(self.current_baseline, 2),
                        'field_value': round(field_value, 2),
                        'deviation': 0.0,
                        'gradient': 0.0,
                        'detection_type': 'initializing',
                        'streak': 0
                    }
            
            # Calculate deviation from baseline
            deviation = abs(field_value - self.current_baseline)
            
            # Track maximum deviation seen
            if deviation > self.max_deviation_seen:
                self.max_deviation_seen = deviation
            
            # Calculate gradient (rate of change)
            gradient = 0.0
            if self.last_magnitude is not None:
                gradient = abs(field_value - self.last_magnitude)
                
                # Track maximum gradient seen
                if gradient > self.max_gradient_seen:
                    self.max_gradient_seen = gradient
            
            # Update last magnitude for next gradient calculation
            self.last_magnitude = field_value
            
            # Detect disturbances
            deviation_detected = deviation >= self.deviation_threshold
            gradient_detected = gradient >= self.gradient_threshold
            detected = deviation_detected or gradient_detected
            
            # Track detection types
            if deviation_detected:
                self.deviation_detections += 1
            if gradient_detected:
                self.gradient_detections += 1
            
            # Determine detection type
            if deviation_detected and gradient_detected:
                detection_type = 'both'
            elif deviation_detected:
                detection_type = 'deviation'
            elif gradient_detected:
                detection_type = 'gradient'
            else:
                detection_type = 'none'
            
            current_time = time.time()
            
            if detected:
                self.current_streak += 1
                self.last_detection_time = current_time
            else:
                self.current_streak = 0
                # Update baseline during quiet periods
                self._update_baseline(field_value)
            
            # Determine if we should trigger
            triggered = self.current_streak >= self.streak_required
            
            # Calculate output value
            if triggered:
                # Scale based on the larger of deviation or gradient
                disturbance_magnitude = max(deviation, gradient)
                threshold_used = max(self.deviation_threshold, self.gradient_threshold)
                
                # Scale output: higher disturbance = higher value
                scaled = (disturbance_magnitude / threshold_used) * self.scale_factor * 1000
                output_value = int(min(max(scaled, 0), self.max_output))
            else:
                output_value = 0
            
            # Prepare result
            result = {
                'trigger': triggered,
                'value': output_value,
                'timestamp': timestamp,
                'baseline': round(self.current_baseline, 2),
                'field_value': round(field_value, 2),
                'deviation': round(deviation, 2),
                'gradient': round(gradient, 2),
                'detection_type': detection_type,
                'streak': self.current_streak
            }
            
            # Log trigger events only
            if triggered and current_time - self.last_trigger_time > 1.0:
                print(f"[{self.algo_id}] MAGNETIC DISTURBANCE: Field={field_value:.2f}, Baseline={self.current_baseline:.2f}, Dev={deviation:.2f}, Grad={gradient:.2f}, Type={detection_type} (raw counts)")
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
            'baseline_range': round(self.max_baseline - self.min_baseline, 2),
            'deviation_detections': self.deviation_detections,
            'gradient_detections': self.gradient_detections,
            'max_deviation_seen': round(self.max_deviation_seen, 2),
            'max_gradient_seen': round(self.max_gradient_seen, 2),
            'baseline_history_size': len(self.baseline_history)
        }


# Made with Bob