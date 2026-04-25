Data Package

Version (1 byte) - offset 0
Device ID -> MAC (3 bytes) - offset 1-3
GPS Latitude (4 bytes) - offset 4-7
GPS Longitude (4 bytes) - offset 8-11
Battery (1 byte) - offset 12
Hops (1 byte) - offset 13

(Repeat for every sensor installed (aka always send all sensors installed))
SensorEnum (1 byte) - offset 14
- 0 means not-installed or not-used
- 1 - 255 means installed and value is the sensor ID
Enums (the next byte value below is just 2 for triggered for now, or 1 for not triggered):
1 - Microphone 
2 - Bluetooth 
3 - Audio
4 - Magnetometer
5 - RFBeam
6 - Camera
7 - Seismic

Value (1 byte) - offset 15
- 0 means not-installed or not-used
- 1 means not triggered
- 2-255 means installed and value is specifc to the SensorEnum
