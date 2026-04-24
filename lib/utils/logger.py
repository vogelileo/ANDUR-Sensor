"""
Logger utility for MicroPython sensor system

Provides a simple debug logging system that can be toggled on/off via config.json.
This allows all debug logging to be controlled from a single configuration setting.
"""

import json

# Global flag for debug logging (loaded from config)
_debug_enabled = False
_config_loaded = False


def _load_config():
    """
    Load debug_logging setting from config.json.
    
    This is called once on first use to avoid repeated file reads.
    Memory-efficient for MicroPython environments.
    """
    global _debug_enabled, _config_loaded
    
    if _config_loaded:
        return
    
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            _debug_enabled = config.get('debug_logging', False)
            _config_loaded = True
            # Only print this message if debug is enabled
            if _debug_enabled:
                print(f"[LOGGER] Debug logging enabled from config.json")
    except Exception as e:
        # If config can't be loaded, default to disabled
        print(f"[LOGGER] Warning: Could not load config.json, debug logging disabled: {e}")
        _debug_enabled = False
        _config_loaded = True


def debug_print(tag, message):
    """
    Print a debug message if debug logging is enabled.
    
    This function checks the debug_logging setting from config.json
    and only prints if it's set to true. This allows all debug logging
    to be toggled on/off from a single configuration setting.
    
    Args:
        tag: String tag to prefix the message (e.g., "[DEBUG]", "[SENSOR DATA]")
        message: The message to print
    
    Example:
        debug_print("[DEBUG]", "Sensor reading started")
        debug_print("[SENSOR DATA]", f"Value: {value}")
    """
    # Load config on first use
    if not _config_loaded:
        _load_config()
    
    # Only print if debug is enabled
    if _debug_enabled:
        print(f"{tag} {message}")


def is_debug_enabled():
    """
    Check if debug logging is enabled.
    
    Returns:
        bool: True if debug logging is enabled, False otherwise
    """
    if not _config_loaded:
        _load_config()
    return _debug_enabled


def reload_config():
    """
    Force reload of the config file.
    
    This can be called to pick up changes to config.json without restarting.
    Useful for development/testing.
    """
    global _config_loaded
    _config_loaded = False
    _load_config()


# Made with Bob