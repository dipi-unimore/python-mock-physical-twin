# Simulation Bridge Result Routing Configuration

> By following these guidelines you can consistently split, transform, and forward simulation bridge responses across MQTT topics, AMQP exchanges, and REST endpoints with a single declarative configuration.

This document explains the declarative routing system used by the simulation bridge protocols (`simulation_bridge_mqtt`, `simulation_bridge_rest`, and `simulation_bridge_amqp`). It covers how YAML configuration is parsed, how the dispatcher interprets the rules, and the protocol-specific fields you must provide. Every section below assumes the YAML snippet lives inside the `config` section of the protocol entry in your main emulator configuration file.

## Table of Contents

- [1. Routing Overview](#1-routing-overview)
  - [1.1 Declaring Routes Inline or from a File](#11-declaring-routes-inline-or-from-a-file)
- [2. The `when` Block (Selection)](#2-the-when-block-selection)
- [3. The `publish` Block (Dispatch)](#3-the-publish-block-dispatch)
  - [3.1 Template Tokens](#31-template-tokens)
    - [Payload Handling](#payload-handling)
- [4. MQTT Protocol (`simulation_bridge_mqtt`)](#4-mqtt-protocol-simulation_bridge_mqtt)
  - [4.1 Required Client Config](#41-required-client-config)
  - [4.2 Publishing Behavior](#42-publishing-behavior)
  - [4.3 Example](#43-example)
- [5. AMQP Protocol (`simulation_bridge_amqp`)](#5-amqp-protocol-simulation_bridge_amqp)
  - [5.1 Required Client Config](#51-required-client-config)
  - [5.2 Publishing Behavior](#52-publishing-behavior)
  - [5.3 Example](#53-example)
- [6. REST Protocol (`simulation_bridge_rest`)](#6-rest-protocol-simulation_bridge_rest)
  - [6.1 Client Configuration](#61-client-configuration)
  - [6.2 Dispatching Rules](#62-dispatching-rules)
  - [6.3 Exposing Custom HTTP Endpoints (`server_routes`)](#63-exposing-custom-http-endpoints-server_routes)
    - [Response Overrides](#response-overrides)
  - [6.4 Complete Example](#64-complete-example)
- [7. Advanced Topics](#7-advanced-topics)
  - [7.1 Relative vs Absolute Paths](#71-relative-vs-absolute-paths)
  - [7.2 Multiple Route Sources](#72-multiple-route-sources)
  - [7.3 Error Handling](#73-error-handling)
  - [7.4 Token Fallbacks](#74-token-fallbacks)
- [8. Quick Checklist](#8-quick-checklist)

## 1. Routing Overview

All three simulation bridge adapters share the same routing engine (`ResultRouter`). The engine reads a list of routing rules from the configuration and turns every incoming simulation result (specifically the `data` field of the message) into one or more outbound messages. Each rule describes:

1. **Selection** (the `when` block) – which portion of the `data` payload to work on.
2. **Dispatch** (the `publish` block) – how to format and send the derived payload to downstream consumers.

Il simulation bridge invia risultati con questa struttura, all'interno del campo data è presente il risultato della simulazione:

```json
{
  "bridge_meta": {...},
  "data": {
    "agents": [[31.7, 2.81], [8.19, 8.38]],
    "distance": 2.04,
    "step": 199
  },
  "status": "streaming",
  "request_id": "abcdef12345"
}
```

the router receives only the `data` block (`{"agents": ..., "distance": ..., "step": ...}`) and evaluates the configured rules against that JSON structure.

### 1.1 Declaring Routes Inline or from a File

Routes can be provided in two ways:

- Directly under `config.routes` (list or a file path).
- Via `config.routes_file` pointing to a YAML document whose root contains a `routes` list.

Example:

```yaml
config:
  routes:
    - when: { type: "all" }
      publish: { topic: "sim/data" }

  # or external file
  routes_file: "conf/custom_routes.yaml"
```

If both values are present, the lists are concatenated (inline routes first, then file routes).

## 2. The `when` Block (Selection)

`when` determines which fragment of the `data` object the rule operates on.

| Field     | Type   | Required           | Description                                                                       |
| --------- | ------ | ------------------ | --------------------------------------------------------------------------------- |
| `type`    | string | No (default `all`) | `all` returns the full `data` object. `json_path` extracts a nested value.        |
| `path`    | string | For `json_path`    | Dot-separated traversal path. Examples: `agents`, `agents.0`, `agents.positions`. |
| `foreach` | bool   | No                 | When `true`, iterates items of an array/dict at the selected path.                |

- **type `all`** – the entire `data` payload is passed to `publish`.
- **type `json_path`** – the router walks the JSON using a simple dot notation. Arrays can be addressed with numeric components (`"agents.0"`).
- **`foreach: true`** – each element of a list (or key/value pair of a dict) becomes its own message.

If the path does not exist, the rule emits no messages but does not throw an error.

## 3. The `publish` Block (Dispatch)

This block is protocol-agnostic; unsupported keys for a given protocol are ignored. Common fields include:

| Field          | Type   | Description                                                                                   |
| -------------- | ------ | --------------------------------------------------------------------------------------------- |
| `payload`      | any    | Template for the outbound payload (string, dict, list, etc.). Defaults to the selected value. |
| `topic`        | string | MQTT topic or AMQP routing key (fallback). Required for MQTT rules.                           |
| `url`          | string | REST target URL. Either absolute or relative to the server’s `dispatch_base_url`.             |
| `method`       | string | HTTP verb (default `POST`).                                                                   |
| `headers`      | dict   | Extra HTTP headers (stringified).                                                             |
| `routing_key`  | string | AMQP routing key override (otherwise `topic` is used).                                        |
| `exchange`     | string | AMQP exchange override (default is the configured bridge-result exchange).                    |
| `qos`          | int    | MQTT QoS (0, 1, or 2). Falls back to client default if omitted or invalid.                    |
| `retain`       | bool   | MQTT retained message flag.                                                                   |
| `persistent`   | bool   | AMQP delivery mode (true → `delivery_mode=2`).                                                |
| `content_type` | string | Sets `content-type` header for AMQP or overrides HTTP `Content-Type`.                         |

### 3.1 Template Tokens

Both `payload` and address fields support templating. The router injects tokens derived from the selected value and iteration context:

| Token     | Description                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------- |
| `{raw}`   | JSON-encoded fragment currently processed. Useful for forwarding the original structure verbatim. |
| `{value}` | Compact string representation of the selection (no surrounding quotes for scalars).               |
| `{root}`  | JSON dump of the entire `data` object (same as the rule input).                                   |
| `{index}` | When `foreach` is true, the integer iteration index.                                              |
| `{key}`   | When iterating dict entries, the stringified dictionary key.                                      |

Additionally, positional tokens `{0}`, `{1}`, … are available when the selected value is an array or tuple. For example, with an `agents` list of `[x, y]` pairs:

```yaml
payload: "{"x": "{0}", "y": "{1}"}"
```

If the selected value is a scalar, `{0}` expands to the scalar value.

#### Payload Handling

- If `payload` is a string, it is treated as a template.
- If `payload` is a dict or list, each nested value is templated, then the structure is serialized as JSON.
- If `payload` is omitted, the router emits the selected fragment directly. Non-string types are serialized as JSON.

## 4. MQTT Protocol (`simulation_bridge_mqtt`)

### 4.1 Required Client Config

`client_config.mqtt` must include `host`, `port`, `input_topic`, and `output_topic`. The router only publishes to topics defined in route rules.

### 4.2 Publishing Behavior

- For every message emitted by `publish.topic`, the protocol sends `client.publish(topic, payload, qos, retain)`.
- `qos` defaults to the client’s configured QoS and is clamped between 0 and 2.
- `retain` defaults to `false` unless specified.
- Messages lacking a `topic` are skipped (warning printed).

### 4.3 Example

```yaml
config:
  client_config:
    mqtt:
      host: localhost
      port: 1883
      input_topic: bridge/input
      output_topic: bridge/output
  simulation_api: simulation.yaml
  routes:
    - when: { type: "all" }
      publish:
        topic: "sim/data"
        payload: "{raw}"
    - when:
        type: "json_path"
        path: "agents"
        foreach: true
      publish:
        topic: "sim/agents/{index}"
        payload:
          x: "{0}"
          y: "{1}"
    - when:
        type: "json_path"
        path: "distance"
      publish:
        topic: "sim/distance"
        payload: "{value}"
```

## 5. AMQP Protocol (`simulation_bridge_amqp`)

### 5.1 Required Client Config

Ensure `client_config` defines:

- `rabbitmq` connection (host, port, vhost, username/password, TLS if needed).
- `exchanges` (maps `input_bridge` and `bridge_result`).
- `queue` definition for consuming results (router does not modify this).
- `digital_twin.routing_key_send` for sending simulation requests.

### 5.2 Publishing Behavior

When a route emits a message:

- `routing_key` uses `publish.routing_key` or falls back to `publish.topic`.
- `exchange` defaults to the configured bridge-result exchange unless overridden.
- `payload` is encoded as UTF-8 bytes.
- `persistent` → AMQP delivery mode (`delivery_mode=2` when true/unspecified, else `1`).
- `content_type` defaults to `application/json` but can be overridden.
- Arbitrary headers are allowed through `publish.headers` and stored inside `BasicProperties`.

### 5.3 Example

```yaml
config:
  client_config:
    rabbitmq:
      host: localhost
      port: 5672
      username: guest
      password: guest
    exchanges:
      bridge_result:
        name: ex.bridge.result
        type: topic
  simulation_api: simulation.yaml
  routes:
    - when: { type: "all" }
      publish:
        exchange: "ex.bridge.result"
        routing_key: "sim.data"
        payload: "{raw}"
    - when:
        type: "json_path"
        path: "agents"
        foreach: true
      publish:
        exchange: "ex.bridge.result"
        routing_key: "sim.agent.{index}"
        payload:
          x: "{0}"
          y: "{1}"
    - when:
        type: "json_path"
        path: "step"
      publish:
        exchange: "ex.bridge.result"
        routing_key: "sim.step"
        payload: "{value}"
        persistent: false
        headers:
          source: "router"
```

## 6. REST Protocol (`simulation_bridge_rest`)

The REST adapter both consumes streaming updates and optionally exposes local HTTP endpoints. Configuration is more extensive.

### 6.1 Client Configuration

The standard `client_config` block provides the bridge endpoint URL, JWT settings, timeouts, etc. These fields are unchanged from the legacy implementation.

### 6.2 Dispatching Rules

- Each message requires a `publish.url`. URLs can be absolute (`https://api.example/v1`) or relative (`/sim/data`).
- Relative URLs are resolved against `dispatch_base_url` if configured; otherwise the protocol derives `http://{server_host}:{server_port}` (substituting `127.0.0.1` for `0.0.0.0`).
- `method` defaults to `POST`.
- `headers` are merged into the outbound request; a `Content-Type` header is added automatically if missing, using `publish.content_type` or `application/json`.
- Any HTTP errors are logged but do not stop routing.

### 6.3 Exposing Custom HTTP Endpoints (`server_routes`)

By default, the REST adapter creates a complete set of device introspection endpoints (`/devices`, `/devices/<id>`, etc.). To disable or extend this surface, use the `server_routes` block:

```yaml
config:
  server_port: 9001
  server_routes:
    defaults: false # omit the legacy endpoints entirely
    routes:
      - path: "/sim/data"
        methods: ["GET", "POST"]
        store_last: true
      - path: "/sim/agents/<int:index>"
        methods: ["GET", "POST"]
        store_last: true
        response:
          default:
            status_code: 204
```

Parameters:

| Field         | Type        | Description                                                                                                 |
| ------------- | ----------- | ----------------------------------------------------------------------------------------------------------- |
| `defaults`    | bool        | Set to `false` to skip registering the stock `/devices` routes.                                             |
| `routes`      | list        | Custom endpoints definitions. Each entry must include a `path`.                                             |
| `path`        | string      | Flask-style route (supports converters such as `<int:index>`).                                              |
| `methods`     | list/string | Allowed HTTP methods. Defaults to `POST`. Methods are uppercased automatically.                             |
| `store_last`  | bool        | When true, the server stores the body of `POST`/`PUT`/`PATCH` requests and returns it on subsequent `GET`s. |
| `log_payload` | bool        | Prints every stored payload to stdout (useful for debugging).                                               |
| `endpoint`    | string      | Optional Flask endpoint name; defaults to `simulationBridge-custom-{index}` to remain unique.               |
| `response`    | dict        | Static response overrides per method or shared defaults. See below.                                         |

#### Response Overrides

Each entry in `response` can be either:

- Method-specific (`post`, `get`, `default`, case-insensitive) pointing to a dict with:
  - `status_code` – HTTP status code (default varies by method; typically 204 for writes, 200 for reads when stored data exists).
  - `body` – Literal response body (string/dict/list). JSON is automatically encoded.
  - `headers` – Map of additional response headers.
  - `content_type` – Overrides the response content type.

`store_last: true` makes the handler behave like a simple in-memory key-value store: writing JSON via POST and reading it back with GET.

### 6.4 Complete Example

```yaml
config:
  server_host: 0.0.0.0
  server_port: 9001
  dispatch_base_url: "http://localhost:9001"
  client_config:
    url: "https://127.0.0.1:5000/message"
    secret: "CHANGE_ME_TO_A_LONG_RANDOM_VALUE"
  routes:
    - when: { type: "all" }
      publish:
        url: "/sim/data"
        method: "post"
        payload: "{raw}"
    - when:
        type: "json_path"
        path: "agents"
        foreach: true
      publish:
        url: "/sim/agents/{index}"
        method: "post"
        payload:
          x: "{0}"
          y: "{1}"
    - when:
        type: "json_path"
        path: "distance"
      publish:
        url: "/sim/distance"
        method: "post"
        payload: "{value}"
  server_routes:
    defaults: false
    routes:
      - path: "/sim/data"
        methods: ["GET", "POST"]
        store_last: true
      - path: "/sim/agents/<int:index>"
        methods: ["GET", "POST"]
        store_last: true
```

With this setup the emulator will expose `/sim/data`, `/sim/agents/<index>`, `/sim/distance`, and `/sim/step` locally, and the router’s outbound HTTP dispatch will hit those same endpoints without returning 404 errors.

## 7. Advanced Topics

### Relative vs Absolute Paths

- Relative paths in `when.path` are not full JSONPath; only dot notation with numeric indices is supported.
- Relative URLs in `publish.url` are converted at runtime. If `dispatch_base_url` is absent and the derived base uses `0.0.0.0`, the scheme becomes `http://127.0.0.1:{port}`.

### Multiple Route Sources

If you maintain shared route templates, split them into separate YAML files and reference them via `routes_file`. The loader merges them sequentially, so you can ship a common base and override with inline tweaks per environment.

### Error Handling

- **Parsing**: Invalid YAML or structural errors (non-dict routes, missing `path`) raise `InvalidConfigurationError` during protocol initialization.
- **Dispatch**: Exceptions thrown by MQTT or AMQP clients are caught and logged to stdout; execution continues with the next message.
- **HTTP**: Failed requests produce a warning but do not raise.

### Token Fallbacks

Unrecognized placeholders remain untouched in the output (e.g., `{unknown}` stays `{unknown}`). This makes it easy to spot mis-typed template tokens during testing.
