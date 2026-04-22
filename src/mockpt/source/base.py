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
from mockpt.common.message.data_message import DataMessage
from mockpt.common.message.response_message import ResponseMessage
from mockpt.common.operation_name import OperationName


class SourceBaseConfig(BaseModel):
    type: str = Field(frozen=True)
    description: Optional[str] = None


@dataclass
class SourceBase(Plugin, ABC):
    config: SourceBaseConfig
    _datastream_push_task: asyncio.Task = field(init=False)
    _datastream_turn_off: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _data_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1), init=False)
    _response_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1), init=False)

    @property
    def source_identifier(self) -> str:
        return self.identifier
    
    @property
    def mandatory_response_handling(self) -> bool:
        return False    # by default, the source does not require mandatory response handling, but it can be overridden by specific sources that require it (e.g., the HTTP source, since it needs to wait for the response to send it back to the client)
    
    @operation(
        name=OperationName.NEXT,
        input=Input.no_input(),
        output=DataMessage,
        default_policy=Policy.no_constraints()
    )
    async def __next(self, topic: str, event: Event):
        pass    # nothing to do, it is declared just to define the operation and its input/output

    @operation(
        name=OperationName.RESPONSE,
        input=Input.from_message(ResponseMessage),
        output=None,
        default_policy=Policy.no_constraints()
    )
    async def __response(self, topic: str, event: Event[ResponseMessage]):
        
        response_message = event.payload
        assert isinstance(response_message, ResponseMessage)
        
        await self._response_queue.put(response_message)
        
    
    async def _push_loop(self):
        while not self._datastream_turn_off.is_set():
            
            if self.mandatory_response_handling:
                assert self._response_queue.empty(), "Response queue is not empty, previous response not yet processed by the device"
            else:
                if not self._response_queue.empty():
                    self._response_queue.get_nowait()   # discard the previous response if it is still in the queue, since it is not mandatory to handle it
            
            data = await self._data_queue.get()
                
            await self._push(DataMessage.of(
                source_identifier=self.source_identifier,
                value=data
            ))
    
    async def _push(self, data_message: DataMessage):

        await self.eventbus_client.multi_publish(
            topics=[str(connections[OperationName.NEXT].output_topic) for connections in self._connections.values() if connections[OperationName.NEXT].has_output],
            message=data_message
        )
        
    async def turn_on_datastream(self):
        self._datastream_turn_off.clear()
        self._datastream_push_task = asyncio.create_task(self._push_loop())
        
    async def turn_off_datastream(self):
        self._datastream_turn_off.set()
        await self._datastream_push_task
        




