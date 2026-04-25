"""
Algorithms Package - Algorithm implementations for sensor data processing

This package contains various algorithm implementations that process sensor data
and trigger LoRa messages based on specific conditions.

Available Algorithms:
- RandomAlgorithm: Random value generator for testing
- MicrowaveDetectionAlgorithm: FFT-based threshold + streak detection for microwave sensors
- AdaptiveThresholdAlgorithm: Adaptive baseline with dynamic threshold adjustment
- EnergyHysteresisAlgorithm: Energy-based detection with hysteresis state machine
- MagnetometerDetectionAlgorithm: Magnetic field disturbance detection for vehicle/metal detection
"""


from algorithms.random_algorithm import RandomAlgorithm
from algorithms.microwave_detection_algorithm import MicrowaveDetectionAlgorithm
from algorithms.adaptive_threshold_algorithm import AdaptiveThresholdAlgorithm
from algorithms.energy_hysteresis_algorithm import EnergyHysteresisAlgorithm
from algorithms.magnetometer_detection_algorithm import MagnetometerDetectionAlgorithm

__all__ = [
    'RandomAlgorithm',
    'MicrowaveDetectionAlgorithm',
    'AdaptiveThresholdAlgorithm',
    'EnergyHysteresisAlgorithm',
    'MagnetometerDetectionAlgorithm'
]

# Made with Bob