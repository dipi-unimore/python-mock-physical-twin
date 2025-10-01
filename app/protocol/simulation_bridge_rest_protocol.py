"""Simulation Bridge protocol that exchanges messages through REST over HTTP/2."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import MethodType
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
import jwt
import yaml

from flask import Flask, abort, jsonify, make_response, request

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

        server_routes_cfg = self.config.get("server_routes")
        self._server_routes_defaults: bool = True
        self._custom_server_routes: List[Dict[str, Any]] = []
        if server_routes_cfg is not None:
            if not isinstance(server_routes_cfg, dict):
                raise InvalidConfigurationError(["server_routes"])
            self._server_routes_defaults = bool(server_routes_cfg.get("defaults", True))
            routes_value = server_routes_cfg.get("routes") or []
            if not isinstance(routes_value, list):
                raise InvalidConfigurationError(["server_routes.routes"])
            for index, route_cfg in enumerate(routes_value):
                if not isinstance(route_cfg, dict):
                    raise InvalidConfigurationError([f"server_routes.routes[{index}]"])
                self._custom_server_routes.append(dict(route_cfg))

        self._custom_route_storage: Dict[str, Dict[str, Any]] = {}
        self._custom_route_lock = threading.Lock()

        self._router = self._build_router()

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

        dispatch_base_value = self.config.get("dispatch_base_url")
        if isinstance(dispatch_base_value, str) and dispatch_base_value:
            self._dispatch_base_url = dispatch_base_value.rstrip("/")
        elif self._server_port is not None:
            host_for_dispatch = self._server_host
            if host_for_dispatch in {"0.0.0.0", "::"}:
                host_for_dispatch = "127.0.0.1"
            self._dispatch_base_url = f"http://{host_for_dispatch}:{self._server_port}"
        else:
            self._dispatch_base_url = None

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

        server_routes_cfg = self.config.get("server_routes")
        if server_routes_cfg is not None:
            if not isinstance(server_routes_cfg, dict):
                raise InvalidConfigurationError(["server_routes"])
            routes_cfg = server_routes_cfg.get("routes")
            if routes_cfg is not None and not isinstance(routes_cfg, list):
                raise InvalidConfigurationError(["server_routes.routes"])
            if isinstance(routes_cfg, list):
                for index, route_cfg in enumerate(routes_cfg):
                    if not isinstance(route_cfg, dict):
                        raise InvalidConfigurationError([f"server_routes.routes[{index}]"])
                    path_value = route_cfg.get("path")
                    if not isinstance(path_value, str) or not path_value:
                        raise InvalidConfigurationError([f"server_routes.routes[{index}].path"])
                    methods_value = route_cfg.get("methods")
                    if methods_value is not None:
                        if isinstance(methods_value, str):
                            pass
                        elif isinstance(methods_value, (list, tuple)):
                            if not all(isinstance(item, str) for item in methods_value):
                                raise InvalidConfigurationError(
                                    [f"server_routes.routes[{index}].methods"]
                                )
                        else:
                            raise InvalidConfigurationError([f"server_routes.routes[{index}].methods"])

        dispatch_base_url = self.config.get("dispatch_base_url")
        if dispatch_base_url is not None and not isinstance(dispatch_base_url, str):
            raise InvalidConfigurationError(["dispatch_base_url"])

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

        if self._server_routes_defaults:
            self._register_default_routes()

        if self._custom_server_routes:
            self._register_custom_routes(self._custom_server_routes)

        self._routes_configured = True

    def _register_default_routes(self) -> None:
        assert self.app is not None
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

    def _register_custom_routes(self, routes_config: List[Dict[str, Any]]) -> None:
        assert self.app is not None
        app = self.app

        for index, route_config in enumerate(routes_config):
            path_value = route_config.get("path")
            if not isinstance(path_value, str) or not path_value:
                print(
                    f"Skipping custom server route at index {index}: missing or invalid 'path'"
                )
                continue

            methods_value = route_config.get("methods")
            if methods_value is None:
                methods = ["POST"]
            elif isinstance(methods_value, str):
                methods = [methods_value]
            else:
                methods = [str(method) for method in methods_value if isinstance(method, str)]
                if not methods:
                    methods = ["POST"]
            methods = [method.upper() for method in methods]

            endpoint_value = route_config.get("endpoint")
            if not isinstance(endpoint_value, str) or not endpoint_value:
                endpoint_value = f"{self.id}-custom-{index}"

            handler = self._build_custom_route_handler(path_value, methods, route_config)

            try:
                app.add_url_rule(
                    path_value,
                    endpoint=endpoint_value,
                    view_func=handler,
                    methods=methods,
                )
            except AssertionError:
                print(
                    f"Custom server route '{path_value}' already registered, skipping duplicate"
                )

    def _build_custom_route_handler(
        self,
        path: str,
        methods: List[str],
        route_config: Dict[str, Any],
    ) -> Callable[..., Any]:
        store_last = bool(route_config.get("store_last", False))
        response_cfg = route_config.get("response")
        log_payload = bool(route_config.get("log_payload", False))
        store_methods = {"POST", "PUT", "PATCH"}

        def handler(**kwargs):  # type: ignore[override]
            method = request.method.upper()

            if method in store_methods:
                payload, is_json, content_type = self._extract_request_payload()
                if store_last:
                    self._store_custom_route_value(request.path, payload, is_json, content_type)
                if log_payload:
                    try:
                        formatted = json.dumps(payload, ensure_ascii=False)
                    except TypeError:
                        formatted = str(payload)
                    print(f"[simulation_bridge_rest] Stored payload for {request.path}: {formatted}")
                return self._respond_with_config(response_cfg, method, default_status=204)

            if method == "DELETE":
                if store_last:
                    self._remove_custom_route_value(request.path)
                return self._respond_with_config(response_cfg, method, default_status=204)

            if method == "GET":
                response_cfg_get = self._select_response_config(response_cfg, method)
                if store_last:
                    stored_payload = self._get_custom_route_value(request.path)
                    if stored_payload is not None:
                        if response_cfg_get and "body" in response_cfg_get:
                            return self._make_response_from_config(response_cfg_get, default_status=200)
                        status_code = int((response_cfg_get or {}).get("status_code", 200))
                        headers = (response_cfg_get or {}).get("headers")
                        return self._make_stored_response(stored_payload, status_code, headers)
                return self._make_response_from_config(response_cfg_get, default_status=204)

            return self._respond_with_config(response_cfg, method, default_status=204)

        handler.__name__ = route_config.get(
            "endpoint", f"custom_route_handler_{hash(path)}_{id(route_config)}"
        )
        return handler

    def _respond_with_config(
        self,
        response_cfg: Any,
        method: str,
        default_status: int,
    ) -> Any:
        config = self._select_response_config(response_cfg, method)
        return self._make_response_from_config(config, default_status)

    @staticmethod
    def _select_response_config(response_cfg: Any, method: str) -> Optional[Dict[str, Any]]:
        if not isinstance(response_cfg, dict):
            return None

        simple_keys = {"body", "status_code", "headers", "content_type"}
        method_lower = method.lower()

        for key, value in response_cfg.items():
            if isinstance(key, str) and key.lower() == method_lower and isinstance(value, dict):
                return value

        for key, value in response_cfg.items():
            if isinstance(key, str) and key.lower() == "default" and isinstance(value, dict):
                return value

        if simple_keys.intersection(response_cfg.keys()):
            return {
                key: response_cfg[key]
                for key in simple_keys
                if key in response_cfg
            }

        return None

    def _make_response_from_config(
        self,
        config: Optional[Dict[str, Any]],
        default_status: int,
    ) -> Any:
        if config is None:
            return self._make_flask_response("", default_status)

        status_code = int(config.get("status_code", default_status))
        body = config.get("body")
        headers = config.get("headers")
        content_type = config.get("content_type")
        return self._make_flask_response(body, status_code, headers, content_type)

    def _make_stored_response(
        self,
        stored: Dict[str, Any],
        status_code: int,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload = stored.get("payload")
        is_json = stored.get("is_json", False)
        content_type = stored.get("content_type")

        if is_json:
            response = jsonify(payload)
        else:
            body = payload if payload is not None else ""
            response = make_response(body)
            if content_type:
                response.headers["Content-Type"] = content_type

        response.status_code = status_code

        if headers and isinstance(headers, dict):
            for key, value in headers.items():
                response.headers[str(key)] = str(value)

        return response

    def _make_flask_response(
        self,
        body: Any,
        status_code: int,
        headers: Optional[Dict[str, Any]] = None,
        content_type: Optional[str] = None,
    ) -> Any:
        if isinstance(body, (dict, list)):
            response = jsonify(body)
        elif isinstance(body, bytes):
            response = make_response(body)
        else:
            response = make_response("" if body is None else str(body))

        response.status_code = status_code

        if content_type:
            response.headers["Content-Type"] = content_type

        if headers and isinstance(headers, dict):
            for key, value in headers.items():
                response.headers[str(key)] = str(value)

        return response

    def _extract_request_payload(self) -> Tuple[Any, bool, Optional[str]]:
        if request.is_json:
            payload = request.get_json(silent=True)
            return payload, True, "application/json"

        data = request.get_data()
        if not data:
            return "", False, request.mimetype

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data, False, request.mimetype

        try:
            parsed = json.loads(text)
            return parsed, True, "application/json"
        except json.JSONDecodeError:
            return text, False, request.mimetype or "text/plain"

    def _store_custom_route_value(
        self,
        key: str,
        payload: Any,
        is_json: bool,
        content_type: Optional[str],
    ) -> None:
        with self._custom_route_lock:
            self._custom_route_storage[key] = {
                "payload": payload,
                "is_json": is_json,
                "content_type": content_type,
            }

    def _get_custom_route_value(self, key: str) -> Optional[Dict[str, Any]]:
        with self._custom_route_lock:
            stored = self._custom_route_storage.get(key)
            return dict(stored) if stored is not None else None

    def _remove_custom_route_value(self, key: str) -> None:
        with self._custom_route_lock:
            self._custom_route_storage.pop(key, None)

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
                        await self._handle_result_line(line)
            except httpx.HTTPError as exc:
                print(f"HTTP error contacting simulation bridge at {url}: {exc}")

    async def _handle_result_line(self, line: str) -> None:
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

        await self._dispatch_routes(data_payload)

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

    async def _dispatch_routes(self, data_payload: Any) -> None:
        router = getattr(self, "_router", None)
        if router is None or not router.has_routes:
            return

        messages = [message for message in router.dispatch(data_payload) if message.url]
        if not messages:
            return

        timeout_value = float(self.client_config.get("dispatch_timeout", 30))
        timeout = httpx.Timeout(timeout_value)

        async with httpx.AsyncClient(timeout=timeout, verify=self.client_config.get("ssl_verify", False)) as client:
            for message in messages:
                method = (message.method or "POST").upper()
                headers = {}
                if message.headers:
                    headers.update({str(key): str(value) for key, value in message.headers.items()})
                content_type = message.content_type or "application/json"
                if not any(key.lower() == "content-type" for key in headers):
                    headers["Content-Type"] = content_type

                target_url = message.url
                if not target_url:
                    continue
                parsed = urlparse(target_url)
                if not parsed.scheme:
                    base_url = self._dispatch_base_url
                    if not base_url:
                        print(
                            f"Failed to dispatch routed HTTP message: relative URL {target_url}"
                            " and no dispatch_base_url configured"
                        )
                        continue
                    target_url = urljoin(f"{base_url}/", target_url.lstrip("/"))

                try:
                    await client.request(
                        method,
                        target_url,
                        headers=headers,
                        content=message.payload,
                    )
                except httpx.HTTPError as exc:  # pragma: no cover - network error path
                    print(f"Failed to dispatch routed HTTP message to {target_url}: {exc}")

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
