import asyncio
from dataclasses import dataclass, field
import logging
from typing import List, Dict, override, Optional
from orbitalis.core.core import Core
from orbitalis.core.requirement import OperationRequirement, Constraint
from orbitalis.orbiter.schemaspec import Input, Output
from orbitalis.core.sink import sink
from busline.event.event import Event
from mockpt.common import id_wrapper
from mockpt.common.message.response_message import ResponseMessage
from mockpt.common.operation_name import OperationName
from mockpt.common.message.send_message import SendMessage
from mockpt.device.config import DestinationRecord, DeviceConfig, StreamConfig
from mockpt.common.message.data_message import DataMessage
from mockpt.state.state import State


@dataclass(kw_only=True)
class StateStream:
    state: State
    stream_config: StreamConfig 
    
    async def put(self, value: DataMessage):
        await self.state.put(value)
        
    async def get(self) -> DataMessage:
        return await self.state.queue.get()



@dataclass(kw_only=True)
class Device(Core):
    config: DeviceConfig
    _states_streams: Dict[str, List[StateStream]] = field(default_factory=dict, init=False)   # source_identifier => [StateStream]
    _loop_tasks: List[asyncio.Task] = field(default_factory=list, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    @property
    def device_identifier(self) -> str:
        return id_wrapper.device_identifier(self.identifier)
    
    def __post_init__(self):
        super().__post_init__()

        self.operation_requirements[OperationName.NEXT] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.no_input()],
                outputs=[Output.from_message(DataMessage)],
            )
        )
        
        self.operation_requirements[OperationName.RESPONSE] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.from_message(ResponseMessage)],
                outputs=[Output.no_output()],
            )
        )

        self.operation_requirements[OperationName.SEND] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.from_message(SendMessage)],
                outputs=[Output.no_output()],
            )
        )
        
        for _, stream_group in self.config.stream_groups.items():
            for _, stream_config in stream_group.items():
                self.register_stream(
                    config=stream_config
                )
        
        for state_streams in self._states_streams.values():     
            for state_stream in state_streams:
                self._loop_tasks.append(asyncio.create_task(self._stream_elaboration_loop(state_stream)))

    def register_stream(self, config: StreamConfig):
        self.operation_requirements[OperationName.NEXT].constraint.mandatory.append(config.source)
        
        state_stream = StateStream(
            state=State(
                logic=config.logic_class()
            ),
            stream_config=config
        )
        
        source_identifier = config.source
        self._states_streams[source_identifier] = self._states_streams.get(source_identifier, []) + [state_stream]
        
        
    async def _on_stopping(self, *args, **kwargs):
        await super()._on_stopping(*args, **kwargs)
        
        self._stop_event.set()
        for task in self._loop_tasks:
            await task
            
    
    @sink(
        operation_name=OperationName.NEXT
    )
    async def _next_event_handler(self, topic: str, event: Event[DataMessage]):
        assert event.payload is not None, "Payload must be provided for next operation"
        
        source_identifier = event.payload.source_identifier
        
        if source_identifier not in self._states_streams:
            logging.warning(f"Received data from unknown source '{source_identifier}' for device '{self.identifier}'. Ignoring.")
            return
        
        try:
            for state_stream in self._states_streams[source_identifier]:
                await state_stream.put(event.payload)
            
            await self.execute_using_plugin(
                operation_name=OperationName.RESPONSE,
                plugin_identifier=source_identifier,
                data=ResponseMessage(
                    device_identifier=self.device_identifier,
                    success=True,
                    message="OK"
                )
            )
            
        except Exception as e:
            logging.warning(f"Failed to process data from source '{source_identifier}' for device '{self.identifier}': {e}")
            
            await self.execute_using_plugin(
                operation_name=OperationName.RESPONSE,
                plugin_identifier=source_identifier,
                data=ResponseMessage(
                    device_identifier=self.device_identifier,
                    success=True,
                    message=str(e)
                )
            )


    async def _stream_elaboration_loop(self, state_stream: StateStream):
        
        interval = state_stream.stream_config.interval
        destinations = state_stream.stream_config.destinations
        
        last_processed_value = None

        while not self._stop_event.is_set():
            if interval is not None:
                # If an interval is specified, we want to send the last value at that interval, 
                # so we check if there's a new value without waiting, and if there is we update the last value to send. 
                # Then we wait for the specified interval before sending the last value 
                # (which could be the same if no new value arrived, or a new one if it did).
                try:
                    last_processed_value = await state_stream.get()
                except asyncio.QueueEmpty:
                    pass
                
                if last_processed_value:
                    await self._send_by_destinations(last_processed_value, destinations)
                
                await asyncio.sleep(interval)
            else:
                msg = await state_stream.get()
                await self._send_by_destinations(msg, destinations)

    async def _send_by_destinations(self, data: DataMessage, destinations: Dict[str, DestinationRecord]):
        for destination_identifier, destination_record in destinations.items():         
                           
            data_to_send = SendMessage(
                endpoint=destination_record.endpoint,
                data=data
            )
            
            try:
                await self.execute_using_plugin(
                    operation_name=OperationName.SEND,
                    plugin_identifier=destination_identifier,
                    data=data_to_send
                )
                
            except ValueError as e:
                logging.warning(f"Failed to send data to destination {destination_identifier}: {e}")

