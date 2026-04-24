"""
Communication module for MicroPython Sensor System

Contains communication interfaces for transmitting processed sensor data.
Currently includes a stub LoRa interface for development and testing.
"""

from communication.lora_interface import LoRaInterface

__all__ = ['LoRaInterface']

# Made with Bob