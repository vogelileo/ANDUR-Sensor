"""
WiFi Manager - Handle both Station (client) and Access Point (host) modes

Provides flexible WiFi connectivity for Raspberry Pi Pico W:
- Station mode: Connect to existing WiFi network
- Access Point mode: Create own WiFi network (hotspot)
- Automatic fallback: Try station first, fall back to AP if connection fails

MicroPython compatible.
"""

import time
import asyncio

try:
    import network
    NETWORK_AVAILABLE = True
except ImportError:
    NETWORK_AVAILABLE = False


class WiFiManager:
    """
    Manage WiFi connectivity in both station and access point modes.
    """
    
    def __init__(self):
        """Initialize WiFi manager."""
        self.wlan_sta = None
        self.wlan_ap = None
        self.mode = None  # 'station', 'ap', or None
        self.ip_address = None
        
    async def connect_station(self, ssid, password, timeout_seconds=30):
        """
        Connect to existing WiFi network (Station mode).
        
        Args:
            ssid: WiFi network name
            password: WiFi password
            timeout_seconds: Connection timeout
        
        Returns:
            bool: True if connected, False otherwise
        """
        if not NETWORK_AVAILABLE:
            print("[WiFi] Network module not available")
            return False
        
        try:
            print(f"[WiFi] Connecting to '{ssid}' (Station mode)...")
            
            # Create station interface
            self.wlan_sta = network.WLAN(network.STA_IF)
            self.wlan_sta.active(True)
            self.wlan_sta.connect(ssid, password)
            
            # Wait for connection
            start_time = time.time()
            while not self.wlan_sta.isconnected():
                if time.time() - start_time > timeout_seconds:
                    print(f"[WiFi] Connection timeout after {timeout_seconds}s")
                    self.wlan_sta.active(False)
                    return False
                await asyncio.sleep(1)
                print("[WiFi] Connecting...")
            
            # Get connection info
            self.ip_address, subnet, gateway, dns = self.wlan_sta.ifconfig()
            self.mode = 'station'
            
            print("[WiFi] Connected successfully!")
            print(f"[WiFi] Mode: Station (Client)")
            print(f"[WiFi] IP Address: {self.ip_address}")
            print(f"[WiFi] Subnet: {subnet}")
            print(f"[WiFi] Gateway: {gateway}")
            print(f"[WiFi] DNS: {dns}")
            
            return True
            
        except Exception as e:
            print(f"[WiFi] Station connection error: {e}")
            if self.wlan_sta:
                self.wlan_sta.active(False)
            return False
    
    def start_access_point(self, ssid, password=None, channel=6):
        """
        Create WiFi access point (AP mode) - host your own network.
        
        Args:
            ssid: Network name for the access point
            password: Password (None for open network, min 8 chars for WPA2)
            channel: WiFi channel (1-11)
        
        Returns:
            bool: True if AP started, False otherwise
        """
        if not NETWORK_AVAILABLE:
            print("[WiFi] Network module not available")
            return False
        
        try:
            print(f"[WiFi] Starting Access Point '{ssid}'...")
            
            # Create AP interface
            self.wlan_ap = network.WLAN(network.AP_IF)
            self.wlan_ap.active(True)
            
            # Configure AP
            if password and len(password) >= 8:
                # WPA2 secured network
                self.wlan_ap.config(
                    essid=ssid,
                    password=password,
                    channel=channel,
                    security=network.AUTH_WPA2_PSK
                )
                print(f"[WiFi] Security: WPA2 (password protected)")
            else:
                # Open network (no password)
                self.wlan_ap.config(
                    essid=ssid,
                    channel=channel,
                    security=network.AUTH_OPEN
                )
                print(f"[WiFi] Security: Open (no password)")
            
            # Wait for AP to be ready
            time.sleep(1)
            
            # Get AP info
            self.ip_address, subnet, gateway, dns = self.wlan_ap.ifconfig()
            self.mode = 'ap'
            
            print("[WiFi] Access Point started successfully!")
            print(f"[WiFi] Mode: Access Point (Host)")
            print(f"[WiFi] Network Name (SSID): {ssid}")
            print(f"[WiFi] IP Address: {self.ip_address}")
            print(f"[WiFi] Channel: {channel}")
            print(f"[WiFi] Connect to this network and access: http://{self.ip_address}/")
            
            return True
            
        except Exception as e:
            print(f"[WiFi] AP start error: {e}")
            if self.wlan_ap:
                self.wlan_ap.active(False)
            return False
    
    async def connect_auto(self, config):
        """
        Automatic WiFi connection with fallback.
        
        Tries to connect in this order:
        1. Station mode (connect to existing network) if configured
        2. Access Point mode (create own network) as fallback
        
        Args:
            config: WiFi configuration dict with keys:
                - mode: 'station', 'ap', or 'auto' (default)
                - station: dict with ssid, password, timeout_seconds
                - ap: dict with ssid, password (optional), channel
        
        Returns:
            bool: True if any mode succeeded, False otherwise
        """
        mode = config.get('mode', 'auto')
        
        # Try station mode first if configured
        if mode in ['station', 'auto'] and 'station' in config:
            station_config = config['station']
            ssid = station_config.get('ssid')
            password = station_config.get('password')
            timeout = station_config.get('timeout_seconds', 30)
            
            if ssid and password:
                if await self.connect_station(ssid, password, timeout):
                    return True
                print("[WiFi] Station mode failed, trying AP mode...")
        
        # Fall back to AP mode if station failed or not configured
        if mode in ['ap', 'auto'] and 'ap' in config:
            ap_config = config['ap']
            ssid = ap_config.get('ssid', 'PicoSensor')
            password = ap_config.get('password')  # None for open network
            channel = ap_config.get('channel', 6)
            
            return self.start_access_point(ssid, password, channel)
        
        print("[WiFi] No valid WiFi configuration found")
        return False
    
    def get_info(self):
        """
        Get current WiFi connection information.
        
        Returns:
            dict: WiFi status information
        """
        return {
            'mode': self.mode,
            'ip_address': self.ip_address,
            'connected': self.mode is not None
        }
    
    def disconnect(self):
        """Disconnect and deactivate WiFi."""
        if self.wlan_sta:
            self.wlan_sta.active(False)
            self.wlan_sta = None
        if self.wlan_ap:
            self.wlan_ap.active(False)
            self.wlan_ap = None
        self.mode = None
        self.ip_address = None
        print("[WiFi] Disconnected")


# Made with Bob