"""
RandomAlgorithm - Event-based random value generator

This algorithm generates random values within a configured range and triggers
on every check. It's useful for testing the system without relying on actual
sensor thresholds or patterns.
"""

import time
from core.base_algorithm import BaseAlgorithm


class RandomAlgorithm(BaseAlgorithm):
    """
    Event-based random value generator algorithm.
    
    This algorithm processes sensor values but generates random output values
    within a configured range. It can be set to always trigger or to trigger
    randomly based on a probability.
    
    This is useful for:
    - Testing LoRa communication without real sensor conditions
    - Generating test data patterns
    - Debugging the system architecture
    - Demonstrations
    
    Parameters:
        min_value: int - Minimum random value (0-10000, default: 0)
        max_value: int - Maximum random value (0-10000, default: 10000)
        trigger_probability: float - Probability of triggering (0.0-1.0, default: 1.0)
    
    Example usage:
        params = {"min_value": 1000, "max_value": 9000, "trigger_probability": 1.0}
        algo = RandomAlgorithm("random1", "alibi1", data_store, lora, 2.0, params)
        await algo.run()
    """
    
    def __init__(self, algo_id, sensor_id, data_store, lora_interface, 
                 check_interval, params):
        """
        Initialize the random algorithm.
        
        Args:
            algo_id: Unique identifier for this algorithm instance
            sensor_id: ID of the sensor to monitor
            data_store: DataStore instance for reading sensor data
            lora_interface: LoRaInterface instance for sending messages
            check_interval: Time in seconds between algorithm checks
            params: dict with 'min_value' (int), 'max_value' (int), 
                    and 'trigger_probability' (float)
        """
        # Initialize base class with event mode
        super().__init__(algo_id, sensor_id, data_store, lora_interface, 
                        check_interval, mode='event', params=params)
        
        # Extract and validate parameters
        self.min_value = params.get('min_value', 0)
        self.max_value = params.get('max_value', 10000)
        self.trigger_probability = params.get('trigger_probability', 1.0)
        
        # Validate ranges
        if self.min_value < 0:
            print(f"[{self.algo_id}] Warning: min_value {self.min_value} < 0, using 0")
            self.min_value = 0
        
        if self.max_value > 10000:
            print(f"[{self.algo_id}] Warning: max_value {self.max_value} > 10000, using 10000")
            self.max_value = 10000
        
        if self.min_value > self.max_value:
            print(f"[{self.algo_id}] Warning: min_value > max_value, swapping")
            self.min_value, self.max_value = self.max_value, self.min_value
        
        if self.trigger_probability < 0.0 or self.trigger_probability > 1.0:
            print(f"[{self.algo_id}] Warning: trigger_probability {self.trigger_probability} out of range, using 1.0")
            self.trigger_probability = 1.0
        
        # Initialize random seed based on time
        self._seed = int(time.time() * 1000) % 2147483647
        
        print(f"[{self.algo_id}] RandomAlgorithm configured: range=[{self.min_value}, {self.max_value}], probability={self.trigger_probability}")
    
    def _random(self):
        """
        Simple linear congruential generator for random numbers.
        
        This is a basic PRNG that works in MicroPython without importing random.
        Uses the formula: seed = (a * seed + c) mod m
        
        Returns:
            float: Random value between 0.0 and 1.0
        """
        # LCG parameters (from Numerical Recipes)
        a = 1664525
        c = 1013904223
        m = 2147483647
        
        self._seed = (a * self._seed + c) % m
        return self._seed / m
    
    def _random_int(self, min_val, max_val):
        """
        Generate a random integer in the given range.
        
        Args:
            min_val: Minimum value (inclusive)
            max_val: Maximum value (inclusive)
        
        Returns:
            int: Random integer in [min_val, max_val]
        """
        range_size = max_val - min_val + 1
        return min_val + int(self._random() * range_size)
    
    async def process(self, data):
        """
        Process sensor data and generate random output.
        
        Args:
            data: dict with 'timestamp' and 'value' keys
        
        Returns:
            dict with:
                - 'trigger': bool (True based on probability)
                - 'value': int (random value in configured range)
                - 'timestamp': int (from input data)
                - 'sensor_value': float (original sensor value for reference)
        """
        try:
            # Extract sensor value for reference
            sensor_value = data.get('value', 0.0)
            timestamp = data.get('timestamp', 0)
            
            # Determine if we should trigger based on probability
            triggered = self._random() < self.trigger_probability
            
            # Generate random value in configured range
            random_value = self._random_int(self.min_value, self.max_value)
            
            # Prepare result
            result = {
                'trigger': triggered,
                'value': random_value,
                'timestamp': timestamp,
                'sensor_value': sensor_value
            }
            
            if triggered:
                print(f"[{self.algo_id}] Random trigger: value={random_value}, sensor={sensor_value:.2f}")
            
            return result
            
        except Exception as e:
            print(f"[{self.algo_id}] Error in process(): {e}")
            return {'trigger': False, 'value': 0}


# Made with Bob