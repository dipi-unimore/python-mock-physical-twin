# IoT Device Emulator

This project is an IoT device emulator designed to simulate devices with
various sensors and actuators using different communication protocols (HTTP, MQTT).
It reads configurations from YAML files to define devices and their behaviors.
Thanks to integration with the Simulation Bridge, the emulator can also acquire
real-time data from external simulators.

## Getting Started

To run the IoT device emulator, follow these steps:

### Prerequisites

- Python>3.13 installed on your system.
- Required Python packages installed:

```bash
pip install -r requirements.txt
```

### Configuration

The emulator uses YAML configuration files to describe protocols, devices, sensors, and actuators. When a configuration
enables a `simulation_bridge_*` protocol, a few extra keys become mandatory to instruct the bridge on how to call the
external simulator and where to inject the simulation results. The dedicated section later in this README details each
adapter; here you will find the high-level structure shared by every configuration.

Main configuration options:

- **protocols:** Declares the communication adapters used by the emulated devices. Traditional options include
  `http` and `mqtt`; Simulation Bridge clients are exposed as `simulation_bridge_rest`, `simulation_bridge_amqp`, or
  `simulation_bridge_mqtt` and require an additional `config` payload with `simulation_api`, `aggregate`, and
  protocol-specific `client_config` entries (see the Simulation Bridge chapter for the full breakdown).
- **devices:** Lists the virtual IoT devices, mapping each one to a protocol adapter via `protocol_id`. Every device can
  declare multiple sensors and actuators. When the Simulation Bridge `aggregate` block references a device/sensor pair,
  that pair must exist (or be creatable from the provided `sensor_config`).
- **independent_communication:** Controls whether sensors/actuators publish as soon as they have fresh data. Set it to
  `True` to let each sensor respect its own `update_time_ms` cadence; use `False` to synchronize updates at the device
  level through `device_update_delay_ms`.
- **device_update_delay_ms:** Defines the polling period, in milliseconds, applied when `independent_communication` is
  disabled.

#### Sensors

Available sensor types:

- **numeric:** Generates floating-point values within `[min_val, max_val]`, starting from `initial_value`.
- **boolean:** Produces random boolean values and supports an `initial_value` toggle.
- **string:** Returns free-form text coming from the `value` field or from upstream sources.
- **random_string:** Emits random alphanumeric strings of configurable length (`value_len`).
- **fixed_string:** Always exposes the same literal `value`.

Every sensor accepts `update_time_ms`, which sets the minimum delay between consecutive updates. Sensors can read data
from CSV streams by specifying `csv_file` and the list of `value_columns`; the emulator aggregates the selected columns
into a single payload (e.g., `accel_x`, `accel_y`, `accel_z`). When Simulation Bridge adapters are active, results coming
from the external simulator are written into the sensor designated in the `aggregate` block using the same update
mechanism.

#### Actuators

Actuator types mirror the supported payload shapes:

- **numeric:** Receives numeric commands.
- **boolean:** Receives boolean commands.
- **string:** Receives textual commands.

Each actuator can declare an `initial_value`. By default, incoming actions are logged; extend the actuator class and
override `handle_action(self, request_type, request_payload)` to implement custom side effects. Remember to register new
actuator classes in the main module so that the emulator can instantiate them from the configuration.

Below are examples of configuration files for HTTP and MQTT protocols (multiple protocols and device configurations can
coexist in the same file):

#### HTTP Example Configuration

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

## Simulation Bridge

Il [Simulation Bridge](https://github.com/INTO-CPS-Association/simulation-bridge) (sim-bridge) è un middleware modulare e bidirezionale che mette in comunicazione Digital Twin (DT), Mock Physical Twin (MockPT) e Physical Twin (PT) con diversi ambienti di simulazione distribuiti. Agisce come uno strato di collegamento intelligente: riceve i dati dai gemelli, li instrada verso i componenti corretti (Simulator Agents), raccoglie i risultati delle simulazioni e li restituisce ai client.

Questa repository include tre client di esempio che permettono a un MockPT di dialogare con sim-bridge usando protocolli differenti (REST, AMQP e MQTT) e recuperare i risultati delle simulazioni:

- **SimulationBridgeRestProtocol**: invia la richiesta di simulazione via HTTP/2 e riceve uno stream di risposte NDJSON. Il file `conf/simulation_bridge_rest_test_config.yaml` contiene:

  - `client_config`: host, secret JWT, e parametri di sicurezza per autenticare la chiamata.
  - `simulation_api`: percorso del payload YAML da inviare al bridge.
  - `aggregate`: identifica il dispositivo/sensore locale che verrà aggiornato con il campo `data` restituito dalla simulazione. (Risultato della simulazione)
  - `server_port` (opzionale) per esporre le letture del sensore tramite l’HTTP server integrato.
    La classe converte ogni riga NDJSON in un dizionario, estrae `data` e aggiorna il sensore aggregato.

- **SimulationBridgeAmqpProtocol**: pubblica la richiesta su RabbitMQ e si sottoscrive al risultato. La configurazione `conf/simulation_bridge_amqp_test_config.yaml` definisce:

  - `client_config.rabbitmq`: host, porta, credenziali e TLS del broker AMQP.
  - `client_config.exchanges`: topic di input/output su cui pubblicare e ascoltare.
  - `client_config.queue`: nome e routing key della coda che riceve le risposte.
  - `client_config.digital_twin`: identificativi del digital twin per instradare i messaggi.
  - `simulation_api` e `aggregate` con la stessa semantica del caso REST.
    L’adapter pubblica il payload YAML, ascolta la coda dei risultati, estrae `data` da ogni messaggio e lo salva sul sensore.

- **SimulationBridgeMqttProtocol**: usa MQTT per richiedere la simulazione e ricevere i dati. Il file `conf/simulation_bridge_mqtt_test_config.yaml` descrive:
  - `client_config.mqtt`: host, port, keepalive, QoS, topic di input/output e credenziali.
  - `simulation_api` e `aggregate` come negli altri protocolli.
    L’adapter invia il payload, sottoscrive il topic di output e, per ogni messaggio, aggiorna il sensore con il contenuto di `data`.

In tutti i casi il campo `aggregate` permette di specificare dove salvare i risultati all’interno dell’IoT device emulato: se il sensore non esiste, viene creato usando la relativa `sensor_config`.

### Running the Emulator

To start the IoT device emulator, run the `physical_twin_emulator.py` script
with the configuration file path specified using the -c or --config option:

```bash
python physical_twin_emulator.py -c http_test_config.yaml
```
