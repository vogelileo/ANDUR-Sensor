"""
Sensors Module - Sensor implementations for MicroPython

This module contains concrete sensor implementations that inherit from BaseSensor.
Each sensor handles specific hardware communication and data reading.
"""

from .alibi_sensor import AlibiSensor
from .microwave_sensor import MicrowaveSensor

__all__ = ['AlibiSensor', 'MicrowaveSensor']

# Made with Bob