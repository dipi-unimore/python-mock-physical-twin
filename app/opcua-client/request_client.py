import asyncio
import yaml
from asyncua import Client, ua

class OpcUaRequestClient:
    def __init__(self, config_path: str, device_id: str, sensor_id: str):
        self.config = self._load_config(config_path)
        self.device_id = device_id
        self.sensor_id = sensor_id
        
        self.server_url = None
        self.node_id = None
        self.username = None
        self.password = None

        self._parse_common_config()
        self._parse_device_node()

    def _load_config(self, path):
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _parse_common_config(self):
        """
        Takes data from config file about server connection.
        """
        protocol_cfg = None
        for prot in self.config["protocols"]:
            if prot["type"] == "opcua":
                protocol_cfg = prot["config"]
                break

        if protocol_cfg is None:
            raise ValueError("Config error: no OPC UA protocol found.")

        self.server_url = protocol_cfg["server_url"]
        self.username = protocol_cfg.get("username")
        self.password = protocol_cfg.get("password")

    def _parse_device_node(self):
        """
        Find the node_id for the given device_id and sensor_id.
        """
        for dev in self.config["devices"]:
            if dev["id"] != self.device_id:
                continue

            for sensor in dev.get("sensors", []):
                if sensor["id"] == self.sensor_id:
                    self.node_id = sensor["node_id"]
                    return

        raise ValueError(f"Node for {self.device_id}.{self.sensor_id} not found.")

    async def connect(self):
        self.client = Client(self.server_url)
        if self.username and self.password:
            self.client.set_user(self.username)
            self.client.set_password(self.password)

        await self.client.connect()
        print(f"[CLIENT] Connected to {self.server_url}")

    async def disconnect(self):
        await self.client.disconnect()
        print("[CLIENT] Disconnected.")

    async def read_value(self):
        """
        Request-response: READ
        """
        node = self.client.get_node(self.node_id)
        value = await node.read_value()
        print(f"[CLIENT] READ {self.node_id} =", value)
        return value    

    async def request_read(self):
        await self.connect()
        await self.read_value()
        await self.disconnect()

if __name__ == "__main__":
    client = OpcUaRequestClient(
        config_path="conf\opcua_test_config.yaml",
        device_id="Device1",
        sensor_id="sensor_accel"
    )

    asyncio.run(client.request_read())