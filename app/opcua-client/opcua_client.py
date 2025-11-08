import asyncio
import argparse
import yaml
from asyncua import Client

async def monitor(endpoint: str, node_ids: list[str], interval: float):
    async with Client(endpoint) as client:
        print(f"Connected to OPC UA server: {endpoint}")
        while True:
            for nid in node_ids:
                try:
                    node = client.get_node(nid)
                    val = await node.read_value()
                    print(f"{nid} -> {val}")
                except Exception as e:
                    print(f"Error reading {nid}: {e}")
            await asyncio.sleep(interval)

def load_node_ids_from_config(cfg_path: str, protocol_id: str | None = None) -> tuple[str, list[str]]:
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # pick first opcua protocol if protocol_id not provided
    endpoint = None
    for p in cfg.get("protocols", []):
        if p.get("type") == "opcua" and (protocol_id is None or p.get("id") == protocol_id):
            endpoint = p.get("config", {}).get("server_url")
            break
    if not endpoint:
        raise RuntimeError("No OPC UA protocol entry with server_url found in config")

    node_ids: list[str] = []
    for dev in cfg.get("devices", []):
        for s in dev.get("sensors", []):
            nid = s.get("node_id")
            if nid:
                node_ids.append(nid)
        for a in dev.get("actuators", []):
            nid = a.get("node_id")
            if nid:
                node_ids.append(nid)

    if not node_ids:
        raise RuntimeError("No node_id values found in config devices (sensors/actuators)")

    return endpoint, node_ids

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple OPC UA client to read nodes published by opcua_protocol")
    parser.add_argument("-c", "--config", default="conf\\opcua_test_config.yaml", help="Path to OPC UA config YAML")
    parser.add_argument("-p", "--protocol-id", default=None, help="Optional protocol id to select when multiple protocols present")
    parser.add_argument("-i", "--interval", type=float, default=1.0, help="Polling interval in seconds")
    args = parser.parse_args()

    endpoint, node_ids = load_node_ids_from_config(args.config, args.protocol_id)
    try:
        asyncio.run(monitor(endpoint, node_ids, args.interval))
    except KeyboardInterrupt:
        print("Stopped by user")