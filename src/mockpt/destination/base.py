from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from busline.event.event import Event
from orbitalis.plugin.plugin import Plugin
from orbitalis.plugin.operation import Policy
from orbitalis.plugin.operation import operation
from orbitalis.orbiter.schemaspec import Input, Output
from busline.event.message.avro_message import AvroMessageMixin

from mockpt.common.data_message import DataMessage
from mockpt.common.send_message import SendMessage


class DestinationBaseConfig(BaseModel):
    type: str = Field(frozen=True)
    description: Optional[str] = None



@dataclass
class DestinationBase(Plugin, ABC):
    config: DestinationBaseConfig

    @property
    def destination_identifier(self) -> str:
        return self.identifier

    @operation(
        name="send",
        input=SendMessage,
        output=Output.no_output(),
        default_policy=Policy.no_constraints()
    )
    async def send(self, topic: str, event: Event[SendMessage]):
        assert event.payload is not None, "Payload must be provided for send operation"
        await self._send(event.payload.endpoint, event.payload.data)

    @abstractmethod
    async def _send(self, endpoint: str, data: DataMessage):
        pass

    




