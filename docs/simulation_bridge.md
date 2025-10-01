## Simulation Bridge

> ##### Refer to the Simulation Bridge Routing and Dispatch Guide [here](./simulation_bridge_routing.md)

The [Simulation Bridge](https://github.com/INTO-CPS-Association/simulation-bridge) (sim-bridge) is a modular and bidirectional middleware that connects Digital Twin (DT), Mock Physical Twin (MockPT), and Physical Twin (PT) with different distributed simulation environments. It acts as a smart connection layer: it receives data from twins, routes them to the correct components (Simulator Agents), collects simulation results, and returns them to the clients.

This repository includes three example clients that allow a MockPT to communicate with sim-bridge using different protocols (REST, AMQP, and MQTT) and retrieve simulation results:

- **SimulationBridgeRestProtocol**: sends the simulation request via HTTP/2 and receives a stream of NDJSON responses. The file `conf/simulation_bridge_rest_test_config.yaml` contains:

  - `client_config`: host, JWT secret, and security parameters to authenticate the call.
  - `simulation_api`: path to the YAML payload to send to the bridge.
  - `aggregate`: identifies the local device/sensor that will be updated with the `data` field returned by the simulation (simulation result).
  - `server_port` (optional) to expose sensor readings through the integrated HTTP server.
    The class converts each NDJSON line into a dictionary, extracts `data`, and updates the aggregated sensor.

- **SimulationBridgeAmqpProtocol**: publishes the request on RabbitMQ and subscribes to the result. The configuration `conf/simulation_bridge_amqp_test_config.yaml` defines:

  - `client_config.rabbitmq`: host, port, credentials, and TLS of the AMQP broker.
  - `client_config.exchanges`: input/output topics to publish and listen to.
  - `client_config.queue`: name and routing key of the queue that receives responses.
  - `client_config.digital_twin`: digital twin identifiers to route messages.
  - `simulation_api` and `aggregate` with the same meaning as the REST case.
    The adapter publishes the YAML payload, listens to the result queue, extracts `data` from each message, and saves it to the sensor.

- **SimulationBridgeMqttProtocol**: uses MQTT to request the simulation and receive data. The file `conf/simulation_bridge_mqtt_test_config.yaml` describes:
  - `client_config.mqtt`: host, port, keepalive, QoS, input/output topics, and credentials.
  - `simulation_api` and `aggregate` as in the other protocols.
    The adapter sends the payload, subscribes to the output topic, and for each message, updates the sensor with the content of `data`.

In all cases, the `aggregate` field lets you specify where to save the results inside the emulated IoT device: if the sensor does not exist, it is created using the related `sensor_config`.
