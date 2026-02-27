from typing import Literal, Optional, List, Any, Dict
import aiomqtt
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig


class MqttSourceConfig(SourceBaseConfig):
    type: Literal["mqtt"] = "mqtt" # type: ignore
    topic: str
    broker_hostname: str
    broker_port: int
    broker_username: Optional[str] = None
    broker_password: Optional[str] = None


@dataclass
class MqttSource(SourceBase):
    config: MqttSourceConfig # type: ignore
    mqtt_client: aiomqtt.Client | None = None
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
        
    async def _on_stopping(self, *args, **kwargs):
        # Close the ExitStack, which will in turn close the connection to the broker cleanly
        if self._exit_stack:
            await self._exit_stack.aclose()
            self.mqtt_client = None
            
        await super()._on_stopping(*args, **kwargs)


    # async def _next(self):

    #     # TODO
