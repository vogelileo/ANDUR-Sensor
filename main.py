"""
MicroPython Sensor System - Main Application

This is the main entry point for the MicroPython sensor system.
It orchestrates all components using asyncio for concurrent execution:
- Loads configuration
- Initializes I2C and LoRa interfaces
- Creates and manages sensors
- Creates and manages algorithms
- Runs everything in parallel

MicroPython compatible - no typing module used.
"""

import asyncio
import gc
import time
from machine import I2C, SPI, Pin

from lib.core.data_store import DataStore
from lib.sensors.alibi_sensor import AlibiSensor
from lib.sensors.microwave_sensor import MicrowaveSensor
from lib.sensors.gps_battery_sensor import GPSBatterySensor
from lib.algorithms.random_algorithm import RandomAlgorithm
from lib.algorithms.microwave_detection_algorithm import MicrowaveDetectionAlgorithm
from lib.algorithms.adaptive_threshold_algorithm import AdaptiveThresholdAlgorithm
from lib.algorithms.energy_hysteresis_algorithm import EnergyHysteresisAlgorithm
from lib.communication.lora_interface import LoRaInterface
from config_loader import load_config

# WiFi and web server imports (only for Pico W)
try:
    import network
    from web_server import WebServer
    from lib.utils.system_monitor import get_monitor
    WIFI_AVAILABLE = True
except ImportError:
    WIFI_AVAILABLE = False
    print("[Main] WiFi not available (not Pico W or missing modules)")


def start_access_point(wifi_config):
    """
    Start WiFi Access Point (host own network).
    
    Args:
        wifi_config: dict with WiFi configuration
    
    Returns:
        WLAN object if successful, None otherwise
    """
    if not WIFI_AVAILABLE:
        print("[WiFi] WiFi not available on this device")
        return None
    
    try:
        ssid = wifi_config["ssid"]
        password = wifi_config.get("password")
        channel = wifi_config.get("channel", 6)
        
        print(f"[WiFi] Starting Access Point '{ssid}'...")
        
        # Create AP interface
        wlan = network.WLAN(network.AP_IF)
        wlan.active(True)
        
        # Configure AP - simplified for MicroPython compatibility
        if password and len(password) >= 8:
            # Secured network with password
            wlan.config(essid=ssid, password=password, channel=channel)
            print(f"[WiFi] Security: Password protected")
        else:
            # Open network (no password)
            wlan.config(essid=ssid, channel=channel)
            print(f"[WiFi] Security: Open (no password)")
        
        # Wait for AP to be ready
        time.sleep(1)
        
        # Get AP info
        ip, subnet, gateway, dns = wlan.ifconfig()
        print("[WiFi] Access Point started successfully!")
        print(f"[WiFi] Network Name (SSID): {ssid}")
        print(f"[WiFi] IP Address: {ip}")
        print(f"[WiFi] Channel: {channel}")
        print(f"[WiFi] Connect to this network and access: http://{ip}/")
        
        return wlan
        
    except Exception as e:
        print(f"[WiFi] Error starting AP: {e}")
        import sys
        sys.print_exception(e)
        return None


async def web_server_task(port=80):
    """
    Run the web server task.
    
    Args:
        port: HTTP port to listen on
    """
    if not WIFI_AVAILABLE:
        print("[WebServer] Cannot start - WiFi not available")
        return
    
    try:
        print(f"[WebServer] Starting web server on port {port}...")
        server = WebServer(port=port)
        await server.start()  # Async call - allows other tasks to run
    except Exception as e:
        print(f"[WebServer] Error: {e}")
        import sys
        sys.print_exception(e)


async def monitor_task():
    """
    Periodic system monitoring task.
    Prints system summary every 60 seconds.
    """
    if not WIFI_AVAILABLE:
        return
    
    try:
        monitor = get_monitor()
        while True:
            await asyncio.sleep(60)
            monitor.print_summary()
    except Exception as e:
        print(f"[Monitor] Error: {e}")


async def gc_task():
    """
    Periodic garbage collection task.
    Runs every 60 seconds to free up memory.
    """
    while True:
        await asyncio.sleep(60)
        gc.collect()
        try:
            free_mem = gc.mem_free()
            print(f"[GC] Garbage collection complete. Free memory: {free_mem} bytes")
        except AttributeError:
            # gc.mem_free() not available in all MicroPython versions
            print("[GC] Garbage collection complete")


def create_sensor(sensor_config, data_store, i2c_bus, monitor=None):
    """
    Factory function to create sensor instances based on configuration.
    
    Args:
        sensor_config: dict with sensor configuration
        data_store: DataStore instance
        i2c_bus: I2C bus instance
        monitor: SystemMonitor instance for tracking
    
    Returns:
        Sensor instance (MagneticSensor, TemperatureSensor, etc.)
    
    Raises:
        ValueError: If sensor type is unknown
    """
    sensor_type = sensor_config["type"]
    sensor_id = sensor_config["id"]
    update_interval = sensor_config["update_interval"]
    buffer_size = sensor_config["buffer_size"]
    
    # Removed magnetic and temperature sensor types - classes don't exist
    # if sensor_type == "magnetic":
    #     i2c_addr = int(sensor_config["i2c_addr"], 16)  # Convert hex string to int
    #     return MagneticSensor(
    #         sensor_id=sensor_id,
    #         data_store=data_store,
    #         update_interval=update_interval,
    #         buffer_size=buffer_size,
    #         i2c_bus=i2c_bus,
    #         i2c_addr=i2c_addr,
    #         monitor=monitor
    #     )
    # elif sensor_type == "temperature":
    #     i2c_addr = int(sensor_config["i2c_addr"], 16)  # Convert hex string to int
    #     return TemperatureSensor(
    #         sensor_id=sensor_id,
    #         data_store=data_store,
    #         update_interval=update_interval,
    #         buffer_size=buffer_size,
    #         i2c_bus=i2c_bus,
    #         i2c_addr=i2c_addr,
    #         monitor=monitor
    #     )
    
    if sensor_type == "alibi":
        # Alibi sensor doesn't need I2C, get optional parameters
        base_value = sensor_config.get("base_value", 50.0)
        variation = sensor_config.get("variation", 10.0)
        return AlibiSensor(
            sensor_id=sensor_id,
            data_store=data_store,
            update_interval=update_interval,
            buffer_size=buffer_size,
            base_value=base_value,
            variation=variation,
            monitor=monitor
        )
    elif sensor_type == "microwave":
        # Microwave sensor uses ADC pins
        pin_i = sensor_config["pin_i"]
        pin_q = sensor_config.get("pin_q")  # Optional Q channel
        sample_count = sensor_config.get("sample_count", 32)
        power_pin = sensor_config.get("power_pin")  # Optional power control
        warmup_ms = sensor_config.get("warmup_ms", 100)
        target_sample_rate_hz = sensor_config.get("target_sample_rate_hz")  # Optional sample rate validation
        min_sample_rate_hz = sensor_config.get("min_sample_rate_hz")  # Optional minimum rate
        return MicrowaveSensor(
            sensor_id=sensor_id,
            data_store=data_store,
            update_interval=update_interval,
            buffer_size=buffer_size,
            pin_i=pin_i,
            pin_q=pin_q,
            sample_count=sample_count,
            power_pin=power_pin,
            warmup_ms=warmup_ms,
            target_sample_rate_hz=target_sample_rate_hz,
            min_sample_rate_hz=min_sample_rate_hz,
            monitor=monitor
        )
    elif sensor_type == "gps_battery":
        # GPS and battery sensor with hardcoded values (no hardware needed)
        return GPSBatterySensor(
            sensor_id=sensor_id,
            data_store=data_store,
            update_interval=update_interval,
            buffer_size=buffer_size,
            monitor=monitor
        )
    else:
        raise ValueError("Unknown sensor type: {}".format(sensor_type))


def create_algorithm(algo_config, data_store, lora_interface, sensors_config, monitor=None):
    """
    Factory function to create algorithm instances based on configuration.
    
    Args:
        algo_config: dict with algorithm configuration
        data_store: DataStore instance
        lora_interface: LoRaInterface instance
        sensors_config: list of sensor configurations to extract MAC addresses
        monitor: SystemMonitor instance for tracking
    
    Returns:
        Algorithm instance (ThresholdDetector, MovingAverage, etc.)
    
    Raises:
        ValueError: If algorithm type is unknown
    """
    algo_type = algo_config["type"]
    algo_id = algo_config["id"]
    sensor_id = algo_config["sensor_id"]
    check_interval = algo_config["check_interval"]
    params = algo_config["params"]
    
    # Extract MAC address from sensor configuration
    sensor_mac = None
    for sensor_config in sensors_config:
        if sensor_config["id"] == sensor_id:
            sensor_mac = sensor_config.get("mac_address")
            break
    
    # Filter to only enabled sensors for payload building
    installed_sensors = [s for s in sensors_config if s.get("enabled", True)]
    
    # Removed threshold and moving_average algorithm types - classes don't exist
    # if algo_type == "threshold":
    #     return ThresholdDetector(
    #         algo_id=algo_id,
    #         sensor_id=sensor_id,
    #         data_store=data_store,
    #         lora_interface=lora_interface,
    #         check_interval=check_interval,
    #         params=params
    #     )
    # elif algo_type == "moving_average":
    #     return MovingAverage(
    #         algo_id=algo_id,
    #         sensor_id=sensor_id,
    #         data_store=data_store,
    #         lora_interface=lora_interface,
    #         check_interval=check_interval,
    #         params=params
    #     )
    
    if algo_type == "random":
        return RandomAlgorithm(
            algo_id=algo_id,
            sensor_id=sensor_id,
            data_store=data_store,
            lora_interface=lora_interface,
            check_interval=check_interval,
            params=params,
            sensor_mac=sensor_mac,
            monitor=monitor,
            installed_sensors=installed_sensors
        )
    elif algo_type == "microwave_detection":
        return MicrowaveDetectionAlgorithm(
            algo_id=algo_id,
            sensor_id=sensor_id,
            data_store=data_store,
            lora_interface=lora_interface,
            check_interval=check_interval,
            params=params,
            sensor_mac=sensor_mac,
            monitor=monitor,
            installed_sensors=installed_sensors
        )
    elif algo_type == "adaptive_threshold":
        return AdaptiveThresholdAlgorithm(
            algo_id=algo_id,
            sensor_id=sensor_id,
            data_store=data_store,
            lora_interface=lora_interface,
            check_interval=check_interval,
            params=params,
            sensor_mac=sensor_mac,
            monitor=monitor,
            installed_sensors=installed_sensors
        )
    elif algo_type == "energy_hysteresis":
        return EnergyHysteresisAlgorithm(
            algo_id=algo_id,
            sensor_id=sensor_id,
            data_store=data_store,
            lora_interface=lora_interface,
            check_interval=check_interval,
            params=params,
            sensor_mac=sensor_mac,
            monitor=monitor,
            installed_sensors=installed_sensors
        )
    else:
        raise ValueError("Unknown algorithm type: {}".format(algo_type))


async def main():
    """
    Main application entry point.
    
    Orchestrates the entire system:
    1. Load configuration
    2. Initialize hardware interfaces (I2C, SPI, LoRa)
    3. Create data store
    4. Create and register sensors
    5. Create algorithms
    6. Start all tasks concurrently
    """
    print("=" * 60)
    print("MicroPython Sensor System Starting...")
    print("=" * 60)

    time.sleep(2)
    
    try:
        # Load configuration
        print("\n[Main] Loading configuration...")
        config = load_config("config.json")
        print("[Main] Configuration loaded successfully")
        
        # Validate sensor types can be mapped to protocol enums
        print("\n[Main] Validating sensor types...")
        from lib.protocol.payload import get_sensor_enum_from_type, SensorEnum
        
        validation_errors = []
        for sensor_config in config["sensors"]:
            if not sensor_config.get("enabled", True):
                continue
            
            sensor_type = sensor_config.get("type", "")
            sensor_id = sensor_config.get("id", "unknown")
            
            # Skip gps_battery - it's not in the protocol enum
            if sensor_type == "gps_battery":
                continue
            
            sensor_enum = get_sensor_enum_from_type(sensor_type)
            if sensor_enum == SensorEnum.NOT_INSTALLED:
                validation_errors.append(f"Sensor '{sensor_id}' has unmapped type '{sensor_type}'")
        
        if validation_errors:
            print("[Main] ERROR: Sensor type validation failed:")
            for error in validation_errors:
                print(f"[Main]   - {error}")
            print("[Main] Please update config.json with valid sensor types")
            print("[Main] Valid types: microphone, bluetooth, audio, magnetometer, rfbeam, microwave, camera, seismic, alibi, gps_battery")
            return
        
        print("[Main] All sensor types validated successfully")
        
        # Initialize system monitor early
        print("\n[Main] Initializing system monitor...")
        monitor = get_monitor()
        print("[Main] System monitor initialized")
        
        # Start WiFi Access Point if enabled (Pico W only)
        wlan = None
        if WIFI_AVAILABLE and "wifi" in config and config["wifi"].get("enabled", False):
            wlan = start_access_point(config["wifi"])
            if wlan:
                print(f"[Main] WiFi AP started - Dashboard available at http://{wlan.ifconfig()[0]}/")
            else:
                print("[Main] WiFi AP failed - continuing without web server")
        
        # Initialize I2C bus
        print("\n[Main] Initializing I2C bus...")
        i2c_config = config["i2c"]
        i2c = I2C(
            i2c_config["id"],
            scl=Pin(i2c_config["scl_pin"]),
            sda=Pin(i2c_config["sda_pin"]),
            freq=i2c_config["freq"]
        )
        print("[Main] I2C bus initialized (SCL={}, SDA={}, freq={}Hz)".format(
            i2c_config["scl_pin"],
            i2c_config["sda_pin"],
            i2c_config["freq"]
        ))
        
        # Initialize SPI bus for LoRa
        print("\n[Main] Initializing SPI bus for LoRa...")
        lora_config = config["lora"]
        spi = SPI(
            lora_config["spi_id"],
            baudrate=1000000,
            polarity=0,
            phase=0
        )
        cs_pin = Pin(lora_config["cs_pin"], Pin.OUT)
        reset_pin = Pin(lora_config["reset_pin"], Pin.OUT)
        print("[Main] SPI bus initialized (SPI={}, CS={}, RST={})".format(
            lora_config["spi_id"],
            lora_config["cs_pin"],
            lora_config["reset_pin"]
        ))
        
        # Create LoRa interface
        print("\n[Main] Creating LoRa interface...")
        lora_interface = LoRaInterface(
            spi_bus=spi,
            cs_pin=cs_pin,
            reset_pin=reset_pin,
            config=lora_config,
            monitor=monitor
        )
        lora_interface.initialize()
        print("[Main] LoRa interface ready")
        
        # Create data store
        print("\n[Main] Creating data store...")
        data_store = DataStore()
        print("[Main] Data store created")
        
        # Create sensors (only enabled ones)
        print("\n[Main] Creating sensors...")
        sensors = []
        for sensor_config in config["sensors"]:
            if sensor_config.get("enabled", True):
                try:
                    sensor = create_sensor(sensor_config, data_store, i2c, monitor)
                    sensors.append(sensor)
                    
                    # Register sensor in data store
                    data_store.register_sensor(
                        sensor_config["id"],
                        sensor_config["buffer_size"]
                    )
                    print("[Main] Created sensor: {} ({})".format(
                        sensor_config["id"],
                        sensor_config["type"]
                    ))
                except Exception as e:
                    print("[Main] Error creating sensor {}: {}".format(
                        sensor_config["id"], e
                    ))
        
        if len(sensors) == 0:
            print("[Main] ERROR: No sensors created!")
            return
        
        print("[Main] Total sensors created: {}".format(len(sensors)))
        
        # Create algorithms (only enabled ones)
        print("\n[Main] Creating algorithms...")
        algorithms = []
        for algo_config in config["algorithms"]:
            if algo_config.get("enabled", True):
                try:
                    algorithm = create_algorithm(algo_config, data_store, lora_interface, config["sensors"], monitor)
                    algorithms.append(algorithm)
                    
                    # Register algorithm as consumer for shared frame access
                    algorithm.register_as_consumer()
                    
                    print("[Main] Created algorithm: {} ({})".format(
                        algo_config["id"],
                        algo_config["type"]
                    ))
                except Exception as e:
                    print("[Main] Error creating algorithm {}: {}".format(
                        algo_config["id"], e
                    ))
        
        if len(algorithms) == 0:
            print("[Main] WARNING: No algorithms created!")
        else:
            print("[Main] Total algorithms created: {}".format(len(algorithms)))
            print("[Main] All algorithms registered as frame consumers")
        
        # Collect garbage before starting main loop
        gc.collect()
        print("\n[Main] Memory cleanup complete")
        print("[Main] Free memory: {} bytes".format(gc.mem_free()))
        
        # Start all sensor and algorithm tasks concurrently
        print("\n" + "=" * 60)
        print("Starting all tasks...")
        print("=" * 60 + "\n")
        
        # Create task list
        sensor_tasks = []
        algo_tasks = []
        
        # Add sensor tasks
        for sensor in sensors:
            sensor_tasks.append(sensor.run())
        
        # Add algorithm tasks
        for algorithm in algorithms:
            algo_tasks.append(algorithm.run())
        
        # Prepare additional tasks
        additional_tasks = [gc_task()]
        
        # Add LoRa transmission worker task
        additional_tasks.append(lora_interface.transmission_worker())
        print("[Main] LoRa transmission worker will start")
        
        # Add web server task if WiFi is connected and enabled
        if wlan and "web_server" in config and config["web_server"].get("enabled", False):
            port = config["web_server"].get("port", 80)
            additional_tasks.append(web_server_task(port))
            print(f"[Main] Web server will start on port {port}")
        
        # Add monitoring task if WiFi is available
        if WIFI_AVAILABLE:
            additional_tasks.append(monitor_task())
            print("[Main] System monitoring enabled")
        
        # Start all tasks concurrently (sensors, algorithms, and additional tasks)
        # This will run forever until interrupted
        print(f"[Main] Starting {len(sensor_tasks)} sensors, {len(algo_tasks)} algorithms, and {len(additional_tasks)} system tasks")
        await asyncio.gather(
            *sensor_tasks,
            *algo_tasks,
            *additional_tasks,
            return_exceptions=True
        )
        
    except KeyboardInterrupt:
        print("\n\n[Main] Keyboard interrupt received")
        print("[Main] Shutting down gracefully...")
        
    except Exception as e:
        print("\n\n[Main] Fatal error: {}".format(e))
        print("[Main] System halted")
        raise


# Entry point
if __name__ == "__main__":
    try:
        # Run the main application
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Main] Shutdown complete")
    except Exception as e:
        print("\n[Main] Application crashed: {}".format(e))
        # Re-raise to see full traceback
        raise
    finally:
        print("\n[Main] Application terminated")
        print("=" * 60)

# Made with Bob