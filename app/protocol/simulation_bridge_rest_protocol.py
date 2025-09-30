"""Simulation Bridge protocol that exchanges messages through REST over HTTP/2."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import MethodType
from typing import TYPE_CHECKING, Any, Dict, Optional

import httpx
import jwt
import yaml

from flask import Flask, abort, jsonify, request

from app.device.sensor import Sensor

from app.protocol.protocol import (
    InvalidConfigurationError,
    Protocol,
    validate_dict_keys,
)
from app.utils.emulator_utils import ProtocolType

if TYPE_CHECKING:
    from app.device.iot_device import IoTDevice


class SimulationBridgeRestProtocol(Protocol):
    """Protocol that forwards device telemetry to the simulation bridge via REST."""

    def __init__(
        self,
        protocol_id: str,
        device_dict: Optional[Dict[str, "IoTDevice"]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            protocol_id,
            ProtocolType.SIMULATION_BRIDGE_REST_PROTOCOL_TYPE,
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

        self.simulation_payload_bytes = self.simulation_api_path.read_bytes()

        self._stop_event = threading.Event()
        self._sensor_lock = threading.Lock()
        self._aggregate_sensor: Optional[Sensor] = None

        self._server_host: str = str(self.config.get("server_host", "0.0.0.0"))
        server_port = self.config.get("server_port")
        self._server_port: Optional[int]
        if server_port is not None:
            try:
                self._server_port = int(server_port)
            except (TypeError, ValueError) as exc:
                raise InvalidConfigurationError(["server_port"]) from exc
        else:
            self._server_port = None

        self.app: Optional[Flask] = None
        self._server_thread: Optional[threading.Thread] = None
        self._routes_configured = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_ready: Optional[threading.Event] = None
        self._client_task: Optional[asyncio.Task[None]] = None

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
        self._start_event_loop()
        self._start_http_server()

    def stop(self) -> None:  # type: ignore[override]
        print(f"Stopping protocol: {self.id} Type: {self.type}")
        self._stop_event.set()

        loop = self._loop
        if loop and loop.is_running():
            def _cancel_task() -> None:
                if self._client_task is not None:
                    self._client_task.cancel()
                loop.stop()

            loop.call_soon_threadsafe(_cancel_task)

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

        self._client_task = None
        self._loop = None
        self._loop_thread = None
        self._loop_ready = None

    def publish_sensor_telemetry_data(self, device_id, sensor_id, payload):  # type: ignore[override]
        pass

    def publish_device_telemetry_data(self, device_id, payload):  # type: ignore[override]
        pass

    def _start_http_server(self) -> None:
        if self._server_port is None:
            return

        if self.app is None:
            self.app = Flask(self.id)

        self.setup_routes()

        if self._server_thread is not None and self._server_thread.is_alive():
            return

        def _run_server() -> None:
            assert self.app is not None
            self.app.run(
                host=self._server_host,
                port=self._server_port,
                debug=False,
                use_reloader=False,
            )

        print(
            f"Simulation bridge REST protocol exposing HTTP endpoints on "
            f"{self._server_host}:{self._server_port}"
        )

        self._server_thread = threading.Thread(
            target=_run_server,
            name=f"{self.id}-rest-http",
            daemon=True,
        )
        self._server_thread.start()

    def setup_routes(self) -> None:
        if self.app is None or self._routes_configured:
            return

        app = self.app

        @app.route("/devices", methods=["GET"], endpoint="simulation_bridge_devices")
        def get_active_devices():
            result = [device.get_device_descr() for device in self.device_dict.values()]
            return jsonify(result)

        @app.route(
            "/devices/<device_id>",
            methods=["GET"],
            endpoint="simulation_bridge_device",
        )
        def get_active_device(device_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            return jsonify(device.get_device_descr())

        @app.route(
            "/devices/<device_id>/sensors",
            methods=["GET"],
            endpoint="simulation_bridge_device_sensors",
        )
        def get_sensors(device_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            result = [self._sensor_to_dict(sensor) for sensor in device.sensors]
            return jsonify(result)

        @app.route(
            "/devices/<device_id>/sensors/<sensor_id>",
            methods=["GET"],
            endpoint="simulation_bridge_device_sensor",
        )
        def get_sensor(device_id, sensor_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            sensor = device.get_sensor_by_id(sensor_id)
            if sensor is None:
                abort(404, description=f"Sensor {sensor_id} not found")
            return jsonify(self._sensor_to_dict(sensor))

        @app.route(
            "/devices/<device_id>/actuators",
            methods=["GET"],
            endpoint="simulation_bridge_device_actuators",
        )
        def list_actuators(device_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            result = [actuator.to_dict() for actuator in device.actuators]
            return jsonify(result)

        @app.route(
            "/devices/<device_id>/actuators/<actuator_id>",
            methods=["GET"],
            endpoint="simulation_bridge_device_actuator_read",
        )
        def get_actuator(device_id, actuator_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            actuator = device.get_actuator_by_id(actuator_id)
            if actuator is None:
                abort(404, description=f"Actuator {actuator_id} not found")
            return jsonify(actuator.to_dict())

        @app.route(
            "/devices/<device_id>/actuators/<actuator_id>",
            methods=["POST"],
            endpoint="simulation_bridge_device_actuation_post",
        )
        def control_actuator_post(device_id, actuator_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            actuator = device.get_actuator_by_id(actuator_id)
            if actuator is None:
                abort(404, description=f"Actuator {actuator_id} not found")
            action_payload = request.json if request.data else None
            if actuator.handle_action("POST", action_payload):
                return ("", 204)
            abort(404, description=f"Actuator {actuator_id} not found")

        @app.route(
            "/devices/<device_id>/actuators/<actuator_id>",
            methods=["PUT"],
            endpoint="simulation_bridge_device_actuation_put",
        )
        def control_actuator_put(device_id, actuator_id):
            device = self.device_dict.get(device_id)
            if device is None:
                abort(404, description=f"Device {device_id} not found")
            actuator = device.get_actuator_by_id(actuator_id)
            if actuator is None:
                abort(404, description=f"Actuator {actuator_id} not found")
            action_payload = request.json if request.data else None
            if actuator.handle_action("PUT", action_payload):
                return ("", 204)
            abort(404, description=f"Actuator {actuator_id} not found")

        self._routes_configured = True

    def _sensor_to_dict(self, sensor: Sensor) -> Dict[str, Any]:
        if sensor is self._aggregate_sensor:
            with self._sensor_lock:
                return sensor.to_dict()
        return sensor.to_dict()

    @staticmethod
    def _extract_data_field(payload: Any) -> Optional[Any]:
        if isinstance(payload, dict):
            return payload.get("data")
        return None

    def _start_event_loop(self) -> None:
        if self._loop is not None and self._loop.is_running():
            return

        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()

        def _run_loop() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            if self._loop_ready is not None:
                self._loop_ready.set()
            try:
                self._loop.run_forever()
            finally:
                loop = self._loop
                if loop is not None:
                    pending = asyncio.all_tasks(loop=loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.close()

        self._loop_thread = threading.Thread(
            target=_run_loop,
            name=f"{self.id}-rest-client",
            daemon=True,
        )
        self._loop_thread.start()

        if self._loop_ready is not None:
            self._loop_ready.wait()

        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._schedule_stream_task)

    def _schedule_stream_task(self) -> None:
        if self._loop is None:
            return
        self._client_task = asyncio.create_task(self._stream_simulation_results())

    async def _stream_simulation_results(self) -> None:
        retry_interval = float(self.client_config.get("retry_interval", 5))
        while not self._stop_event.is_set():
            try:
                await self._execute_request()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Simulation bridge REST request failed: {exc}")

            if not self._stop_event.is_set():
                await asyncio.sleep(retry_interval)

    async def _execute_request(self) -> None:
        url = self.client_config["url"]
        timeout = httpx.Timeout(float(self.client_config.get("timeout", 600)))
        verify = self.client_config.get("ssl_verify", False)

        headers = {
            "Content-Type": "application/x-yaml",
            "Accept": "application/x-ndjson",
            "Authorization": f"Bearer {self._build_token()}",
        }

        async with httpx.AsyncClient(http2=True, timeout=timeout, verify=verify) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    content=self.simulation_payload_bytes,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        print(
                            "Simulation bridge REST request returned",
                            response.status_code,
                            body.decode("utf-8", errors="ignore"),
                        )
                        return

                    async for line in response.aiter_lines():
                        if self._stop_event.is_set():
                            break
                        if not line.strip():
                            continue
                        self._handle_result_line(line)
            except httpx.HTTPError as exc:
                print(f"HTTP error contacting simulation bridge at {url}: {exc}")

    def _handle_result_line(self, line: str) -> None:
        try:
            parsed = yaml.safe_load(line)
        except yaml.YAMLError:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = line

        data_payload = self._extract_data_field(parsed)
        if data_payload is None:
            return

        sensor = self._ensure_aggregate_sensor()
        if sensor is None:
            return

        with self._sensor_lock:
            sensor.last_value = data_payload
            sensor.last_update_time = 0

    def _build_token(self) -> str:
        algorithm = self.client_config.get("algorithm", "HS256")
        if algorithm != "HS256":
            raise ValueError("Only HS256 JWT signing is supported for the REST protocol")

        secret = self.client_config.get("secret", "")
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("HS256 requires JWT secret ≥ 32 characters (256 bits)")

        now = int(time.time())
        ttl = int(self.client_config.get("ttl", 900))

        payload = {
            "sub": self.client_config.get("subject", "client-123"),
            "iss": self.client_config.get("issuer", "simulation-bridge"),
            "iat": now,
            "exp": now + ttl,
        }

        return jwt.encode(payload, secret, algorithm=algorithm)

    def _resolve_path(self, relative_path: str) -> Path:
        path = Path(relative_path).expanduser()
        if not path.is_absolute():
            path = (self.base_path / path).resolve()
        return path

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"YAML file {path} did not contain a dictionary")
        return data

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
