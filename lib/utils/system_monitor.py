"""
SystemMonitor - Resource monitoring for MicroPython on Raspberry Pi Pico

Provides real-time monitoring of:
- Memory usage (free/used RAM)
- CPU frequency
- Task statistics
- Sensor/algorithm performance metrics

MicroPython compatible - designed for resource-constrained environments.
"""

import gc
import time
import micropython


class SystemMonitor:
    """
    Monitor system resources and performance metrics.
    
    Tracks memory usage, provides statistics on sensors and algorithms,
    and helps identify resource bottlenecks.
    """
    
    def __init__(self):
        """Initialize the system monitor."""
        self.start_time = time.time()
        self.last_gc_time = time.time()
        self.gc_count = 0
        
        # Performance tracking
        self.sensor_stats = {}
        self.algorithm_stats = {}
        
        # Memory tracking
        self.peak_memory_used = 0
        self.min_free_memory = float('inf')
        
        # LoRa message tracking (keep last 20 messages)
        self.lora_messages = []
        self.max_lora_messages = 20
        
        print("[SystemMonitor] Initialized")
    
    def add_lora_message(self, algo, sensor, value, timestamp):
        """Add a LoRa message to the history."""
        msg = {
            'algo': algo,
            'sensor': sensor,
            'value': value,
            'time': timestamp
        }
        self.lora_messages.append(msg)
        # Keep only last N messages
        if len(self.lora_messages) > self.max_lora_messages:
            self.lora_messages.pop(0)
    
    def get_lora_messages(self):
        """Get recent LoRa messages."""
        return list(reversed(self.lora_messages))  # Most recent first
    
    def get_memory_info(self):
        """
        Get current memory information.
        
        Returns:
            dict: Memory statistics with keys:
                - free: Free memory in bytes
                - allocated: Allocated memory in bytes
                - total: Total memory (estimated)
                - used_percent: Percentage of memory used
                - peak_used: Peak memory usage since start
        """
        try:
            free = gc.mem_free()
            allocated = gc.mem_alloc()
            total = free + allocated
            used_percent = (allocated / total) * 100 if total > 0 else 0
            
            # Track peak usage
            if allocated > self.peak_memory_used:
                self.peak_memory_used = allocated
            
            # Track minimum free memory
            if free < self.min_free_memory:
                self.min_free_memory = free
            
            return {
                'free': free,
                'allocated': allocated,
                'total': total,
                'used_percent': round(used_percent, 1),
                'peak_used': self.peak_memory_used,
                'min_free': self.min_free_memory
            }
        except AttributeError:
            # gc.mem_free() not available in all MicroPython versions
            return {
                'free': 0,
                'allocated': 0,
                'total': 0,
                'used_percent': 0,
                'peak_used': 0,
                'min_free': 0
            }
    
    def get_uptime(self):
        """
        Get system uptime.
        
        Returns:
            dict: Uptime information with keys:
                - seconds: Total uptime in seconds
                - formatted: Human-readable uptime string
        """
        uptime_seconds = time.time() - self.start_time
        
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        
        if days > 0:
            formatted = f"{days}d {hours}h {minutes}m {seconds}s"
        elif hours > 0:
            formatted = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            formatted = f"{minutes}m {seconds}s"
        else:
            formatted = f"{seconds}s"
        
        return {
            'seconds': int(uptime_seconds),
            'formatted': formatted
        }
    
    def trigger_gc(self):
        """
        Manually trigger garbage collection and track statistics.
        
        Returns:
            dict: GC statistics with keys:
                - freed: Bytes freed by collection
                - time_ms: Time taken for collection in milliseconds
        """
        mem_before = gc.mem_free()
        start_time = time.ticks_us()
        
        gc.collect()
        
        elapsed_us = time.ticks_diff(time.ticks_us(), start_time)
        mem_after = gc.mem_free()
        freed = mem_after - mem_before
        
        self.gc_count += 1
        self.last_gc_time = time.time()
        
        return {
            'freed': freed,
            'time_ms': elapsed_us / 1000.0,
            'total_collections': self.gc_count
        }
    
    def get_gc_stats(self):
        """
        Get garbage collection statistics.
        
        Returns:
            dict: GC statistics
        """
        time_since_gc = time.time() - self.last_gc_time
        
        return {
            'total_collections': self.gc_count,
            'time_since_last_gc': round(time_since_gc, 1),
            'last_gc_time': self.last_gc_time
        }
    
    def record_sensor_reading(self, sensor_id, duration_ms, success=True):
        """
        Record a sensor reading for statistics.
        
        Args:
            sensor_id: Sensor identifier
            duration_ms: Time taken for reading in milliseconds
            success: Whether the reading was successful
        """
        if sensor_id not in self.sensor_stats:
            self.sensor_stats[sensor_id] = {
                'total_readings': 0,
                'successful_readings': 0,
                'failed_readings': 0,
                'total_time_ms': 0,
                'avg_time_ms': 0,
                'min_time_ms': float('inf'),
                'max_time_ms': 0
            }
        
        stats = self.sensor_stats[sensor_id]
        stats['total_readings'] += 1
        
        if success:
            stats['successful_readings'] += 1
            stats['total_time_ms'] += duration_ms
            stats['avg_time_ms'] = stats['total_time_ms'] / stats['successful_readings']
            
            if duration_ms < stats['min_time_ms']:
                stats['min_time_ms'] = duration_ms
            if duration_ms > stats['max_time_ms']:
                stats['max_time_ms'] = duration_ms
        else:
            stats['failed_readings'] += 1
    
    def record_algorithm_execution(self, algo_id, duration_ms, triggered=False):
        """
        Record an algorithm execution for statistics.
        
        Args:
            algo_id: Algorithm identifier
            duration_ms: Time taken for execution in milliseconds
            triggered: Whether the algorithm triggered
        """
        if algo_id not in self.algorithm_stats:
            self.algorithm_stats[algo_id] = {
                'total_executions': 0,
                'total_triggers': 0,
                'total_time_ms': 0,
                'avg_time_ms': 0,
                'min_time_ms': float('inf'),
                'max_time_ms': 0
            }
        
        stats = self.algorithm_stats[algo_id]
        stats['total_executions'] += 1
        stats['total_time_ms'] += duration_ms
        stats['avg_time_ms'] = stats['total_time_ms'] / stats['total_executions']
        
        if triggered:
            stats['total_triggers'] += 1
        
        if duration_ms < stats['min_time_ms']:
            stats['min_time_ms'] = duration_ms
        if duration_ms > stats['max_time_ms']:
            stats['max_time_ms'] = duration_ms
    
    def get_sensor_stats(self, sensor_id=None):
        """
        Get sensor statistics.
        
        Args:
            sensor_id: Specific sensor ID, or None for all sensors
        
        Returns:
            dict: Sensor statistics
        """
        if sensor_id:
            return self.sensor_stats.get(sensor_id, {})
        return self.sensor_stats.copy()
    
    def get_algorithm_stats(self, algo_id=None):
        """
        Get algorithm statistics.
        
        Args:
            algo_id: Specific algorithm ID, or None for all algorithms
        
        Returns:
            dict: Algorithm statistics
        """
        if algo_id:
            return self.algorithm_stats.get(algo_id, {})
        return self.algorithm_stats.copy()
    
    def get_summary(self):
        """
        Get a complete system summary.
        
        Returns:
            dict: Complete system statistics
        """
        memory = self.get_memory_info()
        uptime = self.get_uptime()
        gc_stats = self.get_gc_stats()
        
        return {
            'uptime': uptime,
            'memory': memory,
            'gc': gc_stats,
            'sensors': {
                'count': len(self.sensor_stats),
                'total_readings': sum(s['total_readings'] for s in self.sensor_stats.values()),
                'stats': self.sensor_stats
            },
            'algorithms': {
                'count': len(self.algorithm_stats),
                'total_executions': sum(a['total_executions'] for a in self.algorithm_stats.values()),
                'total_triggers': sum(a['total_triggers'] for a in self.algorithm_stats.values()),
                'stats': self.algorithm_stats
            },
            'lora_messages': self.get_lora_messages()
        }
    
    def print_summary(self):
        """Print a formatted system summary to console."""
        summary = self.get_summary()
        
        print("\n" + "=" * 60)
        print("SYSTEM MONITOR SUMMARY")
        print("=" * 60)
        
        # Uptime
        print(f"\nUptime: {summary['uptime']['formatted']}")
        
        # Memory
        mem = summary['memory']
        print(f"\nMemory:")
        print(f"  Free: {mem['free']:,} bytes ({100 - mem['used_percent']:.1f}%)")
        print(f"  Used: {mem['allocated']:,} bytes ({mem['used_percent']:.1f}%)")
        print(f"  Total: {mem['total']:,} bytes")
        print(f"  Peak Used: {mem['peak_used']:,} bytes")
        print(f"  Min Free: {mem['min_free']:,} bytes")
        
        # Garbage Collection
        gc = summary['gc']
        print(f"\nGarbage Collection:")
        print(f"  Total Collections: {gc['total_collections']}")
        print(f"  Time Since Last: {gc['time_since_last_gc']:.1f}s")
        
        # Sensors
        sensors = summary['sensors']
        print(f"\nSensors ({sensors['count']} active):")
        print(f"  Total Readings: {sensors['total_readings']}")
        for sensor_id, stats in sensors['stats'].items():
            success_rate = (stats['successful_readings'] / stats['total_readings'] * 100) if stats['total_readings'] > 0 else 0
            print(f"  {sensor_id}:")
            print(f"    Readings: {stats['total_readings']} (success: {success_rate:.1f}%)")
            if stats['successful_readings'] > 0:
                print(f"    Avg Time: {stats['avg_time_ms']:.2f}ms")
        
        # Algorithms
        algos = summary['algorithms']
        print(f"\nAlgorithms ({algos['count']} active):")
        print(f"  Total Executions: {algos['total_executions']}")
        print(f"  Total Triggers: {algos['total_triggers']}")
        for algo_id, stats in algos['stats'].items():
            trigger_rate = (stats['total_triggers'] / stats['total_executions'] * 100) if stats['total_executions'] > 0 else 0
            print(f"  {algo_id}:")
            print(f"    Executions: {stats['total_executions']} (triggers: {trigger_rate:.1f}%)")
            print(f"    Avg Time: {stats['avg_time_ms']:.2f}ms")
        
        print("=" * 60 + "\n")


# Global instance
_monitor = None

def get_monitor():
    """Get the global SystemMonitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor()
    return _monitor


# Made with Bob