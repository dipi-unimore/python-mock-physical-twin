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
class StateWrapper:
    state: State
    loop_task: Optional[asyncio.Task] = None
    
    async def put(self, value: DataMessage):
        await self.state.put(value)
        
    async def get(self) -> DataMessage:
        return await self.state.queue.get()



@dataclass(kw_only=True)
class Device(Core):
    config: DeviceConfig
    _states: Dict[str, StateWrapper] = field(default_factory=dict, init=False)    # key: source identifier, value: state wrapper containing the state and the loop task for that source
    _streams: Dict[str, StreamConfig] = field(default_factory=dict, init=False)

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
        
        self._streams = self.config.streams

        for stream_id, stream_config in self._streams.items():
            self.register_stream(
                stream_identifier=stream_id,
                config=stream_config
            )


    def register_stream(self, stream_identifier: str, config: StreamConfig):
        self.operation_requirements[OperationName.NEXT].constraint.mandatory.append(config.source)
        
        state = StateWrapper(state=State(
            logic=config.logic_class()
        ))
        
        source_identifier = config.source
        self._states[source_identifier] = state      # must be stored to be started later and to put new values when received
        
        state.loop_task = asyncio.create_task(self._stream_elaboration_loop(stream_identifier, source_identifier))
        
    async def _on_stopping(self, *args, **kwargs):
        await super()._on_stopping(*args, **kwargs)
        
        for state in self._states.values():
            if state.loop_task is not None:
                state.loop_task.cancel()
    
    @sink(
        operation_name=OperationName.NEXT
    )
    async def _next_event_handler(self, topic: str, event: Event[DataMessage]):
        assert event.payload is not None, "Payload must be provided for next operation"
        
        source_identifier = event.payload.source_identifier
        
        if source_identifier not in self._states:
            logging.warning(f"Received data from unknown source '{source_identifier}' for device '{self.identifier}'. Ignoring.")
            return
        
        try:
            await self._states[source_identifier].put(event.payload)
            
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


    async def _stream_elaboration_loop(self, stream_identifier: str, source_identifier: str):
        source_state = self._states[source_identifier]
        stream_config = self._streams[stream_identifier]
        interval = stream_config.interval
        destinations = stream_config.destinations
        
        last_processed_value = None

        while True:
            if interval is not None:
                # If an interval is specified, we want to send the last value at that interval, 
                # so we check if there's a new value without waiting, and if there is we update the last value to send. 
                # Then we wait for the specified interval before sending the last value 
                # (which could be the same if no new value arrived, or a new one if it did).
                try:
                    last_processed_value = await source_state.get()
                except asyncio.QueueEmpty:
                    pass
                
                if last_processed_value:
                    await self._send_by_destinations(stream_identifier, source_identifier, last_processed_value, destinations)
                
                await asyncio.sleep(interval)
            else:
                msg = await source_state.get()
                await self._send_by_destinations(stream_identifier, source_identifier, msg, destinations)

    
    def _wild_card_replace(self, endpoint: str, sensor_identifier: str, source_identifier: str, destination_identifier: str) -> str:
        endpoint = endpoint.replace("{device}", self.identifier)
        endpoint = endpoint.replace("{stream}", sensor_identifier)
        endpoint = endpoint.replace("{source}", source_identifier)
        endpoint = endpoint.replace("{destination}", destination_identifier)
        
        for var_name, var_value in self.config.vars.items():
            endpoint = endpoint.replace(f"{{var:{var_name}}}", var_value)
            
        return endpoint

    async def _send_by_destinations(self, sensor_identifier: str, source_identifier: str, data: DataMessage, destinations: Dict[str, DestinationRecord]):
        for destination_identifier, destination_record in destinations.items():         
            
            endpoint = self._wild_card_replace(destination_record.endpoint, sensor_identifier, source_identifier, destination_identifier)
               
            data_to_send = SendMessage(
                endpoint=endpoint,
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

