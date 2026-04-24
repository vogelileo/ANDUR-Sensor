"""
LoRa Message Formatter - Unified formatting for all LoRa message outputs
"""
import time

class LoRaMessageFormatter:
    @staticmethod
    def format_timestamp(timestamp, format_type='full'):
        """
        Format Unix timestamp to human-readable string.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            format_type: 'full' (date+time), 'time' (time only)
        """
        if format_type == 'time':
            # HH:MM:SS format
            t = time.localtime(timestamp)
            return "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])
        elif format_type == 'full':
            # YYYY-MM-DD HH:MM:SS format
            t = time.localtime(timestamp)
            return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                t[0], t[1], t[2], t[3], t[4], t[5]
            )
        else:
            return str(timestamp)
    
    @staticmethod
    def format_for_console(algo_id, sensor_id, value, timestamp):
        """Format for serial console output with full timestamp."""
        time_str = LoRaMessageFormatter.format_timestamp(timestamp, 'full')
        return "[LoRa] {} | {} @ {} | value={}".format(
            time_str, algo_id, sensor_id, value
        )
    
    @staticmethod
    def format_for_web(algo_id, sensor_id, value, timestamp):
        """Format for web UI (returns dict for JSON serialization)."""
        return {
            'algo': algo_id,
            'sensor': sensor_id,
            'value': value,
            'time': timestamp,
            'time_formatted': LoRaMessageFormatter.format_timestamp(timestamp, 'time')
        }

# Made with Bob
