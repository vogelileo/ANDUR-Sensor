Data Package

Version (1 byte) - offset 0
Sensor ID -> MAC (3 bytes) - offset 1-3
GPS Latitude (4 bytes) - offset 4-7
GPS Longitude (4 bytes) - offset 8-11
Battery (1 byte) - offset 12
Hops (1 byte) - offset 13

SensorAlgoEnum (1 byte) - offset 14
  Bit-packing format:
  - Bits 4-7: Sensor Type ID (0-15)
  - Bits 0-3: Algorithm Type ID (0-15)
  - When used as single value: 0-15 are reserved for controls

Value (1 byte) - offset 15