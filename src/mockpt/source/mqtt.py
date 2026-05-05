import asyncio
import logging
from typing import Literal, Optional, List, Any, Dict, override
import aiomqtt
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.datastream_mixin import DataStreamMixin
from mockpt.source.enum import SourceName


class MqttSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.MQTT.value] = SourceName.MQTT.value # type: ignore
    topics: str | List[str]
    broker_hostname: str = "localhost"
    broker_port: int = 1883
    broker_username: Optional[str] = None
    broker_password: Optional[str] = None


@dataclass
class MqttSource(DataStreamMixin, SourceBase):
    config: MqttSourceConfig # type: ignore
    mqtt_client: aiomqtt.Client = field(init=False)
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)
    
    
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
        
        if isinstance(self.config.topics, str):
            await self.mqtt_client.subscribe(self.config.topics)
        else:
            for topic in self.config.topics:
                await self.mqtt_client.subscribe(topic)

    async def _on_stopping(self, *args, **kwargs):
        # Close the ExitStack, which will in turn close the connection to the broker cleanly
        if self._exit_stack:
            await self._exit_stack.aclose()
            self.mqtt_client = None # type: ignore
            
        await super()._on_stopping(*args, **kwargs)

    @override
    async def _datastream(self):
        try:
            async for message in self.mqtt_client.messages:
                payload = message.payload.decode()
                await self._data_queue.put({
                    "value": payload
                })
                
        except Exception as e:
            logging.error(f"Error in MQTT datastream: {e}")
