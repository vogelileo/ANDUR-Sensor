"""
LoRa communication interface for the MicroPython Sensor System.

This module provides hardware support for the SX1262 LoRa module on
Raspberry Pi Pico. It handles SPI communication, radio configuration,
packet transmission, and reception with full 16-byte DataPackage support.
"""

import json
import struct
import time
from machine import SPI, Pin

# SX1262 Register Commands
SX1262_CMD_SET_SLEEP = 0x84
SX1262_CMD_SET_STANDBY = 0x80
SX1262_CMD_SET_FS = 0xC1
SX1262_CMD_SET_TX = 0x83
SX1262_CMD_SET_RX = 0x82
SX1262_CMD_STOP_TIMER_ON_PREAMBLE = 0x9F
SX1262_CMD_SET_RF_FREQUENCY = 0x86
SX1262_CMD_SET_PA_CONFIG = 0x95
SX1262_CMD_SET_TX_PARAMS = 0x8E
SX1262_CMD_SET_BUFFER_BASE_ADDRESS = 0x8F
SX1262_CMD_WRITE_BUFFER = 0x0E
SX1262_CMD_READ_BUFFER = 0x1E
SX1262_CMD_SET_MODULATION_PARAMS = 0x8B
SX1262_CMD_SET_PACKET_PARAMS = 0x8C
SX1262_CMD_GET_STATUS = 0xC0
SX1262_CMD_GET_IRQ_STATUS = 0x12
SX1262_CMD_CLEAR_IRQ_STATUS = 0x02
SX1262_CMD_SET_DIO_IRQ_PARAMS = 0x08
SX1262_CMD_SET_PACKET_TYPE = 0x8A
SX1262_CMD_GET_PACKET_STATUS = 0x14
SX1262_CMD_GET_RX_BUFFER_STATUS = 0x13
SX1262_CMD_SET_REGULATOR_MODE = 0x96
SX1262_CMD_CALIBRATE = 0x89
SX1262_CMD_CALIBRATE_IMAGE = 0x98
SX1262_CMD_SET_DIO3_AS_TCXO_CTRL = 0x97
SX1262_CMD_SET_DIO2_AS_RF_SWITCH = 0x9D
SX1262_CMD_WRITE_REGISTER = 0x0D
SX1262_CMD_READ_REGISTER = 0x1D

# SX1262 Register Addresses
SX1262_REG_LORA_SYNC_WORD_MSB = 0x0740
SX1262_REG_LORA_SYNC_WORD_LSB = 0x0741

# SX1262 Constants
SX1262_PACKET_TYPE_LORA = 0x01
SX1262_STANDBY_RC = 0x00
SX1262_STANDBY_XOSC = 0x01
SX1262_REGULATOR_DC_DC = 0x01

# LoRa Modulation Parameters
LORA_SF_7 = 0x07
LORA_SF_8 = 0x08
LORA_SF_9 = 0x09
LORA_SF_10 = 0x0A
LORA_SF_11 = 0x0B
LORA_SF_12 = 0x0C

LORA_BW_125 = 0x04
LORA_BW_250 = 0x05
LORA_BW_500 = 0x06

LORA_CR_4_5 = 0x01
LORA_CR_4_6 = 0x02
LORA_CR_4_7 = 0x03
LORA_CR_4_8 = 0x04

# IRQ Masks
IRQ_TX_DONE = 0x0001
IRQ_RX_DONE = 0x0002
IRQ_TIMEOUT = 0x0200
IRQ_CRC_ERROR = 0x0040
IRQ_ALL = 0xFFFF

# Protocol constants
PROTOCOL_VERSION = 1
TOTAL_PACKAGE_SIZE = 16
CONTROL_MESSAGE_MIN = 0
CONTROL_MESSAGE_MAX = 15

# Schema-based type mappings
SENSOR_TYPE_MAP = {
    "magnetic": 0,
    "temperature": 1,
    "pressure": 2,
    "humidity": 3,
    "microwave": 4,
    "alibi": 5
}

ALGO_TYPE_MAP = {
    "threshold": 0,
    "moving_average": 1,
    "peak_detector": 2,
    "anomaly": 3,
    "adaptive_threshold": 4,
    "energy_hysteresis": 5,
    "microwave_detection": 6,
    "random": 7
}


class LoRaInterface:
    def __init__(self, spi_bus=None, cs_pin=None, reset_pin=None, config=None, monitor=None):
        """
        Initialize the LoRa interface with SX1262 hardware support.
        
        Args:
            spi_bus: Configured SPI bus (ignored, uses hardcoded working config)
            cs_pin: CS pin (ignored, uses hardcoded working config)
            reset_pin: Reset pin (ignored, uses hardcoded working config)
            config: Dictionary with LoRa configuration values
            monitor: SystemMonitor instance for tracking messages
        """
        # Use exact working hardware setup
        self.spi = SPI(
            1,
            baudrate=2000000,
            polarity=0,
            phase=0,
            sck=Pin(10),
            mosi=Pin(11),
            miso=Pin(12),
        )
        self.cs = Pin(3, Pin.OUT, value=1)
        self.rst = Pin(15, Pin.OUT, value=1)
        self.busy = Pin(2, Pin.IN)
        self.dio1 = Pin(20, Pin.IN)
        
        self.monitor = monitor
        self.initialized = False
        self.config = config or {}
        
        # Load protocol schema
        try:
            with open('lora_protocol_schema.json', 'r') as f:
                self.schema = json.load(f)
                print("[LoRa] Protocol schema loaded (version {})".format(
                    self.schema.get('version', 'unknown')))
        except Exception as e:
            print("[LoRa] Warning: Could not load protocol schema: {}".format(e))
            self.schema = None
        
        # Extract configuration parameters with defaults
        self.frequency = self.config.get('frequency', 868000000)
        self.tx_power = self.config.get('tx_power', 14)
        self.spreading_factor = self.config.get('spreading_factor', 7)
        self.bandwidth = self.config.get('bandwidth', 125000)
        self.coding_rate = self.config.get('coding_rate', 5)
        self.preamble_length = self.config.get('preamble_length', 8)
        # Handle sync_word in both hex string ("0x1212") and integer (4626) formats
        sync_word_raw = self.config.get('sync_word', 0x1424)
        if isinstance(sync_word_raw, str):
            self.sync_word = int(sync_word_raw, 16)
        else:
            self.sync_word = sync_word_raw
        
        # Validate parameters
        if self.spreading_factor < 7 or self.spreading_factor > 12:
            print("[LoRa] Warning: Invalid SF {}, using SF7".format(self.spreading_factor))
            self.spreading_factor = 7
        
        if self.bandwidth not in [125000, 250000, 500000]:
            print("[LoRa] Warning: Invalid BW {}, using 125kHz".format(self.bandwidth))
            self.bandwidth = 125000
        
        if self.coding_rate < 5 or self.coding_rate > 8:
            print("[LoRa] Warning: Invalid CR {}, using 4/5".format(self.coding_rate))
            self.coding_rate = 5
        
        if self.tx_power < -9 or self.tx_power > 22:
            print("[LoRa] Warning: Invalid TX power {}, using 14dBm".format(self.tx_power))
            self.tx_power = 14
        
        print("[LoRa] SX1262 Interface created")
        print("[LoRa] Frequency: {} Hz".format(self.frequency))
        print("[LoRa] TX Power: {} dBm".format(self.tx_power))
        print("[LoRa] SF: {}, BW: {} Hz, CR: 4/{}".format(
            self.spreading_factor, self.bandwidth, self.coding_rate))

    def wait_busy(self):
        """Wait for BUSY pin to go low with timeout."""
        t = time.ticks_ms()
        while self.busy():
            if time.ticks_diff(time.ticks_ms(), t) > 5000:
                raise Exception("BUSY timeout")

    def cmd(self, *args):
        """Send command to SX1262."""
        self.wait_busy()
        self.cs(0)
        self.spi.write(bytes(args))
        self.cs(1)

    def xfer(self, data):
        """Transfer data via SPI."""
        self.wait_busy()
        tx = bytes(data)
        rx = bytearray(len(tx))
        self.cs(0)
        self.spi.write_readinto(tx, rx)
        self.cs(1)
        return rx

    def _write_register(self, address, value):
        """Write to SX1262 register."""
        self.wait_busy()
        self.cs(0)
        self.spi.write(bytes([SX1262_CMD_WRITE_REGISTER, 
                             (address >> 8) & 0xFF, 
                             address & 0xFF, 
                             value]))
        self.cs(1)

    def _set_sync_word(self, sync_word):
        """Set LoRa sync word."""
        msb = (sync_word >> 8) & 0xFF
        lsb = sync_word & 0xFF
        self._write_register(SX1262_REG_LORA_SYNC_WORD_MSB, msb)
        self._write_register(SX1262_REG_LORA_SYNC_WORD_LSB, lsb)

    def _set_standby(self, mode):
        """Set standby mode."""
        self.cmd(SX1262_CMD_SET_STANDBY, mode)

    def _set_packet_type(self, packet_type):
        """Set packet type (LoRa)."""
        self.cmd(SX1262_CMD_SET_PACKET_TYPE, packet_type)

    def _set_rf_frequency(self, frequency):
        """Set RF frequency."""
        freq_raw = int((frequency * (2**25)) / 32000000)
        self.cmd(SX1262_CMD_SET_RF_FREQUENCY,
                (freq_raw >> 24) & 0xFF,
                (freq_raw >> 16) & 0xFF,
                (freq_raw >> 8) & 0xFF,
                freq_raw & 0xFF)

    def _set_pa_config(self):
        """Configure power amplifier."""
        self.cmd(SX1262_CMD_SET_PA_CONFIG, 0x04, 0x07, 0x00, 0x01)

    def _set_tx_params(self, power):
        """Set TX parameters."""
        self.cmd(SX1262_CMD_SET_TX_PARAMS, power, 0x04)

    def _set_buffer_base_address(self, tx_base, rx_base):
        """Set buffer base addresses."""
        self.cmd(SX1262_CMD_SET_BUFFER_BASE_ADDRESS, tx_base, rx_base)

    def _set_modulation_params(self):
        """Set modulation parameters."""
        sf_map = {7: LORA_SF_7, 8: LORA_SF_8, 9: LORA_SF_9,
                 10: LORA_SF_10, 11: LORA_SF_11, 12: LORA_SF_12}
        bw_map = {125000: LORA_BW_125, 250000: LORA_BW_250, 500000: LORA_BW_500}
        cr_map = {5: LORA_CR_4_5, 6: LORA_CR_4_6, 7: LORA_CR_4_7, 8: LORA_CR_4_8}
        
        sf = sf_map.get(self.spreading_factor, LORA_SF_7)
        bw = bw_map.get(self.bandwidth, LORA_BW_125)
        cr = cr_map.get(self.coding_rate, LORA_CR_4_5)
        
        self.cmd(SX1262_CMD_SET_MODULATION_PARAMS, sf, bw, cr, 0x00)

    def _set_packet_params(self, payload_length, implicit_header=False, crc_on=True):
        """Set packet parameters."""
        preamble_msb = (self.preamble_length >> 8) & 0xFF
        preamble_lsb = self.preamble_length & 0xFF
        header_type = 0x01 if implicit_header else 0x00
        crc = 0x01 if crc_on else 0x00
        
        self.cmd(SX1262_CMD_SET_PACKET_PARAMS,
                preamble_msb, preamble_lsb,
                header_type, payload_length,
                crc, 0x00)

    def _set_dio_irq_params(self, irq_mask, dio1_mask):
        """Configure DIO IRQ parameters."""
        self.cmd(SX1262_CMD_SET_DIO_IRQ_PARAMS,
                (irq_mask >> 8) & 0xFF, irq_mask & 0xFF,
                (dio1_mask >> 8) & 0xFF, dio1_mask & 0xFF,
                0x00, 0x00, 0x00, 0x00)

    def _clear_irq_status(self, irq_mask):
        """Clear IRQ status."""
        self.cmd(SX1262_CMD_CLEAR_IRQ_STATUS,
                (irq_mask >> 8) & 0xFF, irq_mask & 0xFF)

    def _write_buffer(self, offset, data):
        """Write data to TX buffer."""
        self.wait_busy()
        self.cs(0)
        self.spi.write(bytes([SX1262_CMD_WRITE_BUFFER, offset]))
        self.spi.write(data)
        self.cs(1)

    def _set_tx(self, timeout):
        """Set TX mode with timeout."""
        timeout_bytes = [
            (timeout >> 16) & 0xFF,
            (timeout >> 8) & 0xFF,
            timeout & 0xFF
        ]
        self.cmd(SX1262_CMD_SET_TX, *timeout_bytes)

    def _get_irq_status(self):
        """Get IRQ status."""
        irq = self.xfer([SX1262_CMD_GET_IRQ_STATUS, 0x00, 0x00, 0x00])
        return (irq[2] << 8) | irq[3]

    def initialize(self):
        """Initialize SX1262 hardware."""
        self.rst(0)
        time.sleep_ms(10)
        self.rst(1)
        time.sleep_ms(20)
        self.wait_busy()

        # Standby mode
        self.cmd(SX1262_CMD_SET_STANDBY, 0x00)
        
        # Configure TCXO (critical for Waveshare)
        self.cmd(SX1262_CMD_SET_DIO3_AS_TCXO_CTRL, 0x06, 0x00, 0x01, 0x40)
        
        # Calibrate
        self.cmd(SX1262_CMD_CALIBRATE, 0x7F)
        time.sleep_ms(10)
        self.wait_busy()

        # Standby again
        self.cmd(SX1262_CMD_SET_STANDBY, 0x00)
        
        # Set packet type to LoRa
        self.cmd(SX1262_CMD_SET_PACKET_TYPE, 0x01)
        
        # Set frequency
        freq_raw = int((self.frequency * (2**25)) / 32000000)
        self.cmd(SX1262_CMD_SET_RF_FREQUENCY,
                (freq_raw >> 24) & 0xFF,
                (freq_raw >> 16) & 0xFF,
                (freq_raw >> 8) & 0xFF,
                freq_raw & 0xFF)
        
        # Calibrate image
        self.cmd(SX1262_CMD_CALIBRATE_IMAGE, 0xD7, 0xDB)
        time.sleep_ms(5)
        self.wait_busy()

        # Configure DIO2 as RF switch
        self.cmd(SX1262_CMD_SET_DIO2_AS_RF_SWITCH, 0x01)
        
        # Set modulation parameters
        self._set_modulation_params()
        
        # Set packet parameters
        self._set_packet_params(255)
        
        # Set sync word
        self._set_sync_word(self.sync_word)
        
        # Configure PA
        self._set_pa_config()
        
        # Set TX params
        self._set_tx_params(self.tx_power)
        
        # Set buffer addresses
        self._set_buffer_base_address(0x00, 0x00)
        
        # Configure IRQ - RxDone + CrcErr on DIO1 (exactly like working version)
        self.cmd(SX1262_CMD_SET_DIO_IRQ_PARAMS,
                0x00, 0x42, 0x00, 0x42, 0x00, 0x00, 0x00, 0x00)
        
        # Clear IRQ
        self.cmd(SX1262_CMD_CLEAR_IRQ_STATUS, 0xFF, 0xFF)
        
        # Start continuous receive mode (THIS WAS MISSING!)
        self.cmd(SX1262_CMD_SET_RX, 0xFF, 0xFF, 0xFF)

        self.initialized = True
        print("[LoRa] ✓ SX1262 initialization complete!")
        print("[LoRa] ✓ Radio in RX continuous mode")
        return True

    def _validate_data_package(self, data):
        """
        Validate a complete DataPackage against schema.
        
        Args:
            data: dict with DataPackage fields
            
        Returns:
            tuple: (is_valid, error_message)
        """
        if not self.schema:
            return True, None
        
        # Validate version
        version = data.get('version', PROTOCOL_VERSION)
        if not isinstance(version, int) or version < 0 or version > 255:
            return False, "Invalid version: {}".format(version)
        
        # Validate battery
        battery = data.get('battery')
        if battery is not None:
            if not isinstance(battery, int) or battery < 0 or battery > 100:
                return False, "Invalid battery level: {} (must be 0-100)".format(battery)
        
        # Validate GPS coordinates
        gps_lat = data.get('gps_latitude')
        if gps_lat is not None:
            if not isinstance(gps_lat, (int, float)) or gps_lat < -90 or gps_lat > 90:
                return False, "Invalid GPS latitude: {}".format(gps_lat)
        
        gps_lon = data.get('gps_longitude')
        if gps_lon is not None:
            if not isinstance(gps_lon, (int, float)) or gps_lon < -180 or gps_lon > 180:
                return False, "Invalid GPS longitude: {}".format(gps_lon)
        
        # Validate hops
        hops = data.get('hops')
        if hops is not None:
            if not isinstance(hops, int) or hops < 0 or hops > 255:
                return False, "Invalid hops: {}".format(hops)
        
        # Validate sensor_algo_enum
        sensor_algo_enum = data.get('sensor_algo_enum')
        if sensor_algo_enum is not None:
            if not isinstance(sensor_algo_enum, int) or sensor_algo_enum < 0 or sensor_algo_enum > 255:
                return False, "Invalid sensor_algo_enum: {}".format(sensor_algo_enum)
        
        # Validate value
        value = data.get('value')
        if value is not None:
            if not isinstance(value, int) or value < 0 or value > 255:
                return False, "Invalid value: {}".format(value)
        
        return True, None

    def _format_data_package(self, sensor_id, gps_lat, gps_lon, battery, hops,
                            sensor_algo_enum, value, version=None):
        """
        Format a complete 16-byte DataPackage according to schema.
        
        Args:
            sensor_id: 3-byte sensor MAC address (as hex string or bytes)
            gps_lat: GPS latitude (float, -90 to 90)
            gps_lon: GPS longitude (float, -180 to 180)
            battery: Battery level (int, 0-100)
            hops: Network hop count (int, 0-255)
            sensor_algo_enum: Sensor/algorithm enumeration (int, 0-255)
            value: Sensor reading value (int, 0-255)
            version: Protocol version (int, default: PROTOCOL_VERSION)
            
        Returns:
            bytes object with exactly 16 bytes
        """
        if version is None:
            version = PROTOCOL_VERSION
        
        # Validate inputs
        data = {
            'version': version,
            'sensor_id': sensor_id,
            'gps_latitude': gps_lat,
            'gps_longitude': gps_lon,
            'battery': battery,
            'hops': hops,
            'sensor_algo_enum': sensor_algo_enum,
            'value': value
        }
        
        is_valid, error_msg = self._validate_data_package(data)
        if not is_valid:
            raise ValueError("DataPackage validation failed: {}".format(error_msg))
        
        # Convert sensor_id to bytes if it's a hex string
        if isinstance(sensor_id, str):
            if len(sensor_id) != 6:
                raise ValueError("sensor_id must be 6 hex characters")
            sensor_id_bytes = bytes.fromhex(sensor_id)
        else:
            sensor_id_bytes = sensor_id
        
        if len(sensor_id_bytes) != 3:
            raise ValueError("sensor_id must be exactly 3 bytes")
        
        # Pack according to schema fieldMapping
        package = bytearray(TOTAL_PACKAGE_SIZE)
        package[0] = version
        package[1:4] = sensor_id_bytes
        
        # Pack floats as big-endian IEEE 754
        struct.pack_into('>f', package, 4, gps_lat)
        struct.pack_into('>f', package, 8, gps_lon)
        
        package[12] = battery
        package[13] = hops
        package[14] = sensor_algo_enum
        package[15] = value
        
        return bytes(package)

    def _unpack_data_package(self, package_bytes):
        """
        Unpack a 16-byte DataPackage into a dictionary.
        
        Args:
            package_bytes: bytes object with exactly 16 bytes
            
        Returns:
            dict with unpacked DataPackage fields
        """
        if len(package_bytes) != TOTAL_PACKAGE_SIZE:
            raise ValueError("Invalid package size: {} (expected {})".format(
                len(package_bytes), TOTAL_PACKAGE_SIZE))
        
        # Unpack according to schema fieldMapping
        version = package_bytes[0]
        sensor_id = package_bytes[1:4].hex().upper()
        
        # Unpack floats as big-endian IEEE 754
        gps_lat = struct.unpack_from('>f', package_bytes, 4)[0]
        gps_lon = struct.unpack_from('>f', package_bytes, 8)[0]
        
        battery = package_bytes[12]
        hops = package_bytes[13]
        sensor_algo_enum = package_bytes[14]
        value = package_bytes[15]
        
        data = {
            'version': version,
            'sensor_id': sensor_id,
            'gps_latitude': gps_lat,
            'gps_longitude': gps_lon,
            'battery': battery,
            'hops': hops,
            'sensor_algo_enum': sensor_algo_enum,
            'value': value
        }
        
        # Validate unpacked data
        is_valid, error_msg = self._validate_data_package(data)
        if not is_valid:
            print("[LoRa] Warning: Unpacked package validation failed: {}".format(error_msg))
        
        return data

    def send(self, data_package):
        """
        Send a 16-byte DataPackage via LoRa.
        
        Args:
            data_package: Either a dict with DataPackage fields or bytes (16 bytes)
            
        Returns:
            bool: True if transmission successful, False otherwise
        """
        if not self.initialized:
            error_msg = "Radio not initialized. Call initialize() first."
            print("[LoRa] ✗ Error: {}".format(error_msg))
            raise RuntimeError(error_msg)
        
        # Convert dict to bytes if needed
        if isinstance(data_package, dict):
            try:
                binary_payload = self._format_data_package(
                    data_package.get('sensor_id', '000000'),
                    data_package.get('gps_latitude', 0.0),
                    data_package.get('gps_longitude', 0.0),
                    data_package.get('battery', 0),
                    data_package.get('hops', 0),
                    data_package.get('sensor_algo_enum', 0),
                    data_package.get('value', 0),
                    data_package.get('version', PROTOCOL_VERSION)
                )
            except Exception as e:
                print("[LoRa] ✗ Error formatting data package: {}".format(e))
                raise ValueError("Failed to format data package: {}".format(e))
        else:
            binary_payload = data_package
        
        # Validate payload length
        if len(binary_payload) != TOTAL_PACKAGE_SIZE:
            raise ValueError("Invalid payload size: {} (expected {})".format(
                len(binary_payload), TOTAL_PACKAGE_SIZE))
        
        print("[LoRa] Transmitting {} bytes...".format(len(binary_payload)))
        
        try:
            # Set to standby mode
            self._set_standby(SX1262_STANDBY_RC)
            time.sleep_ms(10)
            
            # Clear any pending IRQs
            self._clear_irq_status(IRQ_ALL)
            
            # Configure DIO IRQ params for transmission
            self._set_dio_irq_params(IRQ_TX_DONE | IRQ_TIMEOUT, IRQ_TX_DONE | IRQ_TIMEOUT)
            
            # Set packet parameters for this transmission
            self._set_packet_params(len(binary_payload))
            
            # Write payload to buffer
            self._write_buffer(0x00, binary_payload)
            
            # Start transmission with timeout (5 seconds)
            tx_timeout = 320000  # ~5 seconds
            self._set_tx(tx_timeout)
            
            time.sleep_ms(10)
            
            # Wait for TX completion
            tx_done = False
            tx_timeout_flag = False
            timeout_count = 0
            max_timeout = 100  # 10 seconds max wait
            
            while not tx_done and not tx_timeout_flag and timeout_count < max_timeout:
                time.sleep_ms(100)
                timeout_count += 1
                
                # Check DIO1 pin
                if self.dio1():
                    tx_done = True
                    break
                
                # Read IRQ status via SPI
                try:
                    irq_status = self._get_irq_status()
                    
                    # Check for TX_DONE flag
                    if irq_status & IRQ_TX_DONE:
                        tx_done = True
                        print("[LoRa] ✓ TX_DONE flag detected (IRQ: 0x{:04X})".format(irq_status))
                        break
                    
                    # Check for TIMEOUT flag
                    if irq_status & IRQ_TIMEOUT:
                        tx_timeout_flag = True
                        print("[LoRa] ✗ TX_TIMEOUT flag detected (IRQ: 0x{:04X})".format(irq_status))
                        break
                        
                except Exception as irq_error:
                    pass
            
            # Clear IRQ status
            self._clear_irq_status(IRQ_ALL)
            
            # Return to standby
            self._set_standby(SX1262_STANDBY_RC)
            
            # Determine success
            if tx_done:
                print("[LoRa] ✓ Transmission successful!")
                
                # Track message in monitor if available
                if self.monitor:
                    try:
                        unpacked = self._unpack_data_package(binary_payload)
                        self.monitor.add_lora_message(
                            unpacked.get('sensor_algo_enum', 0),
                            unpacked.get('sensor_id', '000000'),
                            unpacked.get('value', 0),
                            int(time.time())
                        )
                    except:
                        pass
                
                return True
            elif tx_timeout_flag:
                print("[LoRa] ✗ Transmission timed out")
                return False
            else:
                print("[LoRa] ✗ Warning: TX completion not confirmed")
                return False
                
        except Exception as e:
            print("[LoRa] ✗ Error during transmission: {}".format(e))
            
            # Try to recover
            try:
                self._set_standby(SX1262_STANDBY_RC)
            except:
                pass
            raise RuntimeError("Transmission failed: {}".format(e))

    def receive(self, timeout_ms=None):
        """
        Receive a LoRa packet (16-byte DataPackage format).
        
        Args:
            timeout_ms: Timeout in milliseconds (not used, non-blocking)
            
        Returns:
            dict with received data or None if no packet available
        """
        if not self.dio1():
            return None

        irq = self.xfer([SX1262_CMD_GET_IRQ_STATUS, 0x00, 0x00, 0x00])
        flags = (irq[2] << 8) | irq[3]
        self.cmd(SX1262_CMD_CLEAR_IRQ_STATUS, (flags >> 8) & 0xFF, flags & 0xFF)

        if not (flags & IRQ_RX_DONE):
            return None

        stat = self.xfer([SX1262_CMD_GET_RX_BUFFER_STATUS, 0x00, 0x00, 0x00])
        plen, ptr = stat[2], stat[3]
        data = self.xfer([SX1262_CMD_READ_BUFFER, ptr, 0x00] + [0x00] * plen)
        payload = bytes(data[3:])

        pkt = self.xfer([SX1262_CMD_GET_PACKET_STATUS, 0x00, 0x00, 0x00, 0x00])
        rssi = -pkt[2] / 2
        snr = pkt[3] / 4 if pkt[3] < 128 else (pkt[3] - 256) / 4

        result = {
            "payload": payload,
            "rssi": rssi,
            "snr": snr,
            "crc_error": bool(flags & IRQ_CRC_ERROR),
            "length": plen,
            "hex": payload.hex(),
        }
        
        # Try to unpack as DataPackage if it's 16 bytes
        if plen == TOTAL_PACKAGE_SIZE:
            try:
                unpacked = self._unpack_data_package(payload)
                result["data_package"] = unpacked
                
                # Track in monitor if available
                if self.monitor:
                    try:
                        self.monitor.add_lora_message(
                            unpacked.get('sensor_algo_enum', 0),
                            unpacked.get('sensor_id', '000000'),
                            unpacked.get('value', 0),
                            int(time.time())
                        )
                    except:
                        pass
            except Exception as e:
                print("[LoRa] Warning: Could not unpack DataPackage: {}".format(e))
        
        return result

    @staticmethod
    def get_sensor_type_id(sensor_name):
        """
        Get sensor type ID from name.
        
        Args:
            sensor_name: Sensor type name (e.g., 'magnetic', 'microwave')
            
        Returns:
            int: Sensor type ID
        """
        if sensor_name not in SENSOR_TYPE_MAP:
            raise ValueError("Unknown sensor type: {}".format(sensor_name))
        return SENSOR_TYPE_MAP[sensor_name]

    @staticmethod
    def get_algo_type_id(algo_name):
        """
        Get algorithm type ID from name.
        
        Args:
            algo_name: Algorithm type name (e.g., 'threshold', 'adaptive_threshold')
            
        Returns:
            int: Algorithm type ID
        """
        if algo_name not in ALGO_TYPE_MAP:
            raise ValueError("Unknown algorithm type: {}".format(algo_name))
        return ALGO_TYPE_MAP[algo_name]

    @staticmethod
    def get_sensor_name_from_id(sensor_id):
        """
        Get sensor name from ID.
        
        Args:
            sensor_id: Sensor type ID (int)
            
        Returns:
            str: Sensor type name or 'unknown'
        """
        for name, sid in SENSOR_TYPE_MAP.items():
            if sid == sensor_id:
                return name
        return 'unknown'

    @staticmethod
    def get_algo_name_from_id(algo_id):
        """
        Get algorithm name from ID.
        
        Args:
            algo_id: Algorithm type ID (int)
            
        Returns:
            str: Algorithm type name or 'unknown'
        """
        for name, aid in ALGO_TYPE_MAP.items():
            if aid == algo_id:
                return name
        return 'unknown'

    @staticmethod
    def is_control_message(sensor_algo_enum):
        """
        Check if sensor_algo_enum value is in the control message range.
        
        Args:
            sensor_algo_enum: The sensor_algo_enum value to check
            
        Returns:
            bool: True if value is in control range (0-15)
        """

    @staticmethod
    def encode_sensor_algo_enum(sensor_name, algo_name):
        """
        Encode sensor and algorithm names into sensor_algo_enum byte.
        
        The sensor_algo_enum uses bit-packing:
        - Bits 4-7 (upper nibble): Sensor Type ID (0-15)
        - Bits 0-3 (lower nibble): Algorithm Type ID (0-15)
        
        Args:
            sensor_name: Name of the sensor type (e.g., 'microwave', 'alibi')
            algo_name: Name of the algorithm (e.g., 'adaptive_threshold', 'random')
        
        Returns:
            int: Combined sensor_algo_enum byte (0-255)
        
        Example:
            >>> LoRaInterface.encode_sensor_algo_enum('microwave', 'adaptive_threshold')
            68  # (4 << 4) | 4 = 0x44
        """
        sensor_id = LoRaInterface.get_sensor_type_id(sensor_name)
        algo_id = LoRaInterface.get_algo_type_id(algo_name)
        return (sensor_id << 4) | algo_id

    @staticmethod
    def decode_sensor_algo_enum(sensor_algo_enum):
        """
        Decode sensor_algo_enum byte into sensor and algorithm IDs.
        
        The sensor_algo_enum uses bit-packing:
        - Bits 4-7 (upper nibble): Sensor Type ID (0-15)
        - Bits 0-3 (lower nibble): Algorithm Type ID (0-15)
        
        Args:
            sensor_algo_enum: Combined sensor/algorithm enumeration byte (0-255)
        
        Returns:
            tuple: (sensor_id, algo_id) where both are integers 0-15
        
        Example:
            >>> LoRaInterface.decode_sensor_algo_enum(68)
            (4, 4)  # sensor_id=4 (microwave), algo_id=4 (adaptive_threshold)
        """
        sensor_id = (sensor_algo_enum >> 4) & 0x0F
        algo_id = sensor_algo_enum & 0x0F
        return sensor_id, algo_id
        return CONTROL_MESSAGE_MIN <= sensor_algo_enum <= CONTROL_MESSAGE_MAX


# Made with Bob
