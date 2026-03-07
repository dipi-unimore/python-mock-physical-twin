import asyncio
from typing import AsyncGenerator, Optional, Dict, Any
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from busline.event.event import Event
from orbitalis.plugin.plugin import Plugin
from orbitalis.plugin.operation import Policy
from orbitalis.plugin.operation import operation
from orbitalis.orbiter.schemaspec import Input
from busline.event.message.avro_message import AvroMessageMixin

from mockpt.common import id_wrapper
from mockpt.common.data_message import DataMessage
from mockpt.common.operation_name import OperationName


class SourceBaseConfig(BaseModel):
    type: str = Field(frozen=True)
    description: Optional[str] = None


@dataclass
class SourceBase(Plugin, ABC):
    config: SourceBaseConfig
    _push_loop_task: asyncio.Task = field(init=False)
    _stop_push_loop: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    @property
    def source_identifier(self) -> str:
        return self.identifier
    
    def turn_on_datastream(self):
        self._stop_push_loop.clear()
        self._push_loop_task = asyncio.create_task(self._push_loop())
        
    def turn_off_datastream(self):
        self._stop_push_loop.set()
    
    @operation(
        name=OperationName.NEXT,
        input=Input.no_input(),
        output=DataMessage,
        default_policy=Policy.no_constraints()
    )
    async def next(self, topic: str, event: Event):
        pass    # nothing to do, it is declared just to define the operation and its input/output

    
    async def _push(self, data_message: DataMessage):

        await self.eventbus_client.multi_publish(
            topics=[str(connections[OperationName.NEXT].output_topic) for connections in self._connections.values() if connections[OperationName.NEXT].has_output],
            message=data_message
        )
        
    # TODO: nuova operazione per ottenere la risposta dal device

    
    @abstractmethod
    async def _datastream(self) -> AsyncGenerator[Dict[str, Any], None]:
        yield {}    # dummy yield to make this an async generator, to be overridden by subclasses
    
    async def _push_loop(self):
        while not self._stop_push_loop.is_set():
            async for data in self._datastream():
                await self._push(DataMessage.of(
                    source_identifier=self.source_identifier,
                    value=data
                ))
    




