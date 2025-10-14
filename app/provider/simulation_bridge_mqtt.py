from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING
from datetime import datetime

import yaml
import jinja2
import paho.mqtt.client as mqtt

from app.provider.provider import Provider
from app.utils.emulator_utils import SensorType

if TYPE_CHECKING:
    from app.device.iot_device import IoTDevice
    from app.device.sensor import Sensor


@dataclass
class _RegisteredDevice:
    device: "IoTDevice"
    sensors: Sequence["Sensor"]


class SimulationBridgeMqtt(Provider):
    """
    Simulation Bridge provider using MQTT as the communication protocol.
    This provider interacts with an external Simulation Bridge service to fetch 
    simulated data for registered IoT devices.
    The provider uses the Paho MQTT client to connect to the Simulation Bridge, 
    send simulation requests, and receive responses. Every response is parsed and
    used to update the sensors of the registered devices that rely on the Simulation Bridge.
    """

    MQTT_SECTION = "mqtt"
    DEFAULT_KEEPALIVE = 60
    DEFAULT_QOS = 0

    def __init__(
        self,
        provider_id: str,
        protocol_config: Optional[str],
        payload_config: Optional[str],
    ):
        super().__init__(provider_id, protocol_config, payload_config)

        self.id = provider_id
        self.protocol_config_path = protocol_config
        self.payload_config_path = payload_config

        self._devices: Dict[str, _RegisteredDevice] = {}
        self._mqtt_settings: Dict[str, Any] = {}
        self._mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_connected: bool = False
        self._payload_template_raw: Optional[str] = None
        self._payload_format: str = "yaml"
        self._payload_cache: Dict[str, Dict[str, Any]] = {}
        self._latest_response: Optional[Dict[str, Any]] = None

        self._load_protocol_config()
        self._resolve_payload_path()

    def start(self):
        """
        Initialize the simulation bridge transport and send the first simulation request.
        """
        print(f"SB-Starting SimulationBridge provider: {self.id}")
        self.validate_config()
        self._start_client_sb()

    def stop(self):
        """
        Terminate the provider and release protocol resources.
        """
        print(f"SB-Stopping SimulationBridge provider: {self.id}")
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
            finally:
                self._mqtt_client.disconnect()
        self._mqtt_client = None
        self._mqtt_connected = False

    def register_device(self, device: "IoTDevice", sensors: Optional[Sequence["Sensor"]] = None):
        """
        Register an IoT device whose bridge-backed sensors should be updated.
        """
        bridge_sensors: List["Sensor"] = []
        candidates: Sequence["Sensor"] = sensors if sensors is not None else getattr(device, "sensors", ())

        # Identify sensors that rely on the Simulation Bridge as their data source
        for sensor in candidates:
            source = getattr(sensor, "source", "local")
            if not (isinstance(source, str) and source.lower() == "bridge"):
                continue

            sensor_source_id = getattr(sensor, "source_id", None)
            if sensor_source_id and sensor_source_id != self.id:
                continue

            bridge_sensors.append(sensor)

        # Skip devices without any bridge-backed sensors
        if not bridge_sensors:
            print(f"SB-Device {device.id} has no bridge-backed sensors for provider '{self.id}'; skipping registration.")
            return

        existing_entry = self._devices.get(device.id)
        if existing_entry:
            merged = {sensor.id: sensor for sensor in existing_entry.sensors}
            for sensor in bridge_sensors:
                merged[sensor.id] = sensor
            registered_sensors = tuple(merged.values())
        else:
            registered_sensors = tuple(bridge_sensors)

        # Register the device and its bridge sensors
        self._devices[device.id] = _RegisteredDevice(device=device, sensors=registered_sensors)
        print(f"SB-Registered device '{device.id}' with {len(registered_sensors)} simulation-bridge sensors (provider '{self.id}').")

        if self._mqtt_connected:
            self._trigger_simulation_request([device.id])

    def unregister_device(self, device_id: str):
        """
        Remove a device from the bridge registry.
        """
        if device_id in self._devices:
            del self._devices[device_id]
            print(f"SB-Unregistered device '{device_id}' from the simulation bridge.")

    def publish_sensor_telemetry_data(self, device_id, sensor_id, payload):
        """
        Relay sensor-level telemetry through the selected protocol implementation.
        """
        device_entry = self._devices.get(device_id)
        if not device_entry:
            print(f"SB-Publish skipped: device '{device_id}' not registered.")
            return
        device_entry.device.protocol.publish_sensor_telemetry_data(device_id, sensor_id, payload)

    def publish_device_telemetry_data(self, device_id, payload):
        """
        Relay device-level telemetry through the selected protocol implementation.
        """
        device_entry = self._devices.get(device_id)
        if not device_entry:
            print(f"SB-Publish skipped: device '{device_id}' not registered.")
            return
        device_entry.device.protocol.publish_device_telemetry_data(device_id, payload)

    def validate_config(self):
        """
        Ensure that the loaded configuration contains the required fields.
        """
        if not self._mqtt_settings:
            raise ValueError("SimulationBridge MQTT configuration not loaded.")

        # Check for required keys
        required_keys = ["host", "port", "input_topic", "output_topic"]
        missing = [key for key in required_keys if not self._mqtt_settings.get(key)]
        if missing:
            raise ValueError(f"SimulationBridge MQTT configuration missing keys: {', '.join(missing)}")

    def _load_protocol_config(self):
        """
        Load the protocol configuration file (MQTT) and determine the transport type.
        """
        # Check that the protocol configuration file exists
        if not self.protocol_config_path:
            raise ValueError("Protocol configuration path is not defined for SimulationBridge.")
        
        # Resolve the path and load the configuration
        resolved_path = self._resolve_path(self.protocol_config_path)
        self.protocol_config_path = resolved_path
        with open(resolved_path, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file) or {}

        # Support both a dedicated "mqtt" section or a flat configuration
        if self.MQTT_SECTION in config_data:
            mqtt_config = config_data[self.MQTT_SECTION] or {}
        else:
            mqtt_config = config_data

        # Extract MQTT settings with defaults
        self._mqtt_settings = {
            "host": mqtt_config.get("host") or mqtt_config.get("broker_ip"),
            "port": mqtt_config.get("port") or mqtt_config.get("broker_port"),
            "keepalive": mqtt_config.get("keepalive", self.DEFAULT_KEEPALIVE),
            "qos": mqtt_config.get("qos", self.DEFAULT_QOS),
            "input_topic": mqtt_config.get("input_topic"),
            "output_topic": mqtt_config.get("output_topic"),
            "username": mqtt_config.get("username"),
            "password": mqtt_config.get("password"),
            "client_id": mqtt_config.get("client_id"),
            "tls": mqtt_config.get("tls"),
        }

        if not self.payload_config_path and config_data.get("payload_file"):
            payload_file = config_data["payload_file"]
            base_dir = os.path.dirname(resolved_path)
            self.payload_config_path = self._resolve_path(payload_file, base_dir)

    def _resolve_payload_path(self):
        """
        Resolve the payload configuration path to an absolute path.
        """
        # Check that the payload configuration file exists
        if self.payload_config_path:
            self.payload_config_path = self._resolve_path(self.payload_config_path)
        else:
            print("SB-Warning: No payload configuration path defined for SimulationBridge.")

    @staticmethod
    def _resolve_path(path: str, base_dir: Optional[str] = None) -> str:
        if os.path.isabs(path):
            return path
        base = base_dir or os.getcwd()
        return os.path.abspath(os.path.join(base, path))

    def _load_payload(self, device: Optional["IoTDevice"] = None) -> Dict[str, Any]:
        """
        Load and render the simulation request payload template.
        """
        if not self.payload_config_path:
            raise ValueError("Payload configuration path is not defined.")

        cache_key = device.id if device else "__default__"
        if cache_key in self._payload_cache:
            return self._payload_cache[cache_key]

        if self._payload_template_raw is None:
            with open(self.payload_config_path, "r", encoding="utf-8") as file:
                self._payload_template_raw = file.read()
            self._payload_format = "json" if self.payload_config_path.endswith(".json") else "yaml"

        template = jinja2.Template(self._payload_template_raw)
        rendered = template.render(
            device=device,
            provider=self,
            mqtt=self._mqtt_settings,
        )

        if self._payload_format == "json":
            payload = json.loads(rendered)
        else:
            payload = yaml.safe_load(rendered)

        self._payload_cache[cache_key] = payload or {}
        return self._payload_cache[cache_key]

    def _start_client_sb(self):
        """
        Prepare the MQTT client used to communicate with the Simulation Bridge.
        """
        self._mqtt_client = mqtt.Client(client_id=self._mqtt_settings.get("client_id"))
        username = self._mqtt_settings.get("username")
        password = self._mqtt_settings.get("password")
        if username:
            self._mqtt_client.username_pw_set(username, password)

        # Configure TLS if requested
        self._configure_tls(self._mqtt_client, self._mqtt_settings.get("tls"))

        # Set up MQTT callbacks
        self._mqtt_client.on_connect = self._on_bridge_connect
        self._mqtt_client.on_message = self._on_simulation_message

        host = str(self._mqtt_settings["host"])
        port = int(self._mqtt_settings["port"])
        keepalive = int(self._mqtt_settings.get("keepalive", self.DEFAULT_KEEPALIVE))

        self._mqtt_client.connect(host, port, keepalive)
        self._mqtt_client.loop_start()

    def _configure_tls(self, client: mqtt.Client, tls_config: Any):
        """
        Configure TLS for the MQTT client when requested.
        """
        if not tls_config:
            return

        if isinstance(tls_config, dict):
            ca_certs = tls_config.get("ca_certs")
            certfile = tls_config.get("certfile")
            keyfile = tls_config.get("keyfile")
            insecure = tls_config.get("insecure", False)

            client.tls_set(
                ca_certs=ca_certs,
                certfile=certfile,
                keyfile=keyfile,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(bool(insecure))
        elif isinstance(tls_config, bool) and tls_config:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
            client.tls_insecure_set(False)

    def _on_bridge_connect(self, client, _userdata, _flags, rc):
        if rc != 0:
            print(f"SB-Connection to Simulation Bridge failed with rc={rc}")
            return

        print("SB-Connected to Simulation Bridge MQTT broker.")
        self._mqtt_connected = True
        
        # Subscribe to the output topic for receiving simulation responses
        output_topic = self._mqtt_settings.get("output_topic")
        qos = self._mqtt_settings.get("qos", self.DEFAULT_QOS)
        if output_topic:
            client.subscribe(output_topic, qos=qos)
            # print(f"SB-Subscribed to Simulation Bridge topic '{output_topic}' (qos={qos}).")

        # Trigger an initial simulation request for all registered devices
        self._trigger_simulation_request()

    def _trigger_simulation_request(self, device_ids: Optional[Iterable[str]] = None):
        """
        Publish a simulation request to the Simulation Bridge using MQTT.
        """
        # If the client is not connected, skip the request
        if not self._mqtt_client or not self._mqtt_connected:
            print("ERROR: SB-Simulation request skipped: MQTT client not connected yet.")
            return

        target_devices: Iterable[_RegisteredDevice]
        if device_ids:
            target_devices = [
                self._devices[device_id]
                for device_id in device_ids
                if device_id in self._devices
            ]
        else:
            target_devices = self._devices.values()

        if not target_devices:
            print("SB-No registered devices for simulation requests.")
            return

        input_topic = self._mqtt_settings["input_topic"]
        qos = self._mqtt_settings.get("qos", self.DEFAULT_QOS)

        for entry in target_devices:
            payload_dict = self._load_payload(entry.device)
            payload_dict = convert_datetime_in_payload(payload_dict)
            payload = json.dumps(payload_dict)
            print(f"SB-Publishing simulation request for '{entry.device.id}' to '{input_topic}'")
            self._mqtt_client.publish(input_topic, payload, qos=qos)

    def _on_simulation_message(self, _client, _userdata, message):
        """
        Store the latest simulation response for later dispatch.
        """
        try:
            payload_text = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            print("SB-Received non UTF-8 payload from Simulation Bridge; skipping.")
            return

        # FOR DEBUG PURPOSE
        # print(f"SB-Received message on '{message.topic}': {payload_text}")
        payload = self._parse_simulation_payload(payload_text)
        if payload is None:
            print("SB-Unable to parse simulation payload; ignoring message.")
            return

        # Cache the latest response and update relevant devices
        self._latest_response = payload

        # Determine target devices
        target_ids = list(self._devices.keys())
        for device_id in target_ids:
            entry = self._devices.get(device_id)
            if not entry:
                print(f"SB-Payload references unknown device '{device_id}', skipping.")
                continue

            self._update_device_sensors(entry, payload)

            # Optionally, trigger telemetry publication for updated sensors
            # updated_sensors = self._update_device_sensors(entry, payload)
            # DEBUG PURPOSE
            # if not updated_sensors:
            #     print(f"SB-No bridge sensor values resolved for device '{device_id}'.")
            #     continue
            # print(f"SB-Buffered {len(updated_sensors)} sensor values for device '{device_id}'.")

    def _parse_simulation_payload(self, payload_text: str) -> Optional[Dict[str, Any]]:
        """
        Try to parse the incoming payload as JSON (fallback to YAML).
        """
        try:
            return json.loads(payload_text)
        except json.JSONDecodeError:
            try:
                parsed = yaml.safe_load(payload_text)
                if isinstance(parsed, dict):
                    return parsed
            except yaml.YAMLError:
                return None
        return None

    def _update_device_sensors(
        self,
        entry: _RegisteredDevice,
        payload: Dict[str, Any],
    ) -> List["Sensor"]:
        """
        Update sensors associated to a device based on the payload content requested.
        """
        updated: List["Sensor"] = []
        # Iterate over all bridge-backed sensors and try to resolve their values
        for sensor in entry.sensors:
            bridge_value = getattr(sensor, "bridge_value", None)
            if not bridge_value:
                continue

            # Extract the value from the payload using the specified path
            resolved = self._extract_value(payload, bridge_value)
            if resolved is None:
                continue

            # Try to solve the sensor value according to its declared type (if possible, else keep as-is)
            coerced = self._coerce_sensor_value(sensor, resolved)
            # Update the sensor's bridge value
            sensor.set_bridge_value(coerced)
            # Mark the sensor as updated
            updated.append(sensor)

        return updated

    def _extract_value(self, payload: Dict[str, Any], path: str) -> Any:
        """
        Resolve a dotted path with optional list indices (e.g. 'data.items[0].value').
        """
        current: Any = payload
        for segment in path.split("."):
            # If it does not exist, return None
            if current is None:
                return None

            # Split list indices from the segment
            # For instance, "items[0][1]" -> ["items", "0", "1"]
            parts = [part for part in segment.replace("]", "").split("[") if part]

            # Navigate through the parts:
            # - if it's a dict, use it as a key, else return None
            # - if it's a list, use it as an index (if valid), else return None
            # - if it's neither, return None
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list):
                    try:
                        index = int(part)
                    except ValueError:
                        return None
                    if index >= len(current):
                        return None
                    current = current[index]
                else:
                    return None

        return current

    def _coerce_sensor_value(self, sensor: "Sensor", value: Any) -> Any:
        """
        Try to resolve the sensor value according to its declared type.
        """
        sensor_type_name = getattr(sensor, "type", "").lower()
        try:
            sensor_type = SensorType(sensor_type_name)
        except ValueError:
            # Unknown sensor type (e.g. json) - leave the value untouched.
            return value

        if sensor_type is SensorType.SENSOR_NUMERIC_TYPE:
            if isinstance(value, (int, float)):
                return value
            try:
                return float(value)
            except (TypeError, ValueError):
                return value

        if sensor_type is SensorType.SENSOR_BOOLEAN_TYPE:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "on"}
            if isinstance(value, (int, float)):
                return bool(value)
            return value

        if sensor_type is SensorType.SENSOR_STRING_TYPE:
            return str(value)

        # For other sensor types keep the original value.
        return value

def convert_datetime_in_payload(payload):
    if isinstance(payload, dict):
        # If the payload is a dictionary, recursively convert datetime values
        for key, value in payload.items():
            payload[key] = convert_datetime_in_payload(value)
    elif isinstance(payload, list):
        # If the payload is a list, recursively convert datetime values
        for index in range(len(payload)):
            payload[index] = convert_datetime_in_payload(payload[index])
    elif isinstance(payload, datetime):
        # If you find a datetime object, convert it to ISO 8601 string
        return payload.isoformat()
    return payload
