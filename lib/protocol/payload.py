"""
LoRa Payload Protocol Implementation

This module implements the protocol defined in PROTOCOL.md for encoding and
decoding LoRa payloads with variable-length sensor data.

Protocol Structure:
- Fixed header (14 bytes): version, device_id, gps_lat, gps_lon, battery, hops
- Repeated sensor pairs (2 bytes each): [SensorEnum, Value] for all installed sensors

Sensor enums follow PROTOCOL.md:
  1 - Microphone
  2 - Bluetooth
  3 - Audio
  4 - Magnetometer
  5 - RFBeam
  6 - Camera
  7 - Seismic

Value byte semantics:
  0 - Not installed/not used
  1 - Installed but not triggered
  2-255 - Installed with sensor-specific value
"""

import struct

# Protocol constants
PROTOCOL_VERSION = 1
FIXED_HEADER_SIZE = 14  # version(1) + device_id(3) + gps_lat(4) + gps_lon(4) + battery(1) + hops(1)
SENSOR_PAIR_SIZE = 2    # SensorEnum(1) + Value(1)

# Value byte semantics
VALUE_NOT_INSTALLED = 0
VALUE_NOT_TRIGGERED = 1
VALUE_MIN_TRIGGERED = 2
VALUE_MAX = 255


class SensorEnum:
    """
    Sensor enumeration values according to PROTOCOL.md.
    
    Note: 0 is reserved for not-installed/not-used.
    GPS and battery are NOT included in the repeated sensor list.
    """
    NOT_INSTALLED = 0
    MICROPHONE = 1
    BLUETOOTH = 2
    AUDIO = 3
    MAGNETOMETER = 4
    RFBEAM = 5
    CAMERA = 6
    SEISMIC = 7


# Mapping from sensor type strings (from config) to protocol enums
SENSOR_TYPE_TO_ENUM = {
    'microphone': SensorEnum.MICROPHONE,
    'bluetooth': SensorEnum.BLUETOOTH,
    'audio': SensorEnum.AUDIO,
    'magnetometer': SensorEnum.MAGNETOMETER,
    'magnetic': SensorEnum.MAGNETOMETER,  # Alias
    'rfbeam': SensorEnum.RFBEAM,
    'microwave': SensorEnum.RFBEAM,  # Map microwave to RFBeam
    'camera': SensorEnum.CAMERA,
    'seismic': SensorEnum.SEISMIC,
    'alibi': SensorEnum.SEISMIC,  # Map alibi to seismic as fallback
}

# Reverse mapping
ENUM_TO_SENSOR_TYPE = {
    SensorEnum.MICROPHONE: 'microphone',
    SensorEnum.BLUETOOTH: 'bluetooth',
    SensorEnum.AUDIO: 'audio',
    SensorEnum.MAGNETOMETER: 'magnetometer',
    SensorEnum.RFBEAM: 'rfbeam',
    SensorEnum.CAMERA: 'camera',
    SensorEnum.SEISMIC: 'seismic',
}


def get_sensor_enum_from_type(sensor_type):
    """
    Get protocol sensor enum from sensor type string.
    
    Args:
        sensor_type: Sensor type string (e.g., 'microwave', 'alibi')
        
    Returns:
        int: SensorEnum value, or SensorEnum.NOT_INSTALLED if unknown
    """
    # Normalize: lowercase and strip common suffixes
    normalized = sensor_type.lower().strip()
    for suffix in ['_sensor', 'sensor']:
        normalized = normalized.replace(suffix, '')
    normalized = normalized.strip('_')
    
    return SENSOR_TYPE_TO_ENUM.get(normalized, SensorEnum.NOT_INSTALLED)


def get_sensor_type_from_enum(sensor_enum):
    """
    Get sensor type string from protocol enum.
    
    Args:
        sensor_enum: SensorEnum value
        
    Returns:
        str: Sensor type name, or 'unknown' if not found
    """
    return ENUM_TO_SENSOR_TYPE.get(sensor_enum, 'unknown')


def encode_payload(version, device_id, gps_lat, gps_lon, battery, hops, sensor_data):
    """
    Encode a LoRa payload according to PROTOCOL.md.
    
    Args:
        version: Protocol version (1 byte, typically 1)
        device_id: 3-byte device MAC address (bytes or hex string)
        gps_lat: GPS latitude (float, -90 to 90)
        gps_lon: GPS longitude (float, -180 to 180)
        battery: Battery level (int, 0-100)
        hops: Hop count (int, 0-255)
        sensor_data: List of (sensor_enum, value) tuples for all installed sensors
                     Each tuple is (int, int) where both are 0-255
    
    Returns:
        bytes: Encoded payload
        
    Raises:
        ValueError: If parameters are invalid
    """
    # Validate version
    if not isinstance(version, int) or version < 0 or version > 255:
        raise ValueError(f"Invalid version: {version} (must be 0-255)")
    
    # Convert device_id to bytes if needed
    if isinstance(device_id, str):
        if len(device_id) != 6:
            raise ValueError(f"device_id must be 6 hex characters, got: {device_id}")
        device_id_bytes = bytes.fromhex(device_id)
    else:
        device_id_bytes = device_id
    
    if len(device_id_bytes) != 3:
        raise ValueError(f"device_id must be exactly 3 bytes, got {len(device_id_bytes)}")
    
    # Validate GPS coordinates
    if not isinstance(gps_lat, (int, float)) or gps_lat < -90 or gps_lat > 90:
        raise ValueError(f"Invalid GPS latitude: {gps_lat} (must be -90 to 90)")
    
    if not isinstance(gps_lon, (int, float)) or gps_lon < -180 or gps_lon > 180:
        raise ValueError(f"Invalid GPS longitude: {gps_lon} (must be -180 to 180)")
    
    # Validate battery
    if not isinstance(battery, int) or battery < 0 or battery > 100:
        raise ValueError(f"Invalid battery: {battery} (must be 0-100)")
    
    # Validate hops
    if not isinstance(hops, int) or hops < 0 or hops > 255:
        raise ValueError(f"Invalid hops: {hops} (must be 0-255)")
    
    # Validate sensor_data
    if not isinstance(sensor_data, (list, tuple)):
        raise ValueError(f"sensor_data must be a list or tuple, got {type(sensor_data)}")
    
    for i, pair in enumerate(sensor_data):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"sensor_data[{i}] must be a 2-element tuple (sensor_enum, value)")
        sensor_enum, value = pair
        if not isinstance(sensor_enum, int) or sensor_enum < 0 or sensor_enum > 255:
            raise ValueError(f"sensor_data[{i}] sensor_enum invalid: {sensor_enum}")
        if not isinstance(value, int) or value < 0 or value > 255:
            raise ValueError(f"sensor_data[{i}] value invalid: {value}")
    
    # Build payload
    payload = bytearray()
    
    # Fixed header (14 bytes)
    payload.append(version)                          # Byte 0: version
    payload.extend(device_id_bytes)                  # Bytes 1-3: device_id
    payload.extend(struct.pack('>f', gps_lat))       # Bytes 4-7: gps_lat (big-endian float)
    payload.extend(struct.pack('>f', gps_lon))       # Bytes 8-11: gps_lon (big-endian float)
    payload.append(battery)                          # Byte 12: battery
    payload.append(hops)                             # Byte 13: hops
    
    # Repeated sensor pairs (2 bytes each)
    for sensor_enum, value in sensor_data:
        payload.append(sensor_enum)                  # SensorEnum
        payload.append(value)                        # Value
    
    return bytes(payload)


def decode_payload(payload_bytes):
    """
    Decode a LoRa payload according to PROTOCOL.md.
    
    Args:
        payload_bytes: bytes object containing the payload
        
    Returns:
        dict with keys:
            - version: int
            - device_id: str (6-character hex)
            - gps_latitude: float
            - gps_longitude: float
            - battery: int
            - hops: int
            - sensors: list of dicts with 'sensor_enum' and 'value' keys
            
    Raises:
        ValueError: If payload is invalid
    """
    if len(payload_bytes) < FIXED_HEADER_SIZE:
        raise ValueError(f"Payload too short: {len(payload_bytes)} bytes (minimum {FIXED_HEADER_SIZE})")
    
    # Check that sensor data length is even (pairs of bytes)
    sensor_data_len = len(payload_bytes) - FIXED_HEADER_SIZE
    if sensor_data_len % SENSOR_PAIR_SIZE != 0:
        raise ValueError(f"Invalid sensor data length: {sensor_data_len} (must be multiple of {SENSOR_PAIR_SIZE})")
    
    # Decode fixed header
    version = payload_bytes[0]
    device_id = payload_bytes[1:4].hex().upper()
    gps_lat = struct.unpack_from('>f', payload_bytes, 4)[0]
    gps_lon = struct.unpack_from('>f', payload_bytes, 8)[0]
    battery = payload_bytes[12]
    hops = payload_bytes[13]
    
    # Decode sensor pairs
    sensors = []
    offset = FIXED_HEADER_SIZE
    while offset < len(payload_bytes):
        sensor_enum = payload_bytes[offset]
        value = payload_bytes[offset + 1]
        sensors.append({
            'sensor_enum': sensor_enum,
            'value': value,
            'sensor_type': get_sensor_type_from_enum(sensor_enum)
        })
        offset += SENSOR_PAIR_SIZE
    
    return {
        'version': version,
        'device_id': device_id,
        'gps_latitude': gps_lat,
        'gps_longitude': gps_lon,
        'battery': battery,
        'hops': hops,
        'sensors': sensors
    }


def build_sensor_data_from_config(installed_sensors, triggering_sensor_type=None, trigger_value=0, retained_triggers=None):
    """
    Build sensor_data list for encode_payload from installed sensor configuration.
    
    This function creates the repeated sensor pairs for ALL installed non-gps_battery
    sensors, setting appropriate values based on whether each sensor is currently
    triggered, including retained trigger state from earlier transmissions.
    
    Args:
        installed_sensors: List of sensor config dicts with 'type' key
        triggering_sensor_type: Type of sensor that triggered in this transmission, or None
        trigger_value: Value to use for the current triggering sensor (2-255)
        retained_triggers: Optional dict mapping sensor type -> retained trigger value
        
    Returns:
        List of (sensor_enum, value) tuples for all installed sensors
        
    Raises:
        ValueError: If an installed sensor type cannot be mapped to protocol enum
    """
    sensor_data = []
    retained_triggers = retained_triggers or {}
    
    for sensor_config in installed_sensors:
        sensor_type = sensor_config.get('type', '')
        
        # Skip gps_battery - it's in the fixed header, not the repeated section
        if sensor_type == 'gps_battery':
            continue
        
        sensor_enum = get_sensor_enum_from_type(sensor_type)
        
        # Explicitly handle unmapped sensor types - do not silently skip
        if sensor_enum == SensorEnum.NOT_INSTALLED:
            error_msg = f"Installed sensor type '{sensor_type}' cannot be mapped to protocol enum. Valid types: {list(SENSOR_TYPE_TO_ENUM.keys())}"
            print(f"[PAYLOAD ERROR] {error_msg}")
            raise ValueError(error_msg)
        
        retained_value = retained_triggers.get(sensor_type)
        
        # Current trigger takes precedence over retained trigger state
        if triggering_sensor_type and sensor_type == triggering_sensor_type:
            # Validate trigger_value is in valid triggered range (2-255)
            if not isinstance(trigger_value, int) or trigger_value < VALUE_MIN_TRIGGERED or trigger_value > VALUE_MAX:
                error_msg = f"Invalid trigger_value {trigger_value} for sensor '{sensor_type}' - must be {VALUE_MIN_TRIGGERED}-{VALUE_MAX}"
                print(f"[PAYLOAD ERROR] {error_msg}")
                raise ValueError(error_msg)
            value = trigger_value
        elif retained_value is not None:
            # Validate retained value is in valid triggered range (2-255)
            retained_int = int(retained_value)
            if retained_int < VALUE_MIN_TRIGGERED or retained_int > VALUE_MAX:
                error_msg = f"Invalid retained_value {retained_int} for sensor '{sensor_type}' - must be {VALUE_MIN_TRIGGERED}-{VALUE_MAX}"
                print(f"[PAYLOAD ERROR] {error_msg}")
                raise ValueError(error_msg)
            value = retained_int
        else:
            value = VALUE_NOT_TRIGGERED
        
        sensor_data.append((sensor_enum, value))
    
    return sensor_data

# Made with Bob
