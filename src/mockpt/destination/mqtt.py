import logging
from typing import Literal, Optional, List, Any, Dict
from dataclasses import dataclass, field
import aiomqtt
from contextlib import AsyncExitStack

from mockpt.destination.enum import DestinationName 
from mockpt.destination.base import DestinationBase, DestinationBaseConfig
from mockpt.common.data_message import DataMessage


class MqttDestinationConfig(DestinationBaseConfig):
    type: Literal[DestinationName.MQTT.value] = DestinationName.MQTT.value # type: ignore
    broker_hostname: str
    broker_port: int
    broker_username: Optional[str] = None
    broker_password: Optional[str] = None
    qos: int = 2


@dataclass
class MqttDestination(DestinationBase):
    config: MqttDestinationConfig # type: ignore
    mqtt_client: aiomqtt.Client | None = None
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)

    def __post_init__(self):
        super().__post_init__()

    async def _on_starting(self, *args, **kwargs):
        await super()._on_starting(*args, **kwargs)
        
        client = aiomqtt.Client(
            hostname=self.config.broker_hostname, 
            port=self.config.broker_port,
            username=self.config.broker_username,
            password=self.config.broker_password
        )
        
        # Enter the aiomqtt context manager and keep the connection open
        self.mqtt_client = await self._exit_stack.enter_async_context(client)
        
    async def _on_stopping(self, *args, **kwargs):
        # Close the ExitStack, which will in turn close the connection to the broker cleanly
        if self._exit_stack:
            await self._exit_stack.aclose()
            self.mqtt_client = None
            
        await super()._on_stopping(*args, **kwargs)

    async def _send(self, endpoint: str, data: DataMessage):
        if self.mqtt_client is None:
            raise RuntimeError("MQTT client is not connected.")
        
        try:
            await self.mqtt_client.publish(
                topic=endpoint, 
                payload=data.json_value,
                qos=self.config.qos
            )
        except Exception as e:
            logging.error(f"Failed to publish message to {endpoint}: {e}")






