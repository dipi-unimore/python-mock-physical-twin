import asyncio
from asyncua import Client, ua


class SubHandler:
    """
    Handles data change events from the OPC UA server
    """
    def __init__(self, node_names):
        self.node_names = node_names

    def datachange_notification(self, node, val, data):
        try:
            nodeid = node.nodeid.to_string()
            name = self.node_names.get(nodeid, nodeid)
            print(f"Data Change on {name}: \nNew Value = {val}")
        except Exception as e:
            print(f"Error in datachange_notification: {e}")

    def event_notification(self, event):
        print(f"New Event: {event}")


class OPCUANodeResolver:
    """
    Explores the address space and look for all variable nodes.
    Allows to resolve node_id starting from logic name.
    Example: "numericSensor" → "ns=2;s=Device1.numericSensor"
    """
    def __init__(self, client: Client):
        self.client = client

    async def discover_all_variables(self):
        """
        Returns all VariableNode in the address space.
        """
        root = self.client.get_objects_node()
        to_visit = [root]
        variables = []

        while to_visit:
            node = to_visit.pop()
            try:
                children = await node.get_children()
            except Exception:
                continue

            for child in children:
                try:
                    node_class = await child.read_node_class()
                except Exception:
                    continue

                if node_class == ua.NodeClass.Variable:
                    variables.append(child)

                to_visit.append(child)

        return variables

    async def resolve_node_ids(self, target_names: list[str]):
        """
        Look for specified names inside the node_id.

        Example:
        target_names = ["numericSensor", "booleanSensor"]

        Returns:
        { "numericSensor": OPCUA-Node, "booleanSensor": OPCUA-Node }
        """
        all_vars = await self.discover_all_variables()
        resolved = {}

        for var in all_vars:
            nodeid_str = var.nodeid.to_string()

            # es: "ns=2;s=Device1.numericSensor"
            # here we extract "numericSensor"
            if nodeid_str.startswith("ns=") and ";s=" in nodeid_str:
                full_str = nodeid_str.split(";s=")[1]    # "Device1.numericSensor"
                short_name = full_str.split(".")[-1]     # "numericSensor"

                if short_name in target_names:
                    resolved[short_name] = var

        return resolved


class OPCUAClient:
    """
    OPC UA Client that:
    - Connects to server
    - Resolve node IDs from logical names
    - Creates subscription to monitor data changes
    - Prints updates
    """

    def __init__(self, endpoint: str, logical_node_names: list[str], publish_interval_ms: int = 500):
        self.endpoint = endpoint
        self.logical_node_names = logical_node_names
        self.publish_interval_ms = publish_interval_ms
        self.client = Client(endpoint)
        self.subscription = None

    async def run(self):
        async with self.client as client:
            print(f"Connected to OPC UA server: {self.endpoint}")

            resolver = OPCUANodeResolver(client)
            print("Resolving node IDs...")

            resolved = await resolver.resolve_node_ids(self.logical_node_names)

            if not resolved:
                print("ERROR: No matching nodes found.")
                return

            print("\nResolved nodes:")
            for name, node in resolved.items():
                print(f"  {name} -> {node.nodeid}")

            simple_names = {node.nodeid.to_string(): name for name, node in resolved.items()}
            handler = SubHandler(simple_names)

            # Create subscription
            self.subscription = await client.create_subscription(self.publish_interval_ms, handler)
            await self.subscription.subscribe_data_change(list(resolved.values()))

            print("\nMonitoring started...\n")

            # Keeps the client running
            while True:
                await asyncio.sleep(1)


if __name__ == "__main__":
    ENDPOINT = "opc.tcp://localhost:4840/freeopcua/server/"

    # SPECIFY JUST THE SENSOR NAMES, NOT the node_id
    NODES_TO_MONITOR = [
        "numericSensor",
        "booleanSensor",
        "sensor_accel"
    ]

    client = OPCUAClient(ENDPOINT, NODES_TO_MONITOR, publish_interval_ms=500)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("Stopped by user")