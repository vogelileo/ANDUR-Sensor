# MicroPython Sensor System Architecture

**Pico2W Multi-Sensor LoRa Project**

## 1. System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Application                          │
│                      (main.py + asyncio)                         │
└────────────┬────────────────────────────────────────────────────┘
             │
             ├──────────────────────────────────────────────────────┐
             │                                                      │
             v                                                      v
┌────────────────────────┐                          ┌──────────────────────┐
│   Sensor Manager       │                          │  Algorithm Manager   │
│   (sensor_manager.py)  │                          │  (algo_manager.py)   │
└────────┬───────────────┘                          └──────────┬───────────┘
         │                                                     │
         │ updates                                             │ reads
         v                                                     v
┌─────────────────────────────────────────────────────────────────┐
│                    Shared Data Store                             │
│                   (data_store.py)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Sensor A     │  │ Sensor B     │  │ Sensor C     │          │
│  │ Ring Buffer  │  │ Ring Buffer  │  │ Ring Buffer  │          │
│  │ (N values)   │  │ (N values)   │  │ (N values)   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    │ triggers on threshold
                                    v
                          ┌──────────────────┐
                          │   LoRa Interface │
                          │   (lora.py)      │
                          └──────────────────┘
                                    │
                                    v
                          [ LoRa Transmission ]
```

### Component Responsibilities

| Component             | Responsibility                                                       |
| --------------------- | -------------------------------------------------------------------- |
| **Main Application**  | Initialize system, start asyncio event loop, coordinate components   |
| **Sensor Manager**    | Manage sensor lifecycle, schedule sensor readings, update data store |
| **Data Store**        | Central storage with ring buffers per sensor, thread-safe access     |
| **Algorithm Manager** | Run algorithm instances, consume from data store, trigger LoRa       |
| **LoRa Interface**    | Send formatted payloads via LoRa (stub for now)                      |
| **Configuration**     | Load and validate system configuration                               |

---

## 2. Detailed Component Design

### 2.1 Data Store (`data_store.py`)

**Purpose**: Central, shared storage for all sensor data with efficient ring buffers.

**Key Features**:

- One ring buffer per sensor (identified by sensor_id)
- Configurable buffer size per sensor (number of values to store)
- Automatic old data eviction
- Thread-safe access (using asyncio locks)
- Timestamp-based storage

**Data Structure**:

```python
{
    "sensor_id": {
        "type": "magnetic",           # Sensor type
        "buffer": [                   # Ring buffer (fixed size)
            {
                "timestamp": 1234567890,
                "value": 42.5
            },
            ...
        ],
        "current_index": 0,           # Current write position
        "buffer_size": 12000,         # Max entries (configured per sensor)
        "last_update": 1234567890     # Last update timestamp
    }
}
```

**API**:

```python
class DataStore:
    def register_sensor(sensor_id, sensor_type, buffer_size)
    def update_sensor(sensor_id, value, timestamp)
    def get_latest(sensor_id) -> dict
    def get_history(sensor_id, duration_seconds) -> list
    def get_all_latest() -> dict
```

### 2.2 Sensor Base Class (`sensors/base_sensor.py`)

**Purpose**: Abstract base class for all sensor implementations.

**Key Features**:

- Defines sensor interface
- Handles self-scheduling via asyncio
- Updates data store independently
- Configurable update frequency

**Interface**:

```python
class BaseSensor:
    def __init__(self, sensor_id, config, data_store):
        self.sensor_id = sensor_id
        self.config = config
        self.data_store = data_store
        self.update_interval = config.get('update_interval', 1.0)

    async def initialize(self):
        """Initialize hardware/sensor"""
        pass

    async def read_value(self):
        """Read sensor value - MUST be implemented by subclass"""
        raise NotImplementedError

    async def run(self):
        """Main sensor loop - reads and updates data store"""
        await self.initialize()
        while True:
            value = await self.read_value()
            timestamp = time.time()
            self.data_store.update_sensor(self.sensor_id, value, timestamp)
            await asyncio.sleep(self.update_interval)
```

### 2.3 Algorithm Base Class (`algorithms/base_algorithm.py`)

**Purpose**: Abstract base class for all algorithm implementations.

**Key Features**:

- Two modes: Event-based (single value) and Window-based (history)
- Configurable execution frequency
- Triggers LoRa on threshold detection
- Each instance is independent (multiple instances of same algorithm allowed)

**Interface**:

```python
class BaseAlgorithm:
    def __init__(self, algo_id, sensor_id, config, data_store, lora_interface):
        self.algo_id = algo_id
        self.sensor_id = sensor_id
        self.config = config
        self.data_store = data_store
        self.lora_interface = lora_interface
        self.check_interval = config.get('check_interval', 1.0)
        self.mode = config.get('mode', 'event')  # 'event' or 'window'

    async def process_event(self, value, timestamp):
        """Process single value - for event-based algorithms"""
        raise NotImplementedError

    async def process_window(self, history):
        """Process time window - for window-based algorithms"""
        raise NotImplementedError

    async def run(self):
        """Main algorithm loop"""
        while True:
            if self.mode == 'event':
                data = self.data_store.get_latest(self.sensor_id)
                if data:
                    result = await self.process_event(data['value'], data['timestamp'])
            else:  # window mode
                history = self.data_store.get_history(
                    self.sensor_id,
                    self.config.get('window_duration', 60)
                )
                result = await self.process_window(history)

            if result and result['trigger']:
                await self.trigger_lora(result)

            await asyncio.sleep(self.check_interval)

    async def trigger_lora(self, result):
        """Send LoRa message"""
        payload = {
            'sensor_type': self.data_store.get_sensor_type(self.sensor_id),
            'algo_type': self.config['type'],
            'value': int(result['value'])  # 0-10000
        }
        await self.lora_interface.send(payload)
```

### 2.4 Sensor Manager (`sensor_manager.py`)

**Purpose**: Manage all sensor instances and their lifecycle.

**Key Features**:

- Load sensor configurations
- Instantiate sensor objects
- Start all sensors concurrently using asyncio
- Handle sensor errors gracefully

**API**:

```python
class SensorManager:
    def __init__(self, config, data_store):
        self.config = config
        self.data_store = data_store
        self.sensors = []

    def load_sensors(self):
        """Load and instantiate sensors from config"""
        for sensor_config in self.config['sensors']:
            sensor_class = self._get_sensor_class(sensor_config['type'])
            sensor = sensor_class(
                sensor_config['id'],
                sensor_config,
                self.data_store
            )
            self.sensors.append(sensor)

    async def start_all(self):
        """Start all sensors concurrently"""
        tasks = [sensor.run() for sensor in self.sensors]
        await asyncio.gather(*tasks)
```

### 2.5 Algorithm Manager (`algo_manager.py`)

**Purpose**: Manage all algorithm instances and their lifecycle.

**Key Features**:

- Load algorithm configurations
- Instantiate algorithm objects (multiple instances allowed)
- Start all algorithms concurrently using asyncio
- Handle algorithm errors gracefully

**API**:

```python
class AlgorithmManager:
    def __init__(self, config, data_store, lora_interface):
        self.config = config
        self.data_store = data_store
        self.lora_interface = lora_interface
        self.algorithms = []

    def load_algorithms(self):
        """Load and instantiate algorithms from config"""
        for algo_config in self.config['algorithms']:
            algo_class = self._get_algorithm_class(algo_config['type'])
            algo = algo_class(
                algo_config['id'],
                algo_config['sensor_id'],
                algo_config,
                self.data_store,
                self.lora_interface
            )
            self.algorithms.append(algo)

    async def start_all(self):
        """Start all algorithms concurrently"""
        tasks = [algo.run() for algo in self.algorithms]
        await asyncio.gather(*tasks)
```

### 2.6 LoRa Interface (`lora.py`)

**Purpose**: Handle LoRa communication (stub for now).

**Key Features**:

- Format payload according to spec
- Send via LoRa hardware

**API**:

```python
class LoRaInterface:
    def __init__(self, config):
        self.config = config
        # TODO: Initialize LoRa hardware

    async def send(self, payload):
        """
        Send LoRa message

        Payload format:
        {
            'sensor_type': str,    # e.g., 'magnetic', 'temperature'
            'algo_type': str,      # e.g., 'threshold', 'moving_avg'
            'value': int           # 0-10000
        }

        TODO: Implement actual LoRa transmission
        """
        print(f"[LoRa] Sending: {payload}")
        # Placeholder for actual LoRa transmission
        pass
```

---

## 3. Data Flow

### 3.1 Sensor Data Flow

```
1. Sensor reads hardware
   └─> sensor.read_value()

2. Sensor updates data store
   └─> data_store.update_sensor(sensor_id, value, timestamp)

3. Data store writes to ring buffer
   └─> Overwrites oldest entry if buffer full
   └─> Updates last_update timestamp

4. Data available for algorithms
   └─> Algorithms read via get_latest() or get_history()
```

### 3.2 Algorithm Processing Flow

```
1. Algorithm wakes up (based on check_interval)
   └─> asyncio.sleep(check_interval)

2. Algorithm reads from data store
   ├─> Event mode: get_latest(sensor_id)
   └─> Window mode: get_history(sensor_id, duration)

3. Algorithm processes data
   ├─> Event mode: process_event(value, timestamp)
   └─> Window mode: process_window(history)

4. If threshold met, trigger LoRa
   └─> lora_interface.send(payload)

5. Repeat from step 1
```

### 3.3 Parallel Execution Model

```
Main Event Loop (asyncio)
├─> Sensor A Task (runs independently)
├─> Sensor B Task (runs independently)
├─> Algorithm 1 Task (runs independently)
├─> Algorithm 2 Task (runs independently)
└─> Algorithm 3 Task (runs independently)

All tasks run concurrently via asyncio.gather()
Data store provides thread-safe access
```

---

## 4. File Structure

```
project_root/
│
├── main.py                      # Entry point, asyncio setup
├── config.json                  # System configuration
│
├── core/
│   ├── __init__.py
│   ├── data_store.py           # Shared data store with ring buffers
│   ├── sensor_manager.py       # Sensor lifecycle management
│   └── algo_manager.py         # Algorithm lifecycle management
│
├── sensors/
│   ├── __init__.py
│   ├── base_sensor.py          # Abstract sensor base class
│   ├── magnetic_sensor.py      # Example: Magnetic sensor implementation
│   └── temperature_sensor.py   # Example: Temperature sensor implementation
│
├── algorithms/
│   ├── __init__.py
│   ├── base_algorithm.py       # Abstract algorithm base class
│   ├── threshold_detector.py   # Example: Simple threshold algorithm
│   └── moving_average.py       # Example: Moving average algorithm
│
├── communication/
│   ├── __init__.py
│   └── lora.py                 # LoRa interface (stub)
│
└── utils/
    ├── __init__.py
    └── config_loader.py        # Configuration loading and validation
```

### File Responsibilities

| File                                                                   | Responsibility                                         |
| ---------------------------------------------------------------------- | ------------------------------------------------------ |
| [`main.py`](main.py)                                                   | Initialize components, start asyncio event loop        |
| [`config.json`](config.json)                                           | System configuration (sensors, algorithms, parameters) |
| [`core/data_store.py`](core/data_store.py)                             | Central data storage with ring buffers                 |
| [`core/sensor_manager.py`](core/sensor_manager.py)                     | Manage sensor instances and lifecycle                  |
| [`core/algo_manager.py`](core/algo_manager.py)                         | Manage algorithm instances and lifecycle               |
| [`sensors/base_sensor.py`](sensors/base_sensor.py)                     | Abstract base class for sensors                        |
| [`sensors/magnetic_sensor.py`](sensors/magnetic_sensor.py)             | Concrete magnetic sensor implementation                |
| [`algorithms/base_algorithm.py`](algorithms/base_algorithm.py)         | Abstract base class for algorithms                     |
| [`algorithms/threshold_detector.py`](algorithms/threshold_detector.py) | Concrete threshold detection algorithm                 |
| [`communication/lora.py`](communication/lora.py)                       | LoRa communication interface                           |
| [`utils/config_loader.py`](utils/config_loader.py)                     | Load and validate configuration                        |

---

## 5. Configuration System

### 5.1 Configuration File (`config.json`)

```json
{
  "system": {
    "name": "MicroPython Sensor System",
    "version": "1.0.0"
  },

  "sensors": [
    {
      "id": "mag_sensor_1",
      "type": "magnetic",
      "enabled": true,
      "update_interval": 0.01,
      "buffer_size": 12000,
      "hardware": {
        "i2c_address": "0x1E",
        "pin_sda": 0,
        "pin_scl": 1
      }
    },
    {
      "id": "temp_sensor_1",
      "type": "temperature",
      "enabled": true,
      "update_interval": 1.0,
      "buffer_size": 120,
      "hardware": {
        "pin": 26
      }
    }
  ],

  "algorithms": [
    {
      "id": "mag_threshold_high",
      "type": "threshold",
      "sensor_id": "mag_sensor_1",
      "enabled": true,
      "mode": "event",
      "check_interval": 0.1,
      "parameters": {
        "threshold": 500,
        "direction": "above"
      }
    },
    {
      "id": "mag_threshold_low",
      "type": "threshold",
      "sensor_id": "mag_sensor_1",
      "enabled": true,
      "mode": "event",
      "check_interval": 0.1,
      "parameters": {
        "threshold": 100,
        "direction": "below"
      }
    },
    {
      "id": "mag_moving_avg",
      "type": "moving_average",
      "sensor_id": "mag_sensor_1",
      "enabled": true,
      "mode": "window",
      "check_interval": 1.0,
      "window_duration": 10,
      "parameters": {
        "threshold_deviation": 50
      }
    },
    {
      "id": "temp_threshold",
      "type": "threshold",
      "sensor_id": "temp_sensor_1",
      "enabled": true,
      "mode": "event",
      "check_interval": 1.0,
      "parameters": {
        "threshold": 30,
        "direction": "above"
      }
    }
  ],

  "lora": {
    "enabled": true,
    "frequency": 868000000,
    "tx_power": 14,
    "spreading_factor": 7,
    "bandwidth": 125000
  }
}
```

### 5.2 Configuration Loading

```python
# utils/config_loader.py
import json

class ConfigLoader:
    @staticmethod
    def load(config_path='config.json'):
        """Load and validate configuration"""
        with open(config_path, 'r') as f:
            config = json.load(f)

        ConfigLoader._validate(config)
        return config

    @staticmethod
    def _validate(config):
        """Validate configuration structure"""
        required_keys = ['sensors', 'algorithms', 'lora']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required config key: {key}")

        # Validate sensor configs
        for sensor in config['sensors']:
            if 'id' not in sensor or 'type' not in sensor:
                raise ValueError("Sensor config missing 'id' or 'type'")

        # Validate algorithm configs
        for algo in config['algorithms']:
            if 'id' not in algo or 'sensor_id' not in algo:
                raise ValueError("Algorithm config missing 'id' or 'sensor_id'")
```

---

## 6. Example Implementations

### 6.1 Example Sensor: Magnetic Sensor

```python
# sensors/magnetic_sensor.py
from sensors.base_sensor import BaseSensor
import machine
import time

class MagneticSensor(BaseSensor):
    """
    Example magnetic sensor implementation
    Reads from I2C-based magnetometer
    """

    async def initialize(self):
        """Initialize I2C and magnetometer"""
        i2c_address = int(self.config['hardware']['i2c_address'], 16)
        pin_sda = self.config['hardware']['pin_sda']
        pin_scl = self.config['hardware']['pin_scl']

        self.i2c = machine.I2C(0, scl=machine.Pin(pin_scl), sda=machine.Pin(pin_sda))

        # Initialize magnetometer (example)
        # self.i2c.writeto(i2c_address, b'\x00\x70')  # Config register

        print(f"[{self.sensor_id}] Magnetic sensor initialized")

    async def read_value(self):
        """
        Read magnetic field strength
        Returns: float (magnetic field in µT)
        """
        # Example: Read from magnetometer registers
        # In real implementation, read actual I2C data

        # Simulated reading for example
        import random
        value = 200 + random.randint(-50, 50)

        return float(value)
```

### 6.2 Example Algorithm: Threshold Detector

```python
# algorithms/threshold_detector.py
from algorithms.base_algorithm import BaseAlgorithm

class ThresholdDetector(BaseAlgorithm):
    """
    Simple threshold detection algorithm
    Triggers when value crosses threshold
    """

    def __init__(self, algo_id, sensor_id, config, data_store, lora_interface):
        super().__init__(algo_id, sensor_id, config, data_store, lora_interface)
        self.threshold = config['parameters']['threshold']
        self.direction = config['parameters']['direction']  # 'above' or 'below'
        self.last_state = None

    async def process_event(self, value, timestamp):
        """
        Check if value crosses threshold
        Returns: dict with 'trigger' and 'value' keys
        """
        triggered = False

        if self.direction == 'above':
            current_state = value > self.threshold
        else:  # below
            current_state = value < self.threshold

        # Trigger on state change (edge detection)
        if self.last_state is not None and current_state and not self.last_state:
            triggered = True

        self.last_state = current_state

        if triggered:
            # Normalize value to 0-10000 range
            normalized_value = int((value / 1000.0) * 10000)
            normalized_value = max(0, min(10000, normalized_value))

            return {
                'trigger': True,
                'value': normalized_value,
                'raw_value': value,
                'timestamp': timestamp
            }

        return {'trigger': False}

    async def process_window(self, history):
        """Not used for threshold detector (event-based only)"""
        raise NotImplementedError("Threshold detector is event-based only")
```

### 6.3 Example Algorithm: Moving Average

```python
# algorithms/moving_average.py
from algorithms.base_algorithm import BaseAlgorithm

class MovingAverage(BaseAlgorithm):
    """
    Moving average algorithm with deviation detection
    Triggers when current value deviates significantly from moving average
    """

    def __init__(self, algo_id, sensor_id, config, data_store, lora_interface):
        super().__init__(algo_id, sensor_id, config, data_store, lora_interface)
        self.threshold_deviation = config['parameters']['threshold_deviation']

    async def process_event(self, value, timestamp):
        """Not used for moving average (window-based only)"""
        raise NotImplementedError("Moving average is window-based only")

    async def process_window(self, history):
        """
        Calculate moving average and check for deviation
        Returns: dict with 'trigger' and 'value' keys
        """
        if len(history) < 2:
            return {'trigger': False}

        # Calculate moving average (excluding most recent value)
        values = [entry['value'] for entry in history[:-1]]
        avg = sum(values) / len(values)

        # Get current value
        current_value = history[-1]['value']

        # Check deviation
        deviation = abs(current_value - avg)

        if deviation > self.threshold_deviation:
            # Normalize deviation to 0-10000 range
            normalized_value = int((deviation / 1000.0) * 10000)
            normalized_value = max(0, min(10000, normalized_value))

            return {
                'trigger': True,
                'value': normalized_value,
                'raw_value': current_value,
                'average': avg,
                'deviation': deviation,
                'timestamp': history[-1]['timestamp']
            }

        return {'trigger': False}
```

### 6.4 Main Application

```python
# main.py
import asyncio
from utils.config_loader import ConfigLoader
from core.data_store import DataStore
from core.sensor_manager import SensorManager
from core.algo_manager import AlgorithmManager
from communication.lora import LoRaInterface

async def main():
    """Main application entry point"""
    print("Starting MicroPython Sensor System...")

    # Load configuration
    config = ConfigLoader.load('config.json')

    # Initialize components
    data_store = DataStore(config['data_store'])
    lora_interface = LoRaInterface(config['lora'])

    sensor_manager = SensorManager(config, data_store)
    algo_manager = AlgorithmManager(config, data_store, lora_interface)

    # Load sensors and algorithms
    sensor_manager.load_sensors()
    algo_manager.load_algorithms()

    # Register sensors in data store
    for sensor in sensor_manager.sensors:
        buffer_size = sensor.config.get('buffer_size', 120)
        data_store.register_sensor(
            sensor.sensor_id,
            sensor.config['type'],
            buffer_size
        )

    print(f"Loaded {len(sensor_manager.sensors)} sensors")
    print(f"Loaded {len(algo_manager.algorithms)} algorithms")

    # Start all components concurrently
    try:
        await asyncio.gather(
            sensor_manager.start_all(),
            algo_manager.start_all()
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")

# Run the application
if __name__ == '__main__':
    asyncio.run(main())
```

---

## 7. MicroPython Constraints & Considerations

### 7.1 Memory Management

- **Ring Buffers**: Fixed-size circular buffers prevent unbounded memory growth
- **Buffer Size Configuration**: Each sensor specifies `buffer_size` (number of values to store)
  - Example 1: Magnetic sensor @ 100Hz with buffer_size=12000 → 2 minutes of data
  - Example 2: Temperature sensor @ 1Hz with buffer_size=120 → 2 minutes of data
  - Each entry ~20 bytes → Fast sensor (12000 entries) = ~240KB, Slow sensor (120 entries) = ~2.4KB
- **Memory Scaling**: Fast sensors (100Hz-1kHz) require larger buffers but provide high-resolution data
- **Garbage Collection**: Explicitly call `gc.collect()` periodically if needed

### 7.2 Asyncio Usage

- **No Threading**: MicroPython has limited threading support
- **Cooperative Multitasking**: Use `await asyncio.sleep()` to yield control
- **Task Management**: Use `asyncio.gather()` to run tasks concurrently
- **Error Handling**: Wrap tasks in try-except to prevent one failure from stopping all

### 7.3 Performance Optimization

- **Minimize Allocations**: Reuse objects where possible
- **Efficient Data Structures**: Use lists for ring buffers (fast indexing)
- **Avoid Blocking**: Never use `time.sleep()`, always use `await asyncio.sleep()`
- **I2C/SPI Speed**: Configure appropriate bus speeds for sensors

### 7.4 Power Considerations

- **Sleep Modes**: Consider deep sleep between readings if battery-powered
- **Sensor Power**: Power down sensors when not reading if possible
- **High-Frequency Sensors**: Fast sampling (100Hz+) increases power consumption significantly

---

## 8. Extension Points

### 8.1 Adding New Sensors

1. Create new file in `sensors/` directory
2. Inherit from `BaseSensor`
3. Implement `initialize()` and `read_value()` methods
4. Add sensor configuration to `config.json`
5. Register sensor class in `sensor_manager.py`

### 8.2 Adding New Algorithms

1. Create new file in `algorithms/` directory
2. Inherit from `BaseAlgorithm`
3. Implement `process_event()` or `process_window()` (or both)
4. Add algorithm configuration to `config.json`
5. Register algorithm class in `algo_manager.py`

### 8.3 Adding New Communication Protocols

1. Create new file in `communication/` directory
2. Implement similar interface to `LoRaInterface`
3. Update algorithm base class to support multiple communication methods
4. Add configuration options

---

## 9. Deployment Checklist

- [ ] Configure `config.json` for target hardware
- [ ] Test all sensors individually
- [ ] Test all algorithms with recorded data
- [ ] Verify LoRa transmission (when implemented)
- [ ] Test system for 24+ hours
- [ ] Measure power consumption
- [ ] Document any hardware-specific quirks
- [ ] Create backup/recovery procedure

---

## 10. Future Enhancements

1. **Data Persistence**: Save data to flash for recovery after reboot
2. **Remote Configuration**: Update config via LoRa downlink
3. **Adaptive Sampling**: Adjust sensor frequency based on activity
4. **Multi-hop Networking**: Support LoRa mesh networking
5. **Web Interface**: Local WiFi configuration interface
6. **OTA Updates**: Over-the-air firmware updates
7. **Advanced Algorithms**: ML-based anomaly detection
8. **Data Compression**: Compress historical data to save memory

---

## 11. Summary

This architecture provides:

✅ **Simplicity**: Clear separation of concerns, minimal dependencies  
✅ **Modularity**: Easy to add new sensors and algorithms  
✅ **Efficiency**: Ring buffers prevent memory bloat  
✅ **Parallelism**: Asyncio enables concurrent operation  
✅ **Flexibility**: Event and window-based algorithm modes  
✅ **Scalability**: Multiple algorithm instances per sensor supported  
✅ **MicroPython-friendly**: No threading, efficient memory usage

The system is ready for implementation with clear interfaces and example code provided.
