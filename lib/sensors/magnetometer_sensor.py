"""
RM3100Sensor - I2C-based 3-axis magnetometer

This sensor integrates the PNI RM3100 magnetometer using MicroPython's I2C API.
It operates in single-shot mode:
1. Configure cycle counts / sensitivity
2. Trigger a single measurement
3. Wait for conversion to complete
4. Read X/Y/Z magnetic field data
5. Convert to microTeslas and compute field magnitude

I2C Address Configuration:
The RM3100 I2C address depends on the SA0 pin state:
  - SA0 = LOW (or floating): Address 0x20
  - SA0 = HIGH: Address 0x23

SPI Mode Pin Configuration:
The RM3100 can operate in either I2C or SPI mode. The mode is selected by
the SPI pin state:
  - SPI pin = LOW: SPI mode
  - SPI pin = HIGH: I2C mode
If GP9 is connected to the SPI pin, configure it as an output and set it HIGH
to enable I2C mode without physical rewiring.
"""

import asyncio
import math
from machine import Pin
from core.base_sensor import BaseSensor


class RM3100Sensor(BaseSensor):
    """
    RM3100 3-axis magnetometer sensor.

    Returns magnetic field data in microTeslas (uT) for X, Y, Z axes and the
    vector magnitude in the `value` field for algorithm compatibility.
    
    Note: Default I2C address is 0x20 because the current hardware setup has
    SA0 pulled LOW. If your hardware has SA0 HIGH, use address 0x23 instead.
    """

    # I2C address (current setup: SA0 pin LOW)
    DEFAULT_I2C_ADDR = 0x20

    # Register map
    REG_POLL = 0x00
    REG_CMM = 0x01
    REG_CCX_MSB = 0x04
    REG_CCX_LSB = 0x05
    REG_CCY_MSB = 0x06
    REG_CCY_LSB = 0x07
    REG_CCZ_MSB = 0x08
    REG_CCZ_LSB = 0x09
    REG_MX = 0x24
    REG_MY = 0x27
    REG_MZ = 0x2A
    REG_STATUS = 0x34

    # Single-shot trigger bits for X/Y/Z axes
    POLL_XYZ = 0x70

    # Status register data-ready bit
    STATUS_DRDY = 0x80

    # Default cycle count and approximate sensitivity for conversion to uT
    DEFAULT_CYCLE_COUNT = 200
    DEFAULT_SENSITIVITY = 75.0

    # Measurement timing
    MEASUREMENT_DELAY_S = 0.05
    STATUS_RETRY_COUNT = 3
    STATUS_RETRY_DELAY_S = 0.005

    def __init__(self, sensor_id, data_store, update_interval, buffer_size,
                 i2c_bus, i2c_addr=DEFAULT_I2C_ADDR, cycle_count=DEFAULT_CYCLE_COUNT,
                 sensitivity_factor=DEFAULT_SENSITIVITY, spi_mode_pin=None, monitor=None):
        """
        Initialize the RM3100 sensor.

        Args:
            sensor_id: Unique identifier for this sensor
            data_store: DataStore instance for storing readings
            update_interval: Time in seconds between readings
            buffer_size: Size of ring buffer for this sensor
            i2c_bus: Initialized machine.I2C instance (configured from config.json)
            i2c_addr: I2C address of the RM3100 (current setup: 0x20 with SA0=LOW, 0x23 if SA0=HIGH)
            cycle_count: Cycle count written to all axes
            sensitivity_factor: Raw counts to microTesla conversion divisor
            spi_mode_pin: GPIO pin number connected to RM3100 SPI pin (set HIGH for I2C mode)
            monitor: Optional system monitor
        
        Note:
            The I2C bus pins (SDA/SCL) are configured in config.json under the "i2c" section.
            Current hardware setup uses GP4 (SDA) and GP5 (SCL) for I2C0.
            
            If spi_mode_pin is specified, that GPIO will be configured as an output and
            set HIGH during initialization to enable I2C mode on the RM3100. This is useful
            when the SPI pin is connected to a GPIO instead of being hardwired HIGH.
        """
        super().__init__(sensor_id, data_store, update_interval, buffer_size, monitor)

        self.i2c = i2c_bus
        self.i2c_addr = i2c_addr
        self.cycle_count = cycle_count
        self.sensitivity_factor = sensitivity_factor
        self.spi_mode_pin = spi_mode_pin

        print(f"[{self.sensor_id}] RM3100Sensor configured:")
        print(f"  I2C address: 0x{i2c_addr:02X}")
        print(f"  Cycle count: {cycle_count}")
        print(f"  Sensitivity factor: {sensitivity_factor} counts/uT")
        print(f"  Mode: single-shot")
        if spi_mode_pin is not None:
            print(f"  SPI mode pin: GP{spi_mode_pin} (will be set HIGH for I2C mode)")

    async def initialize(self):
        """
        Initialize the RM3100 by configuring GPIO for I2C mode (if needed),
        setting cycle counts, and disabling continuous measurement mode.
        """
        try:
            # Configure SPI mode pin if specified (set HIGH to enable I2C mode)
            if self.spi_mode_pin is not None:
                mode_pin = Pin(self.spi_mode_pin, Pin.OUT)
                mode_pin.value(1)  # HIGH = I2C mode, LOW = SPI mode
                print(f"[{self.sensor_id}] Set GP{self.spi_mode_pin} HIGH to enable I2C mode")
                await asyncio.sleep(0.01)  # Allow mode to stabilize
            
            async with self.i2c_lock:
                # Configure identical cycle count for X/Y/Z axes
                cc_msb = (self.cycle_count >> 8) & 0xFF
                cc_lsb = self.cycle_count & 0xFF
                cycle_payload = bytes([
                    cc_msb, cc_lsb,
                    cc_msb, cc_lsb,
                    cc_msb, cc_lsb
                ])
                self.i2c.writeto_mem(self.i2c_addr, self.REG_CCX_MSB, cycle_payload)

                # Ensure continuous mode is disabled for single-shot operation
                self.i2c.writeto_mem(self.i2c_addr, self.REG_CMM, b'\x00')

            await asyncio.sleep(0.01)
            print(f"[{self.sensor_id}] RM3100 initialized successfully")

        except Exception as e:
            print(f"[{self.sensor_id}] Error initializing RM3100: {e}")
            raise

    async def read(self):
        """
        Trigger a single-shot measurement and read X/Y/Z field data.

        Returns:
            dict: {
                'value': magnitude_uT,
                'x': x_uT,
                'y': y_uT,
                'z': z_uT,
                'raw_samples': {'x': raw_x, 'y': raw_y, 'z': raw_z}
            }
        """
        print(f"[{self.sensor_id}] Starting RM3100 reading cycle...")
        
        safe_result = {
            'value': 0.0,
            'x': 0.0,
            'y': 0.0,
            'z': 0.0,
            'raw_samples': {'x': 0, 'y': 0, 'z': 0}
        }

        try:
            # Trigger single-shot conversion for all 3 axes
            print(f"[{self.sensor_id}] Triggering single-shot measurement...")
            async with self.i2c_lock:
                self.i2c.writeto_mem(self.i2c_addr, self.REG_POLL, bytes([self.POLL_XYZ]))

            # RM3100 conversion time requirement
            await asyncio.sleep(self.MEASUREMENT_DELAY_S)

            # Wait for data ready status
            print(f"[{self.sensor_id}] Waiting for data ready status...")
            data_ready = False
            for retry in range(self.STATUS_RETRY_COUNT):
                async with self.i2c_lock:
                    status = self.i2c.readfrom_mem(self.i2c_addr, self.REG_STATUS, 1)[0]
                if status & self.STATUS_DRDY:
                    data_ready = True
                    print(f"[{self.sensor_id}] Data ready (status=0x{status:02X})")
                    break
                print(f"[{self.sensor_id}] Data not ready, retry {retry + 1}/{self.STATUS_RETRY_COUNT} (status=0x{status:02X})")
                await asyncio.sleep(self.STATUS_RETRY_DELAY_S)

            if not data_ready:
                print(f"[{self.sensor_id}] ERROR: RM3100 data not ready after {self.STATUS_RETRY_COUNT} retries, returning safe defaults")
                return safe_result

            # Read raw magnetic field data
            print(f"[{self.sensor_id}] Reading raw magnetic field data...")
            async with self.i2c_lock:
                raw_block = self.i2c.readfrom_mem(self.i2c_addr, self.REG_MX, 9)

            # Convert 24-bit signed values
            raw_x = self._convert_24bit_signed(raw_block[0], raw_block[1], raw_block[2])
            raw_y = self._convert_24bit_signed(raw_block[3], raw_block[4], raw_block[5])
            raw_z = self._convert_24bit_signed(raw_block[6], raw_block[7], raw_block[8])
            
            print(f"[{self.sensor_id}] Raw counts: x={raw_x}, y={raw_y}, z={raw_z}")

            # Convert to microTeslas
            x_uT = raw_x / self.sensitivity_factor
            y_uT = raw_y / self.sensitivity_factor
            z_uT = raw_z / self.sensitivity_factor
            magnitude = math.sqrt((x_uT * x_uT) + (y_uT * y_uT) + (z_uT * z_uT))

            print(f"[{self.sensor_id}] Converted: x={x_uT:.2f}µT, y={y_uT:.2f}µT, z={z_uT:.2f}µT, magnitude={magnitude:.2f}µT")

            result = {
                'value': round(magnitude, 2),
                'x': round(x_uT, 2),
                'y': round(y_uT, 2),
                'z': round(z_uT, 2),
                'raw_samples': {
                    'x': raw_x,
                    'y': raw_y,
                    'z': raw_z
                }
            }
            
            print(f"[{self.sensor_id}] Reading complete, returning magnitude={result['value']}µT")
            return result

        except Exception as e:
            print(f"[{self.sensor_id}] ERROR reading RM3100: {e}")
            return safe_result

    def _convert_24bit_signed(self, msb, mid, lsb):
        """
        Convert a 24-bit two's-complement value to a signed integer.
        """
        value = (msb << 16) | (mid << 8) | lsb
        if value & 0x800000:
            value -= 0x1000000
        return value

# Made with Bob