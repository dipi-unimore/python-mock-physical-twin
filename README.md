# MockPT

MockPT is a lightweight, asynchronous Python-based simulator designed to bridge the gap between static data and live IoT ecosystems. Whether you need to simulate a fleet of sensors using historical CSV data, generate synthetic noise via statistical distributions, or pipe data from one protocol to another. MockPT helps you to build your Digital Twins.

Built on top of [Orbitalis](https://github.com/orbitalis-framework/py-orbitalis) (`asyncio`-based), it is designed for high modularity development.


## Installation

Ensure you have Python 3.12+ installed. Clone the repository and install the dependencies:

```bash
pip install -r requirements.txt
```

## CLI Running

Currently, MockPT is executed as a module through the CLI. To start the simulation with your configuration file:

```bash
python src/cli --config path/to/your_config.yaml
```

CLI Options:

- `-c, --config`: Path to your YAML configuration file (Required).
- `--log`: Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
- `--strict-config-validation`: Enable strict validation to ensure your config adheres strictly to the schema.


## User Guide

MockPT uses a declarative YAML configuration. The logic is divided into three main blocks: Destinations, Sources, and Devices.

### Destinations

Destinations define where the data goes. You define them once and reference them in your sensors.

There are different kind of destinations up to now:

- `mqtt`:	Publishes to an MQTT broker.
- `http`:	Sends a request (POST/PUT/etc).
- `local`	Writes to a local file.

#### MQTT

```py
broker_hostname: str
broker_port: int
broker_username: Optional[str] = None
broker_password: Optional[str] = None
qos: int = 2
```

#### HTTP

```py
base_url: str
method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
headers: Optional[Dict[str, str]] = None
```

#### Local

```py
directory: str
force: bool = True
append: bool = True
separator: str = "\n"
```

Directory represents the root directory based on which file are written. If directory is not empty force must be set.

By default, new content is appended to files using `separator`, but you could switch to "write" mode using `append: false`

### Sources

Sources define where the data comes from.

- `random`: Synthetic random values.
- `csv`: Reads files. 

    MQTT/HTTP: These act as "listeners." MockPT spins up a local web server (aiohttp) or an MQTT client to receive data and forward it to the designated sensors.


#### Random

```py
rv: str
interval: float
rv_params: Optional[Dict[str, Any]] = None
max: Optional[float] = None
min: Optional[float] = None
step: Optional[float] = None
```

Uses `scipy` to generate synthetic data. Example:  `uniform` distribution between `10` and `100` with a step of `0.1`


#### CSV

```py
file: str
columns: Optional[List[str]] = None
timestamp_column: Optional[str] = None
rotate: bool = True
interval: Optional[float] = None
```

`columns` to choose which columns must be used.

`rotate` is used to re-start data stream which file is fully read.

If a `timestamp_column` is provided, MockPT calculates the delta between rows and replays the data in real-time.


