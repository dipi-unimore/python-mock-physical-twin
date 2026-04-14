# MQTT and OPC UA Client to read data from OPC UA and MQTT brokers and republish to another MQTT broker on a different topic
# The application use Paho MQTT client and asyncua OPC UA client and every client run in its own thread
import asyncio
import threading
import yaml
import paho.mqtt.client as mqtt
from asyncua import Client as OpcUaClient
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration for MQTT Broker and OPC UA Server
DEFAULT_MOCKPT_BROKER_IP = "192.168.0.115"
DEFAULT_MOCKPT_BROKER_PORT = 1883
DEFAULT_MOCKPT_TARGET_TOPIC_LIST = ["device/MQTT_Device/telemetry"]
#DEFAULT_OPCUA_SERVER_URL = "opc.tcp://localhost:4840/freeopcua/server/"
DEFAULT_OPCUA_SERVER_URL = "opc.tcp://192.168.0.115/freeopcua/server/"
DEFAULT_OPCUA_NODE_IDS = ["ns=2;s=OPCUA_Device.sensor_accel"]  # Example Node IDs to monitor
DEFAULT_POLLING_INTERVAL = 2  # seconds
DEFAULT_MQTT_PUBLISH_TOPIC = "processed/data"
IS_FORWARD_TO_MQTT_ENABLED = False

# Initial Configuration
client_config = {
    "mockpt_broker_ip": DEFAULT_MOCKPT_BROKER_IP,
    "mockpt_broker_port": DEFAULT_MOCKPT_BROKER_PORT,
    "mockpt_target_topic_list": DEFAULT_MOCKPT_TARGET_TOPIC_LIST,
    "opcua_server_url": DEFAULT_OPCUA_SERVER_URL,
    "opcua_node_ids": DEFAULT_OPCUA_NODE_IDS,
    "polling_interval": DEFAULT_POLLING_INTERVAL,
    "mqtt_publish_topic": DEFAULT_MQTT_PUBLISH_TOPIC,
    "is_mqtt_forwarding_enabled": IS_FORWARD_TO_MQTT_ENABLED
}


# Load configuration from YAML file
def load_config(config_file="config.yaml"):
    logger.info(f"Loading configuration from {config_file} ...")
    try:
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
            logger.info(f"Configuration loaded successfully: {config}")
            return config
    except Exception as e:
        logger.error(f"Error loading configuration file: {e}")
        return {}

# MQTT Client Setup
def on_connect(client, userdata, flags, rc):

    if rc != 0:
        logger.error("Failed to connect to MQTT Broker")
        return

    logger.info(f"Connected to MQTT Broker with result code {rc}")

    for topic in client_config["mockpt_target_topic_list"]:
        client.subscribe(topic)
        logger.info(f"Subscribed to topic: {topic}")

def on_message(client, userdata, msg):
    logger.info(f"Received message from topic {msg.topic}: {msg.payload.decode()}")

    if client_config["is_mqtt_forwarding_enabled"]:
        # Process and republish the message to another topic
        processed_payload = f"Processed: {msg.payload.decode()}"
        client.publish(client_config["mqtt_publish_topic"], processed_payload)
        logger.info(f"Published processed message to {client_config['mqtt_publish_topic']}: {processed_payload}")

def mqtt_client_thread():
    logger.info("Starting MQTT client ...")
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(client_config["mockpt_broker_ip"], client_config["mockpt_broker_port"], 60)
    logger.info(f"MQTT client connecting to {client_config['mockpt_broker_ip']}:{client_config['mockpt_broker_port']}...")
    client.loop_forever()

# OPC UA Client Setup
# async def opcua_client_thread():
#     logger.info(f"Starting OPC UA client (Url: {client_config['opcua_server_url']}) ...")
#     async with OpcUaClient(client_config["opcua_server_url"]) as client:
#         logger.info(f"Connected to OPC UA Server: {client_config['opcua_server_url']}")
#         while True:
#             for node_id in client_config["opcua_node_ids"]:
#                 value = await client.get_node(node_id).get_value()
#                 logger.info(f"OPC UA Node {node_id} value: {value}")
#             await asyncio.sleep(client_config["polling_interval"])

async def opcua_client_thread():
    logger.info(f"Starting OPC UA client (Url: {client_config['opcua_server_url']}) ...")
    async with OpcUaClient(client_config["opcua_server_url"]) as client:
        logger.info(f"Connected to OPC UA Server: {client_config['opcua_server_url']}")
        class SubHandler:
            def datachange_notification(self, node, val, data):
                try:
                    node_id = node.nodeid.to_string()
                except Exception:
                    node_id = str(node)
                logger.info(f"OPC UA Node {node_id} value changed: {val}")
            def event_notification(self, event):
                logger.info(f"OPC UA Event: {event}")
        handler = SubHandler()
        period_ms = int(client_config.get("polling_interval", 2) * 1000)
        sub = await client.create_subscription(period_ms, handler)
        # client.get_node is synchronous; do not await it
        nodes = [client.get_node(nid) for nid in client_config["opcua_node_ids"]]
        for node in nodes:
            await sub.subscribe_data_change(node)
            logger.info(f"Subscribed to OPC UA Node data changes: {node}")
        # keep the subscription alive
        stop_event = asyncio.Event()
        await stop_event.wait()

# Start the OPC UA client in a dedicated thread
def start_opcua_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(opcua_client_thread())
    loop.close()

if __name__ == "__main__":

    logger.info("Starting MQTT and OPC UA clients ...")

    # Load configuration from file
    client_config = load_config("config.yaml")

    # If MQTT Management is enabled in the configuration, start MQTT client thread
    if client_config.get("is_mqtt_enabled", True):
        logger.info("MQTT Management is enabled.")

        # Start MQTT client thread
        mqtt_thread = threading.Thread(target=mqtt_client_thread)
        mqtt_thread.start()
    else:
        logger.info("MQTT Management is disabled.")
        mqtt_thread = None

    # If OPC UA Management is enabled in the configuration, start OPC UA client thread
    if client_config.get("is_opcua_enabled", True):

        logger.info("OPC UA Management is enabled.")

        # Start OPC UA client thread
        opcua_thread = threading.Thread(target=start_opcua_thread)
        opcua_thread.start()
    else:
        logger.info("OPC UA Management is disabled.")
        opcua_thread = None

    # Join threads if they were started
    if mqtt_thread:
        mqtt_thread.join()
    if opcua_thread:
        opcua_thread.join()

