from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.device.iot_device import IoTDevice
    from typing import Dict

from app.protocol.protocol import Protocol, validate_dict_keys, InvalidConfigurationError
from app.utils.emulator_utils import ProtocolType
from asyncua import Server, ua
import asyncio
import threading
import json
import logging
from datetime import datetime

class OpcUaProtocol(Protocol):
    def __init__(self,
                protocol_id,
                device_dict: Dict[str, IoTDevice] = None,
                config: Dict = None):
        super().__init__(protocol_id, ProtocolType.OPCUA_PROTOCOL_TYPE, device_dict, config)
        
        self.server_url = self.config['server_url']
        self.server_name = self.config['server_name']
        self.namespace = self.config['namespace']
        self.username = self.config['username']
        self.password = self.config['password']
        
        self.server = None
        self.nodes = {}
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def start(self):
        print(f'Starting protocol: {self.id} Type: {self.type}')
        print(f'Initializing OPC UA server...')

        # Starts server in a dedicated thread
        server_thread = threading.Thread(target=self._run_server_loop, daemon=True)
        server_thread.start()

    def _run_server_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start_server())
        # Keeps the loop alive to handle incoming requests
        self.loop.run_forever()
        
    async def _start_server(self):
        self.server = Server()
        await self.server.init()
        
        self.server.set_endpoint(self.server_url)
        self.server.set_server_name(self.server_name)
        
        # Register namespace
        namespace_idx = await self.server.register_namespace(self.namespace)
        
        # Create nodes for all devices and their sensors/actuators
        for device in self.device_dict.values():
            # Create device folder
            device_folder = await self.server.nodes.objects.add_folder(
                namespace_idx, 
                f"{device.id}"
            )
            
            # Create nodes for sensors
            for sensor in device.sensors:
                nodeid_str = f"{device.id}.{sensor.id}"
                nodeid = ua.NodeId(nodeid_str, namespace_idx)
                
                value = sensor.current_value()
                variant_type = OpcUaProtocol._get_variant_type_from_value(value)
                variant_value = ua.Variant(value, variant_type)

                node = await device_folder.add_variable(
                    nodeid,
                    sensor.id,
                    variant_value
                )
                self.nodes[f"{device.id}.{sensor.id}"] = node
                await node.set_writable()
            
            # Create nodes for actuators
            for actuator in device.actuators:
                nodeid_str = f"{device.id}.{actuator.id}"
                nodeid = ua.NodeId(nodeid_str, namespace_idx)

                value = actuator.current_value
                variant_type = OpcUaProtocol._get_variant_type_from_value(value)
                variant_value = ua.Variant(value, variant_type)

                node = await device_folder.add_variable(
                    nodeid,
                    actuator.id,
                    variant_value
                )
                self.nodes[f"{device.id}.{actuator.id}"] = node
                await node.set_writable()
        
        await self.server.start()
        print(f'OPC UA Server started at {self.server_url}')    

    def stop(self):
        print(f'Stopping protocol: {self.id} Type: {self.type}')

        async def _shutdown():
            if self.server:
                await self.server.stop()
            self.loop.stop()

        asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)

        print(f'OPC UA Server stopped')

    def validate_config(self):
        required_keys = ["server_url", "server_name", "namespace"]
        if not validate_dict_keys(self.config, required_keys):
            raise InvalidConfigurationError(required_keys)

    def publish_sensor_telemetry_data(self, device_id, sensor_id, payload):        
        node_key = f"{device_id}.{sensor_id}"
        if node_key in self.nodes:
            asyncio.run_coroutine_threadsafe(
                self._update_node_value(self.nodes[node_key], payload),
                self.loop
            )
            #print(f"[DEBUG OPCUA] Scheduled update for node {node_key} -> {payload}")
        # else:
        #     print(f"[WARN OPCUA] Node {node_key} not found, skipping update.")

    def publish_device_telemetry_data(self, device_id, payload):
        # For OPC UA, we update individual sensor nodes instead of publishing device-level data
        #print(f"[DEBUG OPCUA] publish_device_telemetry_data called for {device_id}: {payload}")

        # Decode payload if it's a JSON string
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
                for sensor_id, value in payload.items():
                    self.publish_sensor_telemetry_data(device_id, sensor_id, value)
                #print(f"[DEBUG OPCUA] Decoded JSON payload: {payload}")
            except json.JSONDecodeError as e:
                print(f"[ERROR OPCUA] Failed to decode payload JSON: {e}")
                return

    async def _update_node_value(self, node, value):
        try:
            data_type = await node.read_data_type_as_variant_type()
            
            if isinstance(value, dict):
                value = json.dumps(value)
            if data_type == ua.VariantType.Int64 and isinstance(value, float):
                value = int(value)
            elif data_type == ua.VariantType.Double and isinstance(value, int):
                value = float(value)
            await node.write_value(value)
            #print(f"[OPCUA] Updating node {node} -> {value}")
        except Exception as e:
            print(f"Error updating node value: {str(e)}")

    async def _handle_actuator_change(self, value, actuator):
        # Handle actuator value changes from OPC UA clients
        actuator.handle_action("OPCUA_ACTION", value)
        return value
    
    @staticmethod
    def _get_variant_type_from_value(value):
        """Returns OPC UA type correspondant to Python type."""
        if isinstance(value, bool):
            return ua.VariantType.Boolean
        elif isinstance(value, int):
            return ua.VariantType.Int64
        elif isinstance(value, float):
            return ua.VariantType.Double
        elif isinstance(value, str):
            return ua.VariantType.String
        elif isinstance(value, dict):
            # For JSON types, we use String representation
            return ua.VariantType.String
        else:
            return ua.VariantType.String