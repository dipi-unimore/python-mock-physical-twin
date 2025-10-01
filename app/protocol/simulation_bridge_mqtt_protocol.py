"""Simulation Bridge protocol that exchanges messages through MQTT."""

from __future__ import annotations

import json
import ssl
import threading
from pathlib import Path
from types import MethodType
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

import paho.mqtt.client as mqtt
import yaml

from app.device.sensor import Sensor
from app.protocol.protocol import (
    InvalidConfigurationError,
    Protocol,
    validate_dict_keys,
)
from app.utils.result_router import ResultRouter, normalise_routes_config
from app.utils.emulator_utils import ProtocolType

if TYPE_CHECKING:
    from app.device.iot_device import IoTDevice


class SimulationBridgeMqttProtocol(Protocol):
    """Protocol that forwards device telemetry to the simulation bridge via MQTT."""

    def __init__(
        self,
        protocol_id: str,
        device_dict: Optional[Dict[str, "IoTDevice"]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            protocol_id,
            ProtocolType.SIMULATION_BRIDGE_MQTT_PROTOCOL_TYPE,
            device_dict,
            config,
        )

        self.base_path = Path(self.config.get("base_path", ".")).resolve()
        self.simulation_api_path = self._resolve_path(self.config["simulation_api"])

        aggregate_cfg = self.config.get("aggregate", {})
        self.aggregate_device_id: str = aggregate_cfg["device_id"]
        self.aggregate_sensor_id: str = aggregate_cfg["sensor_id"]
        self.aggregate_sensor_config: Optional[Dict[str, Any]] = aggregate_cfg.get(
            "sensor_config"
        )

        client_cfg_value = self.config.get("client_config")
        if isinstance(client_cfg_value, str):
            client_cfg_path = self._resolve_path(client_cfg_value)
            self.client_config = self._load_yaml(client_cfg_path)
        elif isinstance(client_cfg_value, dict):
            self.client_config = client_cfg_value
        else:
            raise InvalidConfigurationError(["client_config"])

        self.simulation_payload = self._load_yaml(self.simulation_api_path)

        self._router = self._build_router()

        self._validate_client_config(self.client_config)
        mqtt_cfg = self.client_config["mqtt"]

        self._host: str = mqtt_cfg.get("host", "localhost")
        self._port: int = int(mqtt_cfg.get("port", 1883))
        self._keepalive: int = int(mqtt_cfg.get("keepalive", 60))
        self._username: Optional[str] = mqtt_cfg.get("username")
        self._password: Optional[str] = mqtt_cfg.get("password")
        self._qos: int = int(mqtt_cfg.get("qos", 0))
        self._input_topic: str = mqtt_cfg["input_topic"]
        self._output_topic: str = mqtt_cfg["output_topic"]
        self._client_id: str = mqtt_cfg.get("client_id", f"simulation-bridge-{uuid4()}")
        self._tls_config = mqtt_cfg.get("tls")

        self.client: Optional[mqtt.Client] = None
        self._stop_event = threading.Event()
        self._sensor_lock = threading.Lock()
        self._aggregate_sensor: Optional[Sensor] = None

    def validate_config(self) -> None:  # type: ignore[override]
        required_keys = ["client_config", "simulation_api", "aggregate"]
        if not validate_dict_keys(self.config, required_keys):
            raise InvalidConfigurationError(required_keys)

        aggregate_cfg = self.config.get("aggregate", {})
        if not validate_dict_keys(aggregate_cfg, ["device_id", "sensor_id"]):
            raise InvalidConfigurationError(["aggregate.device_id", "aggregate.sensor_id"])

    def start(self) -> None:  # type: ignore[override]
        print(f"Starting protocol: {self.id} Type: {self.type}")
        self._stop_event.clear()
        self._ensure_aggregate_sensor()
        self._initialize_client()

    def stop(self) -> None:  # type: ignore[override]
        print(f"Stopping protocol: {self.id} Type: {self.type}")
        self._stop_event.set()
        client = self.client
        if client is not None:
            try:
                client.unsubscribe(self._output_topic)
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                client.disconnect()
            except Exception:  # pylint: disable=broad-except
                pass
            finally:
                try:
                    client.loop_stop()
                except RuntimeError:
                    pass
        self.client = None

    def publish_sensor_telemetry_data(self, device_id, sensor_id, payload):  # type: ignore[override]
        pass

    def publish_device_telemetry_data(self, device_id, payload):  # type: ignore[override]
        pass

    def _initialize_client(self) -> None:
        client = mqtt.Client(client_id=self._client_id)
        client.on_connect = self._handle_connect
        client.on_message = self._handle_message

        if self._username:
            client.username_pw_set(self._username, self._password)

        self._configure_tls(client)

        self.client = client
        client.connect(self._host, self._port, self._keepalive)
        client.loop_start()

    def _configure_tls(self, client: mqtt.Client) -> None:
        tls_cfg = self._tls_config
        if not tls_cfg:
            return

        if isinstance(tls_cfg, dict):
            ca_certs = tls_cfg.get("ca_certs")
            certfile = tls_cfg.get("certfile")
            keyfile = tls_cfg.get("keyfile")
            tls_version = str(tls_cfg.get("tls_version", "TLSv1_2")).upper()
            insecure = bool(tls_cfg.get("insecure", False))

            version_map = {
                "TLS": getattr(ssl, "PROTOCOL_TLS", ssl.PROTOCOL_TLS_CLIENT),
                "TLS_CLIENT": ssl.PROTOCOL_TLS_CLIENT,
                "TLSV1": getattr(ssl, "PROTOCOL_TLSv1", ssl.PROTOCOL_TLS_CLIENT),
                "TLSV1_1": getattr(ssl, "PROTOCOL_TLSv1_1", ssl.PROTOCOL_TLS_CLIENT),
                "TLSV1_2": getattr(ssl, "PROTOCOL_TLSv1_2", ssl.PROTOCOL_TLS_CLIENT),
                "TLSV1_3": getattr(ssl, "PROTOCOL_TLS", ssl.PROTOCOL_TLS_CLIENT),
            }
            version = version_map.get(tls_version, ssl.PROTOCOL_TLS_CLIENT)
            client.tls_set(
                ca_certs=self._resolve_optional_path(ca_certs),
                certfile=self._resolve_optional_path(certfile),
                keyfile=self._resolve_optional_path(keyfile),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=version,
            )
            client.tls_insecure_set(insecure)
        elif isinstance(tls_cfg, bool) and tls_cfg:
            client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(False)

    def _handle_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        if rc != 0:
            print(f"MQTT connection failed with result code {rc}")
            return

        try:
            client.subscribe(self._output_topic, qos=self._qos)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Failed to subscribe to simulation bridge topic {self._output_topic}: {exc}")
            return

        self._publish_simulation_request()

    def _handle_message(self, client, userdata, message):  # pylint: disable=unused-argument
        if self._stop_event.is_set():
            return

        payload_text = message.payload.decode("utf-8", errors="replace")
        parsed: Any
        try:
            parsed = yaml.safe_load(payload_text)
        except yaml.YAMLError:
            try:
                parsed = json.loads(payload_text)
            except json.JSONDecodeError:
                parsed = payload_text

        data_payload = self._extract_data_field(parsed)
        if data_payload is None:
            return

        sensor = self._ensure_aggregate_sensor()
        if sensor is None:
            return

        with self._sensor_lock:
            sensor.last_value = data_payload
            sensor.last_update_time = 0

        self._dispatch_routes(data_payload)

    def _publish_simulation_request(self) -> None:
        client = self.client
        if client is None:
            return

        try:
            payload = json.dumps(self.simulation_payload)
        except TypeError:
            payload = yaml.dump(self.simulation_payload, default_flow_style=False)

        client.publish(self._input_topic, payload, qos=self._qos)

    def _dispatch_routes(self, data_payload: Any) -> None:
        if not getattr(self, "_router", None):
            return
        client = self.client
        if client is None:
            return

        for message in self._router.dispatch(data_payload):
            topic = message.topic
            if not topic:
                continue
            qos = self._coerce_qos(message.qos)
            retain = bool(message.retain) if message.retain is not None else False
            try:
                client.publish(topic, message.payload, qos=qos, retain=retain)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Failed to publish routed MQTT message to {topic}: {exc}")

    def _coerce_qos(self, value: Optional[int]) -> int:
        try:
            qos = int(value) if value is not None else self._qos
        except (TypeError, ValueError):
            qos = self._qos
        if qos < 0:
            return 0
        if qos > 2:
            return 2
        return qos

    def _build_router(self) -> ResultRouter:
        routes_config = self._load_routes_config()
        return ResultRouter(routes_config)

    def _load_routes_config(self) -> Optional[List[Dict[str, Any]]]:
        combined: List[Dict[str, Any]] = []
        inline_value = self.config.get("routes")
        if inline_value is not None:
            if isinstance(inline_value, str):
                inline_value = self._load_routes_file(inline_value)
            try:
                inline_routes = normalise_routes_config(inline_value)
            except ValueError as exc:  # pragma: no cover - configuration error path
                raise InvalidConfigurationError(["config.routes"]) from exc
            if inline_routes:
                combined.extend(inline_routes)

        routes_file_value = self.config.get("routes_file")
        if routes_file_value is not None:
            file_data = self._load_routes_file(routes_file_value)
            try:
                file_routes = normalise_routes_config(file_data)
            except ValueError as exc:  # pragma: no cover - configuration error path
                raise InvalidConfigurationError(["config.routes_file"]) from exc
            if file_routes:
                combined.extend(file_routes)

        return combined or None

    def _load_routes_file(self, path_value: str) -> Any:
        path = self._resolve_path(path_value)
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or []

    def _ensure_aggregate_sensor(self) -> Optional[Sensor]:
        with self._sensor_lock:
            if self._aggregate_sensor is not None:
                return self._aggregate_sensor

            device = self.device_dict.get(self.aggregate_device_id)
            if device is None:
                return None

            sensor = device.get_sensor_by_id(self.aggregate_sensor_id)
            if sensor is None and self.aggregate_sensor_config is not None:
                sensor = Sensor(id=self.aggregate_sensor_id, **self.aggregate_sensor_config)
                device.sensors.append(sensor)

            if sensor is None:
                return None

            sensor.last_value = sensor.last_value or {}
            sensor.last_update_time = 0
            sensor.update_value = MethodType(lambda self_sensor: self_sensor.last_value, sensor)

            self._aggregate_sensor = sensor
            return sensor

    def _resolve_path(self, relative_path: str) -> Path:
        path = Path(relative_path).expanduser()
        if not path.is_absolute():
            path = (self.base_path / path).resolve()
        return path

    def _resolve_optional_path(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return str(self._resolve_path(value))

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"YAML file {path} did not contain a dictionary")
        return data

    @staticmethod
    def _extract_data_field(payload: Any) -> Optional[Any]:
        if isinstance(payload, dict):
            return payload.get("data")
        return None

    @staticmethod
    def _validate_client_config(config: Dict[str, Any]) -> None:
        mqtt_cfg = config.get("mqtt")
        if not isinstance(mqtt_cfg, dict):
            raise InvalidConfigurationError(["client_config.mqtt"])

        required_keys = ["host", "port", "input_topic", "output_topic"]
        missing = [key for key in required_keys if key not in mqtt_cfg or mqtt_cfg[key] is None]
        if missing:
            raise InvalidConfigurationError([f"client_config.mqtt.{key}" for key in missing])
