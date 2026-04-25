"""
EnergyHysteresisAlgorithm - Energy-based motion detection with hysteresis state machine

This algorithm uses signal energy calculation combined with a hysteresis state machine
to provide robust motion detection with reduced false positives and false negatives.

Key features:
- Signal energy calculation from I/Q samples or sensor values
- Hysteresis state machine (IDLE, DETECTING, CONFIRMED, COOLDOWN)
- Separate thresholds for activation and deactivation
- Configurable state transition timings
- Energy accumulation over time windows
- Robust against noise and brief interruptions

Algorithm approach:
1. Calculate signal energy from I/Q samples (or use sensor value)
2. Accumulate energy over a sliding window
3. Use state machine with hysteresis:
   - IDLE: Waiting for motion, low threshold to enter DETECTING
   - DETECTING: Potential motion, accumulating evidence
   - CONFIRMED: Motion confirmed, high threshold to exit
   - COOLDOWN: Motion ended, waiting before returning to IDLE
4. Trigger only in CONFIRMED state
5. Require sustained energy to maintain CONFIRMED state

This is particularly useful for:
- Environments with intermittent noise
- Detecting sustained motion vs. brief disturbances
- Reducing false positives from transient events
- Maintaining detection through brief signal drops
"""

import time
from core.base_algorithm import BaseAlgorithm
from utils.logger import debug_print


class EnergyHysteresisAlgorithm(BaseAlgorithm):
    """
    Energy-based motion detection with hysteresis state machine.
    
    This algorithm calculates signal energy and uses a state machine with
    hysteresis to provide robust motion detection. The hysteresis prevents
    rapid state changes and reduces false positives.
    
    State machine:
    - IDLE: No motion detected, waiting for activation threshold
    - DETECTING: Potential motion, accumulating evidence
    - CONFIRMED: Motion confirmed, sending triggers
    - COOLDOWN: Motion ended, waiting before returning to IDLE
    
    Parameters:
        activation_threshold: float - Energy level to enter DETECTING (default: 150.0)
        confirmation_threshold: float - Energy level to enter CONFIRMED (default: 250.0)
        deactivation_threshold: float - Energy level to exit CONFIRMED (default: 100.0)
        detection_window: int - Number of readings to confirm motion (default: 3)
        cooldown_window: int - Number of readings in cooldown (default: 5)
        energy_window_size: int - Size of energy accumulation window (default: 5)
        max_output: int - Maximum output value (default: 10000)
        scale_factor: float - Output scaling multiplier (default: 1.0)
        use_raw_samples: bool - Calculate energy from I/Q samples (default: True)
    
    Example usage:
        params = {
            "activation_threshold": 150.0,
            "confirmation_threshold": 250.0,
            "deactivation_threshold": 100.0,
            "detection_window": 3,
            "cooldown_window": 5,
            "energy_window_size": 5,
            "max_output": 10000,
            "scale_factor": 1.0,
            "use_raw_samples": True
        }
        algo = EnergyHysteresisAlgorithm(
            "energy1", "microwave1", data_store, lora, 0.1, params
        )
        await algo.run()
    """
    
    # State machine states
    STATE_IDLE = 0
    STATE_DETECTING = 1
    STATE_CONFIRMED = 2
    STATE_COOLDOWN = 3
    
    STATE_NAMES = {
        0: "IDLE",
        1: "DETECTING",
        2: "CONFIRMED",
        3: "COOLDOWN"
    }
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface,
                 check_interval, params, sensor_mac=None, monitor=None):
        """
        Initialize the energy hysteresis algorithm.
        
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
        
        # Threshold parameters
        self.activation_threshold = params.get('activation_threshold', 150.0)
        self.confirmation_threshold = params.get('confirmation_threshold', 250.0)
        self.deactivation_threshold = params.get('deactivation_threshold', 100.0)
        
        # Window parameters
        self.detection_window = params.get('detection_window', 3)
        self.cooldown_window = params.get('cooldown_window', 5)
        self.energy_window_size = params.get('energy_window_size', 5)
        
        # Output parameters
        self.max_output = params.get('max_output', 10000)
        self.scale_factor = params.get('scale_factor', 1.0)
        self.use_raw_samples = params.get('use_raw_samples', True)
        
        # Validate parameters
        if self.activation_threshold < 0:
            print(f"[{self.algo_id}] Warning: activation_threshold < 0, using 0")
            self.activation_threshold = 0.0
        
        if self.confirmation_threshold < self.activation_threshold:
            print(f"[{self.algo_id}] Warning: confirmation_threshold < activation_threshold, adjusting")
            self.confirmation_threshold = self.activation_threshold * 1.5
        
        if self.deactivation_threshold > self.confirmation_threshold:
            print(f"[{self.algo_id}] Warning: deactivation_threshold > confirmation_threshold, adjusting")
            self.deactivation_threshold = self.confirmation_threshold * 0.7
        
        if self.detection_window < 1:
            print(f"[{self.algo_id}] Warning: detection_window < 1, using 1")
            self.detection_window = 1
        
        if self.cooldown_window < 1:
            print(f"[{self.algo_id}] Warning: cooldown_window < 1, using 1")
            self.cooldown_window = 1
        
        if self.energy_window_size < 1:
            print(f"[{self.algo_id}] Warning: energy_window_size < 1, using 1")
            self.energy_window_size = 1
        
        if self.max_output < 1 or self.max_output > 10000:
            print(f"[{self.algo_id}] Warning: max_output out of range, using 10000")
            self.max_output = 10000
        
        if self.scale_factor <= 0:
            print(f"[{self.algo_id}] Warning: scale_factor <= 0, using 1.0")
            self.scale_factor = 1.0
        
        # State tracking
        self.current_state = self.STATE_IDLE
        self.state_counter = 0
        self.energy_history = []
        self.last_trigger_time = 0
        
        # Statistics
        self.total_readings = 0
        self.state_transitions = {
            'idle_to_detecting': 0,
            'detecting_to_confirmed': 0,
            'detecting_to_idle': 0,
            'confirmed_to_cooldown': 0,
            'cooldown_to_idle': 0
        }
        
        print(f"[{self.algo_id}] EnergyHysteresisAlgorithm configured:")
        print(f"  Activation threshold: {self.activation_threshold}")
        print(f"  Confirmation threshold: {self.confirmation_threshold}")
        print(f"  Deactivation threshold: {self.deactivation_threshold}")
        print(f"  Detection window: {self.detection_window}")
        print(f"  Cooldown window: {self.cooldown_window}")
        print(f"  Energy window size: {self.energy_window_size}")
        print(f"  Max output: {self.max_output}")
        print(f"  Scale factor: {self.scale_factor}")
        print(f"  Use raw samples: {self.use_raw_samples}")
    
    def _calculate_energy(self, sensor_data):
        """
        Calculate signal energy from sensor data.
        
        For raw samples: Uses RMS energy of I/Q channels
        For sensor value: Uses the value directly
        
        Args:
            sensor_data: Either a float or dict with 'value' and optionally 'raw_samples'
        
        Returns:
            float: Signal energy value
        """
        if isinstance(sensor_data, dict):
            if self.use_raw_samples and 'raw_samples' in sensor_data:
                raw_samples = sensor_data['raw_samples']
                i_samples = raw_samples.get('i', [])
                q_samples = raw_samples.get('q', [])
                
                if i_samples:
                    # Calculate energy as sum of squared samples (proportional to power)
                    i_energy = sum(x**2 for x in i_samples) / len(i_samples)
                    
                    if q_samples:
                        q_energy = sum(x**2 for x in q_samples) / len(q_samples)
                        # Total energy is sum of I and Q energies
                        total_energy = i_energy + q_energy
                        # Normalize to reasonable range (ADC is 16-bit)
                        # Scale down from ~2^32 range to ~10000 range
                        return (total_energy / (65536.0 ** 2)) * 10000.0
                    else:
                        # Single channel
                        return (i_energy / (65536.0 ** 2)) * 10000.0
            
            # Fall back to sensor value
            return sensor_data.get('value', 0.0)
        else:
            return sensor_data
    
    def _update_energy_history(self, energy):
        """
        Update the energy history window.
        
        Maintains a sliding window of recent energy values for
        smoothing and trend analysis.
        
        Args:
            energy: Current energy value
        """
        self.energy_history.append(energy)
        
        # Keep only the most recent values
        if len(self.energy_history) > self.energy_window_size:
            self.energy_history.pop(0)
    
    def _get_average_energy(self):
        """
        Get the average energy over the current window.
        
        Returns:
            float: Average energy, or 0 if no history
        """
        if not self.energy_history:
            return 0.0
        return sum(self.energy_history) / len(self.energy_history)
    
    def _transition_state(self, new_state, reason=""):
        """
        Transition to a new state and log the change.
        
        Args:
            new_state: New state to transition to
            reason: Optional reason for the transition
        """
        old_state = self.current_state
        self.current_state = new_state
        self.state_counter = 0
        
        # Track transition statistics
        transition_key = f"{self.STATE_NAMES[old_state].lower()}_to_{self.STATE_NAMES[new_state].lower()}"
        if transition_key in self.state_transitions:
            self.state_transitions[transition_key] += 1
        
        debug_print("[ALGO STATE]", 
                   f"State transition: {self.STATE_NAMES[old_state]} -> {self.STATE_NAMES[new_state]}")
        if reason:
            debug_print("[ALGO STATE]", f"Reason: {reason}")
    
    async def process(self, data):
        """
        Process microwave sensor data with energy-based hysteresis detection.
        
        Args:
            data: dict with 'timestamp' and 'value' keys
        
        Returns:
            dict with:
                - 'trigger': bool (True if in CONFIRMED state)
                - 'value': int (scaled energy value, 0-max_output)
                - 'timestamp': int (from input data)
                - 'state': str (current state name)
                - 'energy': float (current energy value)
                - 'avg_energy': float (average energy over window)
        """
        debug_print("[ALGO PROCESS]", f"{self.algo_id} - process() called")
        
        try:
            timestamp = data.get('timestamp', 0)
            sensor_data = data.get('value', 0.0)
            
            self.total_readings += 1
            
            # Calculate energy
            energy = self._calculate_energy(sensor_data)
            self._update_energy_history(energy)
            avg_energy = self._get_average_energy()
            
            debug_print("[ALGO ENERGY]", f"Energy: {energy:.2f}, Avg: {avg_energy:.2f}")
            debug_print("[ALGO STATE]", f"Current state: {self.STATE_NAMES[self.current_state]}, Counter: {self.state_counter}")
            
            # State machine logic
            if self.current_state == self.STATE_IDLE:
                # IDLE: Waiting for activation
                if avg_energy >= self.activation_threshold:
                    self._transition_state(self.STATE_DETECTING, 
                                         f"Energy {avg_energy:.2f} >= activation {self.activation_threshold}")
                
            elif self.current_state == self.STATE_DETECTING:
                # DETECTING: Accumulating evidence
                self.state_counter += 1
                
                if avg_energy >= self.confirmation_threshold:
                    if self.state_counter >= self.detection_window:
                        self._transition_state(self.STATE_CONFIRMED,
                                             f"Energy {avg_energy:.2f} >= confirmation {self.confirmation_threshold} for {self.state_counter} readings")
                elif avg_energy < self.activation_threshold:
                    self._transition_state(self.STATE_IDLE,
                                         f"Energy {avg_energy:.2f} < activation {self.activation_threshold}")
                
            elif self.current_state == self.STATE_CONFIRMED:
                # CONFIRMED: Motion detected
                if avg_energy < self.deactivation_threshold:
                    self._transition_state(self.STATE_COOLDOWN,
                                         f"Energy {avg_energy:.2f} < deactivation {self.deactivation_threshold}")
                
            elif self.current_state == self.STATE_COOLDOWN:
                # COOLDOWN: Waiting before returning to IDLE
                self.state_counter += 1
                
                if avg_energy >= self.confirmation_threshold:
                    # Motion resumed, go back to CONFIRMED
                    self._transition_state(self.STATE_CONFIRMED,
                                         f"Energy {avg_energy:.2f} >= confirmation {self.confirmation_threshold}")
                elif self.state_counter >= self.cooldown_window:
                    self._transition_state(self.STATE_IDLE,
                                         f"Cooldown period {self.state_counter} >= {self.cooldown_window}")
            
            # Determine trigger and output
            triggered = self.current_state == self.STATE_CONFIRMED
            
            if triggered:
                # Scale output based on energy level
                scaled = (avg_energy / self.confirmation_threshold) * self.scale_factor * 1000
                output_value = int(min(max(scaled, 0), self.max_output))
            else:
                output_value = 0
            
            # Prepare result
            result = {
                'trigger': triggered,
                'value': output_value,
                'timestamp': timestamp,
                'state': self.STATE_NAMES[self.current_state],
                'energy': round(energy, 2),
                'avg_energy': round(avg_energy, 2),
                'state_counter': self.state_counter
            }
            
            # Log trigger events
            current_time = time.time()
            if triggered and current_time - self.last_trigger_time > 1.0:
                debug_print("[ALGO TRIGGER EVENT]", "*** ENERGY MOTION DETECTED ***")
                debug_print("[ALGO TRIGGER EVENT]", f"  State: {self.STATE_NAMES[self.current_state]}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Energy: {energy:.2f}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Avg Energy: {avg_energy:.2f}")
                debug_print("[ALGO TRIGGER EVENT]", f"  Output: {output_value}")
                self.last_trigger_time = current_time
            
            return result
            
        except Exception as e:
            print(f"[ALGO ERROR] Exception in process(): {e}")
            import sys
            sys.print_exception(e)
            return {'trigger': False, 'value': 0}
    
    def get_statistics(self):
        """
        Get algorithm statistics.
        
        Returns:
            dict: Statistics including state transitions and current state
        """
        return {
            'total_readings': self.total_readings,
            'current_state': self.STATE_NAMES[self.current_state],
            'state_counter': self.state_counter,
            'energy_window_size': len(self.energy_history),
            'avg_energy': round(self._get_average_energy(), 2),
            'transitions': self.state_transitions.copy()
        }


# Made with Bob