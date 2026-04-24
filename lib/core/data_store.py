"""
DataStore - Central data storage with shared frame semantics for sensor data

Provides memory-efficient storage for sensor readings with shared frame access.
Multiple algorithms can consume the same frame without duplication.
Frames are released/reused once all registered consumers have processed them.
"""

import asyncio
import time
from utils.logger import debug_print


class DataStore:
    """
    Central data store with shared frame semantics.
    
    Each sensor has a bounded pool of frames that are shared among
    registered algorithm consumers. Frames are reused once all consumers
    have acknowledged consumption.
    """
    
    def __init__(self):
        """Initialize the data store"""
        self.sensors = {}
        self.lock = asyncio.Lock()
    
    def register_sensor(self, sensor_id, buffer_size):
        """
        Register a new sensor with its frame pool.
        
        Args:
            sensor_id: Unique identifier for the sensor
            buffer_size: Maximum number of frames in the pool
        """
        self.sensors[sensor_id] = {
            'frames': [],  # Pool of frame objects
            'buffer_size': buffer_size,
            'write_index': 0,  # Next frame to write
            'frame_sequence': 0,  # Monotonic frame counter
            'consumers': {},  # {consumer_id: last_consumed_sequence}
            'is_full': False
        }
        print(f"[DataStore] Registered sensor '{sensor_id}' with frame pool size {buffer_size}")
    
    def register_consumer(self, sensor_id, consumer_id):
        """
        Register an algorithm as a consumer of sensor frames.
        
        Args:
            sensor_id: Sensor to consume from
            consumer_id: Unique identifier for the consumer (algorithm)
        """
        if sensor_id not in self.sensors:
            print(f"[DataStore] ERROR: Cannot register consumer '{consumer_id}' - sensor '{sensor_id}' not found")
            return
        
        sensor = self.sensors[sensor_id]
        sensor['consumers'][consumer_id] = -1  # Start before any frames
        print(f"[DataStore] Registered consumer '{consumer_id}' for sensor '{sensor_id}'")
    
    async def add_data(self, sensor_id, timestamp, value):
        """
        Add a new data frame to sensor's pool.
        
        Frames are stored in a bounded pool and reused once all consumers
        have processed them. This avoids memory duplication.
        
        Args:
            sensor_id: Sensor identifier
            timestamp: Unix timestamp of the reading
            value: Sensor value (float or int) or dict with 'value' and 'raw_samples'
        """
        debug_print("[DATASTORE]", f"[{sensor_id}] add_data() called")
        debug_print("[DATASTORE]", f"[{sensor_id}]   timestamp: {timestamp}")
        debug_print("[DATASTORE]", f"[{sensor_id}]   value type: {type(value).__name__}")
        
        async with self.lock:
            debug_print("[DATASTORE]", f"[{sensor_id}] Lock acquired")
            
            if sensor_id not in self.sensors:
                print(f"[DATASTORE] [{sensor_id}] ✗ ERROR: Sensor not registered!")
                return
            
            sensor = self.sensors[sensor_id]
            sequence = sensor['frame_sequence']
            sensor['frame_sequence'] += 1
            
            debug_print("[DATASTORE]", f"[{sensor_id}] Frame sequence: {sequence}")
            debug_print("[DATASTORE]", f"[{sensor_id}]   pool_size: {sensor['buffer_size']}")
            debug_print("[DATASTORE]", f"[{sensor_id}]   current_count: {len(sensor['frames'])}")
            
            # Create frame object
            frame = {
                'sequence': sequence,
                'timestamp': timestamp,
                'value': value,
                'consumed_by': set()  # Track which consumers have processed this
            }
            
            # If pool not full, append new frame
            if not sensor['is_full']:
                debug_print("[DATASTORE]", f"[{sensor_id}] Pool not full, appending frame {sequence}")
                sensor['frames'].append(frame)
                
                if len(sensor['frames']) >= sensor['buffer_size']:
                    sensor['is_full'] = True
                    sensor['write_index'] = 0
                    debug_print("[DATASTORE]", f"[{sensor_id}] Pool now full, switching to reuse mode")
            else:
                # Reuse oldest frame slot (ring buffer semantics)
                idx = sensor['write_index']
                old_frame = sensor['frames'][idx]
                debug_print("[DATASTORE]", f"[{sensor_id}] Reusing frame slot {idx} (was seq {old_frame['sequence']})")
                
                # Check if all consumers have processed the old frame
                consumers = set(sensor['consumers'].keys())
                unconsumed = consumers - old_frame['consumed_by']
                if unconsumed:
                    debug_print("[DATASTORE]", f"[{sensor_id}] WARNING: Frame {old_frame['sequence']} not consumed by: {unconsumed}")
                
                # Overwrite with new frame
                sensor['frames'][idx] = frame
                sensor['write_index'] = (sensor['write_index'] + 1) % sensor['buffer_size']
            
            debug_print("[DATASTORE]", f"[{sensor_id}] ✓ Frame {sequence} added successfully")
    
    async def get_next_frame(self, sensor_id, consumer_id):
        """
        Get the next unconsumed frame for a consumer.
        
        Returns the oldest frame that this consumer hasn't processed yet.
        Does NOT copy the frame - returns a reference for shared access.
        
        Args:
            sensor_id: Sensor identifier
            consumer_id: Consumer (algorithm) identifier
            
        Returns:
            Frame dict with 'sequence', 'timestamp', 'value', or None if no new frames
        """
        async with self.lock:
            if sensor_id not in self.sensors:
                return None
            
            sensor = self.sensors[sensor_id]
            if consumer_id not in sensor['consumers']:
                debug_print("[DATASTORE]", f"[{sensor_id}] Consumer '{consumer_id}' not registered")
                return None
            
            if not sensor['frames']:
                return None
            
            last_consumed = sensor['consumers'][consumer_id]
            
            # Find oldest unconsumed frame
            for frame in sensor['frames']:
                if frame['sequence'] > last_consumed:
                    debug_print("[DATASTORE]", f"[{sensor_id}] Consumer '{consumer_id}' fetching frame {frame['sequence']}")
                    return frame  # Return reference, not copy
            
            return None
    
    async def release_frame(self, sensor_id, consumer_id, sequence):
        """
        Mark a frame as consumed by a consumer.
        
        Once all registered consumers have released a frame, it can be reused.
        
        Args:
            sensor_id: Sensor identifier
            consumer_id: Consumer (algorithm) identifier
            sequence: Frame sequence number to release
        """
        async with self.lock:
            if sensor_id not in self.sensors:
                return
            
            sensor = self.sensors[sensor_id]
            if consumer_id not in sensor['consumers']:
                return
            
            # Update consumer's last consumed sequence
            sensor['consumers'][consumer_id] = sequence
            
            # Mark frame as consumed by this consumer
            for frame in sensor['frames']:
                if frame['sequence'] == sequence:
                    frame['consumed_by'].add(consumer_id)
                    debug_print("[DATASTORE]", f"[{sensor_id}] Frame {sequence} released by '{consumer_id}'")
                    
                    # Check if all consumers have processed this frame
                    all_consumers = set(sensor['consumers'].keys())
                    if frame['consumed_by'] == all_consumers:
                        debug_print("[DATASTORE]", f"[{sensor_id}] Frame {sequence} fully consumed by all consumers")
                    break
    
    async def get_latest(self, sensor_id):
        """
        Get the most recent frame for a sensor (legacy compatibility).
        
        Returns a COPY for backward compatibility with existing code.
        New code should use get_next_frame() instead.
        
        Args:
            sensor_id: Sensor identifier
            
        Returns:
            dict with 'timestamp' and 'value' keys, or None if no data
        """
        async with self.lock:
            if sensor_id not in self.sensors:
                return None
            
            sensor = self.sensors[sensor_id]
            if not sensor['frames']:
                return None
            
            # Find frame with highest sequence
            latest = max(sensor['frames'], key=lambda f: f['sequence'])
            return {
                'timestamp': latest['timestamp'],
                'value': latest['value']
            }
    
    async def get_window(self, sensor_id, count):
        """
        Get the last N frames for a sensor (legacy compatibility).
        
        Returns COPIES for backward compatibility.
        New code should use get_next_frame() instead.
        
        Args:
            sensor_id: Sensor identifier
            count: Number of most recent values to retrieve
            
        Returns:
            list of dicts with 'timestamp' and 'value' keys, ordered oldest to newest
        """
        async with self.lock:
            if sensor_id not in self.sensors:
                return []
            
            sensor = self.sensors[sensor_id]
            if not sensor['frames']:
                return []
            
            # Sort frames by sequence and take last N
            sorted_frames = sorted(sensor['frames'], key=lambda f: f['sequence'])
            recent = sorted_frames[-count:] if count < len(sorted_frames) else sorted_frames
            
            return [{'timestamp': f['timestamp'], 'value': f['value']} for f in recent]
    
    def get_sensor_info(self, sensor_id):
        """
        Get information about a sensor's frame pool.
        
        Args:
            sensor_id: Sensor identifier
            
        Returns:
            dict with pool statistics or None
        """
        if sensor_id not in self.sensors:
            return None
        
        sensor = self.sensors[sensor_id]
        return {
            'buffer_size': sensor['buffer_size'],
            'current_count': len(sensor['frames']),
            'is_full': sensor['is_full'],
            'frame_sequence': sensor['frame_sequence'],
            'consumers': list(sensor['consumers'].keys())
        }

# Made with Bob
