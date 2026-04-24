"""
Configuration Loader for MicroPython Sensor System

This module provides functionality to load and validate the system configuration
from a JSON file. It ensures all required fields are present and properly formatted.

MicroPython compatible - no typing module used.
"""

import json


def load_config(filename="config.json"):
    """
    Load and validate configuration from JSON file.
    
    Args:
        filename: Path to the configuration file (default: "config.json")
    
    Returns:
        dict: Validated configuration dictionary with keys:
            - sensors: List of sensor configurations
            - algorithms: List of algorithm configurations
            - lora: LoRa communication settings
            - i2c: I2C bus settings
    
    Raises:
        ValueError: If configuration is invalid or missing required fields
        OSError: If configuration file cannot be read
    
    Example usage:
        config = load_config("config.json")
        sensors_config = config["sensors"]
        algorithms_config = config["algorithms"]
        lora_config = config["lora"]
        i2c_config = config["i2c"]
    """
    try:
        with open(filename, 'r') as f:
            config = json.load(f)
    except OSError as e:
        raise OSError("Failed to read configuration file '{}': {}".format(filename, str(e)))
    except ValueError as e:
        raise ValueError("Invalid JSON in configuration file '{}': {}".format(filename, str(e)))
    
    # Validate top-level structure
    _validate_top_level(config)
    
    # Validate sensors configuration
    _validate_sensors(config["sensors"])
    
    # Validate algorithms configuration
    _validate_algorithms(config["algorithms"], config["sensors"])
    
    # Validate LoRa configuration
    _validate_lora(config["lora"])
    
    # Validate I2C configuration
    _validate_i2c(config["i2c"])
    
    return config


def _validate_top_level(config):
    """Validate top-level configuration structure."""
    required_keys = ["sensors", "algorithms", "lora", "i2c"]
    for key in required_keys:
        if key not in config:
            raise ValueError("Missing required configuration section: '{}'".format(key))
    
    if not isinstance(config["sensors"], list):
        raise ValueError("'sensors' must be a list")
    
    if not isinstance(config["algorithms"], list):
        raise ValueError("'algorithms' must be a list")
    
    if not isinstance(config["lora"], dict):
        raise ValueError("'lora' must be a dictionary")
    
    if not isinstance(config["i2c"], dict):
        raise ValueError("'i2c' must be a dictionary")
    
    # Optional WiFi configuration
    if "wifi" in config:
        if not isinstance(config["wifi"], dict):
            raise ValueError("'wifi' must be a dictionary")
        _validate_wifi(config["wifi"])
    
    # Optional web server configuration
    if "web_server" in config:
        if not isinstance(config["web_server"], dict):
            raise ValueError("'web_server' must be a dictionary")
        _validate_web_server(config["web_server"])


def _validate_sensors(sensors):
    """Validate sensors configuration."""
    if len(sensors) == 0:
        raise ValueError("At least one sensor must be configured")
    
    sensor_ids = set()
    required_fields = ["id", "type", "update_interval", "buffer_size", "enabled"]
    
    for i, sensor in enumerate(sensors):
        # Check required fields
        for field in required_fields:
            if field not in sensor:
                raise ValueError("Sensor {} missing required field: '{}'".format(i, field))
        
        # Check for duplicate IDs
        sensor_id = sensor["id"]
        if sensor_id in sensor_ids:
            raise ValueError("Duplicate sensor ID: '{}'".format(sensor_id))
        sensor_ids.add(sensor_id)
        
        # Validate field types and values
        if not isinstance(sensor["id"], str) or len(sensor["id"]) == 0:
            raise ValueError("Sensor {} 'id' must be a non-empty string".format(i))
        
        if not isinstance(sensor["type"], str) or len(sensor["type"]) == 0:
            raise ValueError("Sensor {} 'type' must be a non-empty string".format(i))
        
        if not isinstance(sensor["update_interval"], (int, float)) or sensor["update_interval"] <= 0:
            raise ValueError("Sensor {} 'update_interval' must be a positive number".format(i))
        
        if not isinstance(sensor["buffer_size"], int) or sensor["buffer_size"] <= 0:
            raise ValueError("Sensor {} 'buffer_size' must be a positive integer".format(i))
        
        if not isinstance(sensor["enabled"], bool):
            raise ValueError("Sensor {} 'enabled' must be a boolean".format(i))
        
        # Validate sensor-specific fields
        sensor_type = sensor["type"]
        
        # i2c_addr is required for I2C-based sensors
        if sensor_type in ["magnetic", "temperature", "pressure", "humidity"]:
            if "i2c_addr" not in sensor:
                raise ValueError("Sensor {} of type '{}' requires 'i2c_addr' field".format(i, sensor_type))
            if not isinstance(sensor["i2c_addr"], str):
                raise ValueError("Sensor {} 'i2c_addr' must be a string".format(i))
        
        # Microwave sensor requires pin_i
        elif sensor_type == "microwave":
            if "pin_i" not in sensor:
                raise ValueError("Sensor {} of type 'microwave' requires 'pin_i' field".format(i))
            if not isinstance(sensor["pin_i"], int) or sensor["pin_i"] < 0:
                raise ValueError("Sensor {} 'pin_i' must be a non-negative integer".format(i))
            
            # Optional pin_q
            if "pin_q" in sensor:
                if not isinstance(sensor["pin_q"], int) or sensor["pin_q"] < 0:
                    raise ValueError("Sensor {} 'pin_q' must be a non-negative integer".format(i))
            
            # Optional sample_count
            if "sample_count" in sensor:
                if not isinstance(sensor["sample_count"], int) or sensor["sample_count"] <= 0:
                    raise ValueError("Sensor {} 'sample_count' must be a positive integer".format(i))
            
            # Optional power_pin
            if "power_pin" in sensor:
                if not isinstance(sensor["power_pin"], int) or sensor["power_pin"] < 0:
                    raise ValueError("Sensor {} 'power_pin' must be a non-negative integer".format(i))
            
            # Optional warmup_ms
            if "warmup_ms" in sensor:
                if not isinstance(sensor["warmup_ms"], int) or sensor["warmup_ms"] < 0:
                    raise ValueError("Sensor {} 'warmup_ms' must be a non-negative integer".format(i))
            
            # Optional target_sample_rate_hz
            if "target_sample_rate_hz" in sensor:
                if not isinstance(sensor["target_sample_rate_hz"], (int, float)) or sensor["target_sample_rate_hz"] <= 0:
                    raise ValueError("Sensor {} 'target_sample_rate_hz' must be a positive number".format(i))
            
            # Optional min_sample_rate_hz
            if "min_sample_rate_hz" in sensor:
                if not isinstance(sensor["min_sample_rate_hz"], (int, float)) or sensor["min_sample_rate_hz"] <= 0:
                    raise ValueError("Sensor {} 'min_sample_rate_hz' must be a positive number".format(i))
                
                # If both target and min are specified, min should be <= target
                if "target_sample_rate_hz" in sensor:
                    if sensor["min_sample_rate_hz"] > sensor["target_sample_rate_hz"]:
                        raise ValueError("Sensor {} 'min_sample_rate_hz' must be <= 'target_sample_rate_hz'".format(i))


def _validate_algorithms(algorithms, sensors):
    """Validate algorithms configuration."""
    if len(algorithms) == 0:
        raise ValueError("At least one algorithm must be configured")
    
    # Build set of valid sensor IDs
    sensor_ids = {sensor["id"] for sensor in sensors}
    
    algorithm_ids = set()
    required_fields = ["id", "type", "sensor_id", "check_interval", "params", "enabled"]
    
    for i, algorithm in enumerate(algorithms):
        # Check required fields
        for field in required_fields:
            if field not in algorithm:
                raise ValueError("Algorithm {} missing required field: '{}'".format(i, field))
        
        # Check for duplicate IDs
        algorithm_id = algorithm["id"]
        if algorithm_id in algorithm_ids:
            raise ValueError("Duplicate algorithm ID: '{}'".format(algorithm_id))
        algorithm_ids.add(algorithm_id)
        
        # Validate field types and values
        if not isinstance(algorithm["id"], str) or len(algorithm["id"]) == 0:
            raise ValueError("Algorithm {} 'id' must be a non-empty string".format(i))
        
        if not isinstance(algorithm["type"], str) or len(algorithm["type"]) == 0:
            raise ValueError("Algorithm {} 'type' must be a non-empty string".format(i))
        
        # Validate sensor_id references an existing sensor
        if algorithm["sensor_id"] not in sensor_ids:
            raise ValueError("Algorithm {} references non-existent sensor: '{}'".format(i, algorithm["sensor_id"]))
        
        if not isinstance(algorithm["check_interval"], (int, float)) or algorithm["check_interval"] <= 0:
            raise ValueError("Algorithm {} 'check_interval' must be a positive number".format(i))
        
        if not isinstance(algorithm["params"], dict):
            raise ValueError("Algorithm {} 'params' must be a dictionary".format(i))
        
        if not isinstance(algorithm["enabled"], bool):
            raise ValueError("Algorithm {} 'enabled' must be a boolean".format(i))
        
        # Validate algorithm-specific parameters
        _validate_algorithm_params(algorithm, i)


def _validate_algorithm_params(algorithm, index):
    """Validate algorithm-specific parameters."""
    algo_type = algorithm["type"]
    params = algorithm["params"]
    
    if algo_type == "threshold":
        # Threshold algorithm requires: threshold, direction
        if "threshold" not in params:
            raise ValueError("Algorithm {} (threshold) missing 'threshold' parameter".format(index))
        if "direction" not in params:
            raise ValueError("Algorithm {} (threshold) missing 'direction' parameter".format(index))
        
        if not isinstance(params["threshold"], (int, float)):
            raise ValueError("Algorithm {} 'threshold' must be a number".format(index))
        
        if params["direction"] not in ["above", "below", "both"]:
            raise ValueError("Algorithm {} 'direction' must be 'above', 'below', or 'both'".format(index))
    
    elif algo_type == "moving_average":
        # Moving average requires: window_size, threshold, direction
        if "window_size" not in params:
            raise ValueError("Algorithm {} (moving_average) missing 'window_size' parameter".format(index))
        if "threshold" not in params:
            raise ValueError("Algorithm {} (moving_average) missing 'threshold' parameter".format(index))
        if "direction" not in params:
            raise ValueError("Algorithm {} (moving_average) missing 'direction' parameter".format(index))
        
        if not isinstance(params["window_size"], int) or params["window_size"] <= 0:
            raise ValueError("Algorithm {} 'window_size' must be a positive integer".format(index))
        
        if not isinstance(params["threshold"], (int, float)):
            raise ValueError("Algorithm {} 'threshold' must be a number".format(index))
        
        if params["direction"] not in ["above", "below", "both"]:
            raise ValueError("Algorithm {} 'direction' must be 'above', 'below', or 'both'".format(index))
    
    elif algo_type == "random":
        # Random algorithm requires: min_value, max_value, trigger_probability
        if "min_value" not in params:
            raise ValueError("Algorithm {} (random) missing 'min_value' parameter".format(index))
        if "max_value" not in params:
            raise ValueError("Algorithm {} (random) missing 'max_value' parameter".format(index))
        if "trigger_probability" not in params:
            raise ValueError("Algorithm {} (random) missing 'trigger_probability' parameter".format(index))
        
        if not isinstance(params["min_value"], int) or params["min_value"] < 0 or params["min_value"] > 10000:
            raise ValueError("Algorithm {} 'min_value' must be an integer between 0 and 10000".format(index))
        
        if not isinstance(params["max_value"], int) or params["max_value"] < 0 or params["max_value"] > 10000:
            raise ValueError("Algorithm {} 'max_value' must be an integer between 0 and 10000".format(index))
        
        if not isinstance(params["trigger_probability"], (int, float)) or params["trigger_probability"] < 0.0 or params["trigger_probability"] > 1.0:
            raise ValueError("Algorithm {} 'trigger_probability' must be a number between 0.0 and 1.0".format(index))
    
    elif algo_type == "microwave_detection":
        # Microwave detection algorithm requires: threshold, streak_required
        if "threshold" not in params:
            raise ValueError("Algorithm {} (microwave_detection) missing 'threshold' parameter".format(index))
        if "streak_required" not in params:
            raise ValueError("Algorithm {} (microwave_detection) missing 'streak_required' parameter".format(index))
        
        if not isinstance(params["threshold"], (int, float)) or params["threshold"] < 0:
            raise ValueError("Algorithm {} 'threshold' must be a non-negative number".format(index))
        
        if not isinstance(params["streak_required"], int) or params["streak_required"] < 1:
            raise ValueError("Algorithm {} 'streak_required' must be a positive integer".format(index))
        
        # Optional max_output
        if "max_output" in params:
            if not isinstance(params["max_output"], int) or params["max_output"] < 1 or params["max_output"] > 10000:
                raise ValueError("Algorithm {} 'max_output' must be an integer between 1 and 10000".format(index))
        
        # Optional scale_factor
        if "scale_factor" in params:
            if not isinstance(params["scale_factor"], (int, float)) or params["scale_factor"] <= 0:
                raise ValueError("Algorithm {} 'scale_factor' must be a positive number".format(index))
    
    elif algo_type == "adaptive_threshold":
        # Adaptive threshold algorithm requires: initial_baseline, threshold_margin, adaptation_rate, streak_required
        if "initial_baseline" not in params:
            raise ValueError("Algorithm {} (adaptive_threshold) missing 'initial_baseline' parameter".format(index))
        if "threshold_margin" not in params:
            raise ValueError("Algorithm {} (adaptive_threshold) missing 'threshold_margin' parameter".format(index))
        if "adaptation_rate" not in params:
            raise ValueError("Algorithm {} (adaptive_threshold) missing 'adaptation_rate' parameter".format(index))
        if "streak_required" not in params:
            raise ValueError("Algorithm {} (adaptive_threshold) missing 'streak_required' parameter".format(index))
        
        if not isinstance(params["initial_baseline"], (int, float)) or params["initial_baseline"] < 0:
            raise ValueError("Algorithm {} 'initial_baseline' must be a non-negative number".format(index))
        
        if not isinstance(params["threshold_margin"], (int, float)) or params["threshold_margin"] < 0:
            raise ValueError("Algorithm {} 'threshold_margin' must be a non-negative number".format(index))
        
        if not isinstance(params["adaptation_rate"], (int, float)) or params["adaptation_rate"] < 0 or params["adaptation_rate"] > 1:
            raise ValueError("Algorithm {} 'adaptation_rate' must be a number between 0 and 1".format(index))
        
        if not isinstance(params["streak_required"], int) or params["streak_required"] < 1:
            raise ValueError("Algorithm {} 'streak_required' must be a positive integer".format(index))
        
        # Optional parameters
        if "max_output" in params:
            if not isinstance(params["max_output"], int) or params["max_output"] < 1 or params["max_output"] > 10000:
                raise ValueError("Algorithm {} 'max_output' must be an integer between 1 and 10000".format(index))
        
        if "scale_factor" in params:
            if not isinstance(params["scale_factor"], (int, float)) or params["scale_factor"] <= 0:
                raise ValueError("Algorithm {} 'scale_factor' must be a positive number".format(index))
        
        if "baseline_update_delay" in params:
            if not isinstance(params["baseline_update_delay"], (int, float)) or params["baseline_update_delay"] < 0:
                raise ValueError("Algorithm {} 'baseline_update_delay' must be a non-negative number".format(index))
    
    elif algo_type == "energy_hysteresis":
        # Energy hysteresis algorithm requires: activation_threshold, confirmation_threshold, deactivation_threshold
        if "activation_threshold" not in params:
            raise ValueError("Algorithm {} (energy_hysteresis) missing 'activation_threshold' parameter".format(index))
        if "confirmation_threshold" not in params:
            raise ValueError("Algorithm {} (energy_hysteresis) missing 'confirmation_threshold' parameter".format(index))
        if "deactivation_threshold" not in params:
            raise ValueError("Algorithm {} (energy_hysteresis) missing 'deactivation_threshold' parameter".format(index))
        
        if not isinstance(params["activation_threshold"], (int, float)) or params["activation_threshold"] < 0:
            raise ValueError("Algorithm {} 'activation_threshold' must be a non-negative number".format(index))
        
        if not isinstance(params["confirmation_threshold"], (int, float)) or params["confirmation_threshold"] < 0:
            raise ValueError("Algorithm {} 'confirmation_threshold' must be a non-negative number".format(index))
        
        if not isinstance(params["deactivation_threshold"], (int, float)) or params["deactivation_threshold"] < 0:
            raise ValueError("Algorithm {} 'deactivation_threshold' must be a non-negative number".format(index))
        
        # Optional parameters
        if "detection_window" in params:
            if not isinstance(params["detection_window"], int) or params["detection_window"] < 1:
                raise ValueError("Algorithm {} 'detection_window' must be a positive integer".format(index))
        
        if "cooldown_window" in params:
            if not isinstance(params["cooldown_window"], int) or params["cooldown_window"] < 1:
                raise ValueError("Algorithm {} 'cooldown_window' must be a positive integer".format(index))
        
        if "energy_window_size" in params:
            if not isinstance(params["energy_window_size"], int) or params["energy_window_size"] < 1:
                raise ValueError("Algorithm {} 'energy_window_size' must be a positive integer".format(index))
        
        if "max_output" in params:
            if not isinstance(params["max_output"], int) or params["max_output"] < 1 or params["max_output"] > 10000:
                raise ValueError("Algorithm {} 'max_output' must be an integer between 1 and 10000".format(index))
        
        if "scale_factor" in params:
            if not isinstance(params["scale_factor"], (int, float)) or params["scale_factor"] <= 0:
                raise ValueError("Algorithm {} 'scale_factor' must be a positive number".format(index))


def _validate_lora(lora):
    """Validate LoRa configuration."""
    required_fields = ["spi_id", "cs_pin", "reset_pin", "frequency"]
    
    for field in required_fields:
        if field not in lora:
            raise ValueError("LoRa configuration missing required field: '{}'".format(field))
    
    if not isinstance(lora["spi_id"], int) or lora["spi_id"] < 0:
        raise ValueError("LoRa 'spi_id' must be a non-negative integer")
    
    if not isinstance(lora["cs_pin"], int) or lora["cs_pin"] < 0:
        raise ValueError("LoRa 'cs_pin' must be a non-negative integer")
    
    if not isinstance(lora["reset_pin"], int) or lora["reset_pin"] < 0:
        raise ValueError("LoRa 'reset_pin' must be a non-negative integer")
    
    if not isinstance(lora["frequency"], int) or lora["frequency"] <= 0:
        raise ValueError("LoRa 'frequency' must be a positive integer")


def _validate_i2c(i2c):
    """Validate I2C configuration."""
    required_fields = ["id", "scl_pin", "sda_pin", "freq"]
    
    for field in required_fields:
        if field not in i2c:
            raise ValueError("I2C configuration missing required field: '{}'".format(field))
    
    if not isinstance(i2c["id"], int) or i2c["id"] < 0:
        raise ValueError("I2C 'id' must be a non-negative integer")
    
    if not isinstance(i2c["scl_pin"], int) or i2c["scl_pin"] < 0:
        raise ValueError("I2C 'scl_pin' must be a non-negative integer")
    
    if not isinstance(i2c["sda_pin"], int) or i2c["sda_pin"] < 0:
        raise ValueError("I2C 'sda_pin' must be a non-negative integer")
    
    if not isinstance(i2c["freq"], int) or i2c["freq"] <= 0:
        raise ValueError("I2C 'freq' must be a positive integer")


# Example usage (commented out for production):
# if __name__ == "__main__":
#     try:
#         config = load_config("config.json")
#         print("Configuration loaded successfully!")
#         print("Sensors:", len(config["sensors"]))
#         print("Algorithms:", len(config["algorithms"]))
#         print("LoRa frequency:", config["lora"]["frequency"])
#         print("I2C frequency:", config["i2c"]["freq"])
#     except (ValueError, OSError) as e:
#         print("Configuration error:", str(e))

# Made with Bob


def _validate_wifi(wifi):
    """Validate WiFi configuration (Access Point mode only)."""
    required_fields = ["enabled", "ssid"]
    
    for field in required_fields:
        if field not in wifi:
            raise ValueError("WiFi configuration missing required field: '{}'".format(field))
    
    if not isinstance(wifi["enabled"], bool):
        raise ValueError("WiFi 'enabled' must be a boolean")
    
    if not isinstance(wifi["ssid"], str):
        raise ValueError("WiFi 'ssid' must be a string")
    
    # Optional password
    if "password" in wifi:
        if not isinstance(wifi["password"], str):
            raise ValueError("WiFi 'password' must be a string")
        if len(wifi["password"]) > 0 and len(wifi["password"]) < 8:
            raise ValueError("WiFi 'password' must be at least 8 characters or empty for open network")
    
    # Optional channel
    if "channel" in wifi:
        if not isinstance(wifi["channel"], int) or wifi["channel"] < 1 or wifi["channel"] > 11:
            raise ValueError("WiFi 'channel' must be an integer between 1 and 11")


def _validate_web_server(web_server):
    """Validate web server configuration."""
    required_fields = ["enabled", "port"]
    
    for field in required_fields:
        if field not in web_server:
            raise ValueError("Web server configuration missing required field: '{}'".format(field))
    
    if not isinstance(web_server["enabled"], bool):
        raise ValueError("Web server 'enabled' must be a boolean")
    
    if not isinstance(web_server["port"], int) or web_server["port"] <= 0 or web_server["port"] > 65535:
        raise ValueError("Web server 'port' must be an integer between 1 and 65535")
