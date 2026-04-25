"""
Protocol module for LoRa payload encoding/decoding.

This module centralizes all protocol constants, sensor enum mappings,
and payload encode/decode logic according to PROTOCOL.md.
"""

from lib.protocol.payload import (
    # Protocol constants
    PROTOCOL_VERSION,
    FIXED_HEADER_SIZE,
    SENSOR_PAIR_SIZE,
    
    # Sensor enums
    SensorEnum,
    
    # Value semantics
    VALUE_NOT_INSTALLED,
    VALUE_NOT_TRIGGERED,
    VALUE_MIN_TRIGGERED,
    VALUE_MAX,
    
    # Encode/decode functions
    encode_payload,
    decode_payload,
    
    # Helper functions
    get_sensor_enum_from_type,
    get_sensor_type_from_enum,
)

__all__ = [
    'PROTOCOL_VERSION',
    'FIXED_HEADER_SIZE',
    'SENSOR_PAIR_SIZE',
    'SensorEnum',
    'VALUE_NOT_INSTALLED',
    'VALUE_NOT_TRIGGERED',
    'VALUE_MIN_TRIGGERED',
    'VALUE_MAX',
    'encode_payload',
    'decode_payload',
    'get_sensor_enum_from_type',
    'get_sensor_type_from_enum',
]

# Made with Bob
