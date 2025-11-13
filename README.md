# Mock Physical Twin (MockPT): What is it

This project is an IoT Device Emulator designed to simulate virtual devices equipped with various sensors and actuators, communicating over multiple protocols such as OPC-UA, HTTP and MQTT.

Device behavior and communication settings are defined through flexible YAML configuration files, allowing quick setup of complex scenarios.

The emulator can also integrate seamlessly with the **[Simulation Bridge](https://github.com/INTO-CPS-Association/simulation-bridge)**, enabling sensors to stream simulation-driven data derived from distributed simulation environments.

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Pick or create a configuration**
   - Ready-made examples live under `conf/`.
   - Use `conf/opcua_test_config.yaml`, `conf/http_test_config.yaml` or `conf/mqtt_test_config.yaml`
     as templates.
3. **Run the emulator**
   ```bash
   python physical_twin_emulator.py -c <path-to-config>.yaml
   ```

## Configuration Guide

The emulator uses YAML configuration files to define protocols and devices together with their sensors and actuators.

Main configuration options are the following:

- **Protocols**  
  Provide an `id`, a `type` (`opcua`, `http` or `mqtt`), and the settings required by the
  chosen adapter (OPCUA `server_url`, HTTP `server_port`, MQTT broker credentials, etc.). Devices
  refer to the adapter via `protocol_id`.

- **Devices**  
  Each device needs an `id`, a `protocol_id`, and the lists of `sensors` and
  `actuators`. Device-level communication behaviour is governed by:

  - `independent_communication: true` → every sensor publishes as soon as its
    `update_time_ms` elapses.
  - `independent_communication: false` → sensor values are aggregated and sent
    every `device_update_delay_ms`.

- **Sensors**  
  Required fields are `id`, `type`, `update_time_ms`, and `source` (`local` by
  default). Supported types:

  - `numeric`: random float between `min_val` and `max_val` (optional
    `initial_value`).
  - `boolean`: random boolean, optional `initial_value`.
  - `string` / `fixed_string`: always publish the supplied `value`.
  - `random_string`: emits an alphanumeric string of length `value_len`.
  - Any sensor can replay values from a CSV when `csv_file` and
    `value_columns` are supplied; additional fields such as `timestamp_column`
    or `timestamp_unit` control timestamp handling.

- **Actuators**  
   Supported types mirror the sensor set (`numeric`, `boolean`, `string`). By default, commands are printed to the console;
  extend the actuator class and override `handle_action` to implement custom behaviour. For each actuator it is also possible to specify the `initial_value` according to its type.
  The default management for an actuator is just to log on the console the received message. If you want to create custom behaviour you can extend the actuator class overriding the method `handle_action(self, request_type, request_payload)` in order to implement your own logic. Introducing a new actuator behaviour and class should be handled in the main file in order to properly load theclass according to its new type (that should be declared).

- **Data providers (optional)**  
  Bridge-backed sensors require a provider declaration in `data_providers`. See
  the next section for details.

## Simulation Bridge

The emulator can stream telemetry from the [Simulation Bridge](https://github.com/INTO-CPS-Association/simulation-bridge) and republish it using HTTP or MQTT.

1. **Declare the provider**

   ```yaml
   data_providers:
     - source_id: "simBridge1"
       type: "simulation_bridge"
       protocol_config: "../sb-conf/mqtt_use.yaml"
       payload_config: "../sb-conf/simulation.yaml"
   ```

   - `source_id` uniquely identifies the provider.
   - `protocol_config` points to the MQTT client settings for the bridge.
   - `payload_config` points to the request template (JSON or YAML).

2. **Link sensors to the bridge**

   ```yaml
   sensors:
     - id: "distanceSensor"
       type: "numeric"
       source: "bridge"
       source_id: "simBridge1"
       update_time_ms: 500
       bridge_value: "data.distance"
   ```

   - `source` must be `"bridge"`.
   - `source_id` must match the provider identifier.
   - `bridge_value` is a dot-notation path inside the bridge response. List
     indices are supported (e.g. `items[0].value`).

3. **Runtime behaviour**
   - Providers are instantiated before devices start.
   - Only sensors whose `source_id` resolves to a declared provider are
     registered; missing or unknown identifiers trigger a warning.
   - Sensor values coming from the bridge follow the same publishing rules as
     local sensors (`independent_communication` vs. `device_update_delay_ms`).
   - Local sensors remain unaffected by the presence of the bridge.

## Example (HTTP with Simulation Bridge)

```yaml
protocols:
  - id: "httpProtocol"
    type: "http"
    config:
      server_port: 5555
devices:
  - id: "device1"
    protocol_id: "httpProtocol"
    sensors:
      - id: "distanceSensor"
        type: "numeric"
        source: "bridge"
        source_id: "simBridge1"
        update_time_ms: 500
        bridge_value: "data.distance"
      - id: "randomStringSensor"
        type: "random_string"
        source: "local"
        update_time_ms: 2000
        value_len: 10
    actuators:
      - id: "demoActuator"
        type: "string"
        initial_value: "ON"
data_providers:
  - source_id: "simBridge1"
    type: "simulation_bridge"
    protocol_config: "../sb-conf/mqtt_use.yaml"
    payload_config: "../sb-conf/simulation.yaml"
independent_communication: true
device_update_delay_ms: 10
```

Additional ready-to-run examples for pure HTTP or MQTT setup are available in the `conf/` directory.

### HTTP Example Configuration

Details and endpoints related to the RESTful APIs exposed by the implementation are available through a PostMan application
collection in the repository folder [api](api). You can import it in PostMan and test the APIs.

```yaml
protocols:
  - id: "httpProtocol"
    type: "http"
    config:
      server_port: 5555
devices:
  - id: "device1"
    protocol_id: "httpProtocol"
    sensors:
      - id: "numericSensor"
        type: "numeric"
        update_time_ms: 2000 # Update every 2 seconds
        min_val: 0
        max_val: 100
        initial_value: 0
      - id: "booleanSensor"
        type: "boolean"
        update_time_ms: 2000 # Update every 2 seconds
        initial_value: false
      - id: "randomStringSensor"
        type: "random_string"
        value_len: 10
        update_time_ms: 2000 # Update every 2 seconds
      - id: "fixedStringSensor"
        type: "fixed_string"
        value: "test-fixed-string"
        update_time_ms: 2000 # Update every 2 seconds
    actuators:
      - id: "demoActuator"
        type: "string"
        initial_value: "ON"
independent_communication: True
device_update_delay_ms: 10 # Update every 10 seconds if independent_communication is False
```

#### MQTT Example Configuration File

```yaml
protocols:
  - id: "mqttProtocol"
    type: "mqtt"
    config:
      broker_ip: "192.168.1.106"
      broker_port: 1883
      username: null
      password: null
devices:
  - id: "device1"
    protocol_id: "mqttProtocol"
    sensors:
      - id: "fixedStringSensor"
        type: "fixed_string"
        value: "test-fixed-string"
        update_time_ms: 5000
      - id: "sensor_accel"
        type: "numeric"
        update_time_ms: 1000
        csv_file: "data/accelerometer_data_seconds.csv"
        value_columns: ["accel_x", "accel_y", "accel_z"]
    actuators:
      - id: "demoActuator"
        type: "string"
        initial_value: "ON"
independent_communication: True
device_update_delay_ms: 1000 # Update every 10 seconds if independent_communication is False
```

#### MQTT Configuration File with CSV Input

```yaml
protocols:
  - id: "mqttProtocol"
    type: "mqtt"
    config:
      broker_ip: "192.168.1.106"
      broker_port: 1883
      username: null
      password: null
devices:
  - id: "device1"
    protocol_id: "mqttProtocol"
    sensors:
      - id: "fixedStringSensor"
        type: "fixed_string"
        value: "test-fixed-string"
        update_time_ms: 5000
      - id: "sensor_accel"
        type: "numeric"
        update_time_ms: 1000
        csv_file: "data/accelerometer_data_seconds.csv"
        value_columns: ["accel_x", "accel_y", "accel_z"]
    actuators:
      - id: "demoActuator"
        type: "string"
        initial_value: "ON"
independent_communication: True
device_update_delay_ms: 1000 # Update every 10 seconds if independent_communication is False
```

## OPC UA Protocol Integration
The **OPC UA** (Open Platform Communications Unified Architecture) protocol has been integrated to extend the communication capabilities of the mock physical twin framework. This implementation allows the system to emulate OPC UA-based digital twins, providing both publish/subscribe and request/response interaction modes.

### Server Description
The file `app/protocol/opcua_protocol.py` defines a class-based OPC UA Server that:
- Initializes an OPC UA endpoint according to the parameters defined in the YAML configuration file;
- Registers nodes corresponding to the configured devices and their attributes;
- Handles both data publishing and client read requests;
- Maintains compatibility with the generic protocol structure used for MQTT and HTTP, inheriting from the base `Protocol` class.

### Client Modes
Two separate client implementations are provided, reflecting different use cases for OPC UA communication:

1. **Publish/Subscribe Mode**
File: `app/opcua-client/pub-sub_client.py`
  - Simulates a client that **subscribes to data changes** on specific nodes exposed by the server.
  - Requires the same **YAML configuration file** (`conf/opcua_test_config.yaml`) used by the server to correctly identify devices and monitored variables.
  - Automatically handles data updates and logs received changes

2. **Request/Response Mode**
File: `app/opcua-client/req-res_client.py`
  - Implements a **single-request client** that connects to the OPC UA server, retrieves data for a specific device, and disconnects after the response.
  - Designed for lightweight, on-demand data queries (e.g., device state polling or remote inspection)

#### OPC UA Example Configuration File
The file `conf/opcua_test_config.yaml` follows the same structural pattern as the other protocol configurations (`http_test_config.yaml` and `mqtt_test_config.yaml`), including:
```yaml
protocols:
  - id: "opcuaProtocol"
    type: "opcua"
    config:
      server_url: "opc.tcp://localhost:4840/freeopcua/server/"
      server_name: "MockPhysicalTwin"
      namespace: "http://examples.mockphysicaltwin.com"
      security_mode: "None"
      security_policy: "None"
      username: null
      password: null
devices:
  - id: "Device1"
    protocol_id: "opcuaProtocol"
    sensors:
      - id: "fixedStringSensor"
        type: "fixed_string"
        value: "test-fixed-string"
        update_time_ms: 5000
        node_id: "ns=2;s=Device1.fixedStringSensor"
      - id: "sensor_accel"
        type: "numeric"
        update_time_ms: 1000
        csv_file: "test/data/accelerometer_data_seconds.csv"
        value_columns: ["accel_x", "accel_y", "accel_z"]
        node_id: "ns=2;s=Device1.sensor_accel"
    actuators:
      - id: "demoActuator"
        type: "string"
        initial_value: "ON"
        node_id: "ns=2;s=Device1.demoActuator"
independent_communication: False
device_update_delay_ms: 10000 # Update every 10 seconds if independent_communication is False
```
This ensures consistency across all communication protocols and allows the same logical device definitions to be reused.

### How to Run
Start the OPC UA Server:
```bash
python app/physical_twin_emulator.py --config conf/opcua_test_config.yaml
```
Then in separate terminals, you can launch either client mode:

**Publish/Subscribe client**:
```bash
python app/opcua-client/pub-sub_client.py --config conf/opcua_test_config.yaml
```

**Request/Response client**:
```bash
python app/opcua-client/req-res_client.py
```

## Author

<div style="display: flex; flex-direction: column; gap: 25px;"> <!-- Marco Melloni --> <div style="display: flex; align-items: center; gap: 15px;"> <img src="images/melloni.jpg" width="60" style="border-radius: 50%; border: 2px solid #eee;"/> <div> <h3 style="margin: 0;">Marco Melloni</h3> <p style="margin: 4px 0;">Digital Automation Engineering Student<br> University of Modena and Reggio Emilia, Department of Sciences and Methods for Engineering (DISMI)</p> <div> <a href="https://www.linkedin.com/in/marco-melloni/"> <img src="https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat-square&logo=linkedin"/> </a> <a href="https://github.com/marcomelloni" style="margin-left: 8px;"> <img src="https://img.shields.io/badge/GitHub-Profile-black?style=flat-square&logo=github"/> </a> </div> </div> </div> <!-- Marco Picone --> <div style="display: flex; align-items: center; gap: 15px;"> <img src="images/picone.jpeg" width="60" style="border-radius: 50%; border: 2px solid #eee;"/> <div> <h3 style="margin: 0;">Prof. Marco Picone</h3> <p style="margin: 4px 0;">Associate Professor<br> University of Modena and Reggio Emilia, Department of Sciences and Methods for Engineering (DISMI)</p> <div> <a href="https://www.linkedin.com/in/marco-picone-8a6a4612/"> <img src="https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat-square&logo=linkedin"/> </a> <a href="https://github.com/piconem" style="margin-left: 8px;"> <img src="https://img.shields.io/badge/GitHub-Profile-black?style=flat-square&logo=github"/> </a> </div> </div> </div> <!-- Davide Ziglioli --> <div style="display: flex; align-items: center; gap: 15px;"> <img src="images/ziglioli.jpg" width="60" style="border-radius: 50%; border: 2px solid #eee;"/> <div> <h3 style="margin: 0;">Davide Ziglioli</h3> <p style="margin: 4px 0;">Graduated Digital Automation Engineering Student<br> University of Modena and Reggio Emilia, Department of Sciences and Methods for Engineering (DISMI)</p> <div> <a href="https://www.linkedin.com/in/davide-ziglioli/"> <img src="https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat-square&logo=linkedin"/> </a> <a href="https://github.com/davide-z99" style="margin-left: 8px;"> <img src="https://img.shields.io/badge/GitHub-Profile-black?style=flat-square&logo=github"/> </a> </div> </div></div> </div>
