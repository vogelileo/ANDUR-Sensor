"""
LoRa communication interface for the MicroPython Sensor System.

This module provides a simple, extensible stub implementation for LoRa
communication. It already formats payloads into a compact 4-byte binary
representation and simulates transmission using logging via print().

Example usage:
# from machine import SPI, Pin
# spi = SPI(0, baudrate=1000000, polarity=0, phase=0)
# lora = LoRaInterface(spi, cs_pin=Pin(5), reset_pin=Pin(6), config={})
# await lora.initialize()
# await lora.send("magnetic", "threshold", 7500)
"""

from lib.utils.lora_formatter import LoRaMessageFormatter

SENSOR_TYPE_MAP = {
    "magnetic": 0,
    "temperature": 1,
    "pressure": 2,
    "humidity": 3
}

ALGO_TYPE_MAP = {
    "threshold": 0,
    "moving_average": 1,
    "peak_detector": 2,
    "anomaly": 3
}


class LoRaInterface:
    """
    Stub LoRa interface for development and testing.

    The class accepts SPI bus and control pins so it can later be extended
    to support a real LoRa radio module without changing the public API.
    """

    def __init__(self, spi_bus, cs_pin, reset_pin, config, monitor=None):
        """
        Initialize the LoRa interface.

        Args:
            spi_bus: Configured SPI bus instance
            cs_pin: Chip-select pin object
            reset_pin: Reset pin object
            config: Dictionary with LoRa configuration values
            monitor: SystemMonitor instance for tracking messages
        """
        self.spi_bus = spi_bus
        self.cs_pin = cs_pin
        self.reset_pin = reset_pin
        self.config = config or {}
        self.monitor = monitor
        self.initialized = False

        print("[LoRa] Interface created (stub mode)")

    async def initialize(self):
        """
        Initialize the LoRa module.

        For now, this method only logs the configured setup and marks the
        interface as initialized. Real hardware setup can be added later.
        """
        print("[LoRa] Initializing LoRa module (stub)")
        print("[LoRa] SPI bus: {}".format(self.spi_bus))
        print("[LoRa] CS pin: {}".format(self.cs_pin))
        print("[LoRa] Reset pin: {}".format(self.reset_pin))
        print("[LoRa] Config: {}".format(self.config))

        self.initialized = True

    async def send(self, payload):
        """
        Send a LoRa message (serial print mode).

        In this simplified configuration, instead of transmitting via LoRa hardware,
        the payload is printed to serial/console output for debugging and testing.

        Args:
            payload: dict with message data containing:
                - 'algo_id': Algorithm identifier
                - 'sensor_id': Sensor identifier
                - 'value': Integer value (0-10000)
                - 'timestamp': Timestamp of the reading
                - Additional fields as needed

        Returns:
            None (prints to serial instead of transmitting)
        """
        if not self.initialized:
            print("[LoRa] Warning: send() called before initialize()")
        
        # Format as a more readable serial message
        algo_id = payload.get('algo_id', 'unknown')
        sensor_id = payload.get('sensor_id', 'unknown')
        value = payload.get('value', 0)
        timestamp = payload.get('timestamp', 0)
        
        formatted_msg = LoRaMessageFormatter.format_for_console(algo_id, sensor_id, value, timestamp)
        print(formatted_msg)
        
        # Track message in monitor
        if self.monitor:
            self.monitor.add_lora_message(algo_id, sensor_id, value, timestamp)
        
        # In a real LoRa implementation, you would:
        # 1. Format the payload into a compact binary message
        # 2. Transmit via the LoRa radio module
        # For example:
        # binary_payload = self._format_payload(sensor_id, algo_id, value)
        # self.radio.send(binary_payload)

    def _format_payload(self, sensor_type, algo_type, value):
        """
        Format the LoRa payload as a compact 4-byte binary message.

        Payload layout:
            Byte 0: sensor type ID
            Byte 1: algorithm type ID
            Byte 2: value high byte
            Byte 3: value low byte

        Args:
            sensor_type: Sensor type name
            algo_type: Algorithm type name
            value: Integer value in range 0-10000

        Returns:
            bytes object with exactly 4 bytes

        Raises:
            ValueError: If sensor/algo type is unknown or value is out of range
        """
        if sensor_type not in SENSOR_TYPE_MAP:
            raise ValueError("Unknown sensor type: {}".format(sensor_type))

        if algo_type not in ALGO_TYPE_MAP:
            raise ValueError("Unknown algorithm type: {}".format(algo_type))

        if not isinstance(value, int):
            raise ValueError("Value must be an integer")

        if value < 0 or value > 10000:
            raise ValueError("Value out of range: {}".format(value))

        sensor_id = SENSOR_TYPE_MAP[sensor_type]
        algo_id = ALGO_TYPE_MAP[algo_type]

        high_byte = (value >> 8) & 0xFF
        low_byte = value & 0xFF

        return bytes([sensor_id, algo_id, high_byte, low_byte])


# Made with Bob