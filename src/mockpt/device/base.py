import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, override, Optional
from orbitalis.core.core import Core
from orbitalis.core.requirement import OperationRequirement, Constraint
from orbitalis.orbiter.schemaspec import Input, Output
from orbitalis.core.sink import sink
from busline.event.event import Event
from mockpt.common.operation_name import OperationName
from mockpt.common.send_message import SendMessage
from mockpt.device.sensor.base import DestinationRecord, SensorBaseConfig
from mockpt.common.data_message import DataMessage


@dataclass(kw_only=True)
class SourceState:
    last_value: Optional[DataMessage] = None
    value_updated: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    loop_task: Optional[asyncio.Task] = field(default=None, init=False)
    
    def put(self, value: DataMessage):
        self.last_value = value
        self.value_updated.set()


@dataclass(kw_only=True)
class Device(Core):
    sensors: Dict[str, SensorBaseConfig]
    source_states: Dict[str, SourceState] = field(default_factory=dict)


    def __post_init__(self):
        super().__post_init__()

        self.operation_requirements[OperationName.NEXT] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.no_input()],
                outputs=[Output.from_message(DataMessage)],
            )
        )

        self.operation_requirements[OperationName.SEND] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.from_message(SendMessage)],
                outputs=[Output.no_output()],
            )
        )

        for identifier, sensor in self.sensors.items():
            self.register_sensor(identifier, sensor)


    def register_sensor(self, sensor_identifier: str, config: SensorBaseConfig):
        self.operation_requirements[OperationName.NEXT].constraint.mandatory.append(config.source)
        
        state = SourceState()
        self.source_states[config.source] = state      # must be stored to be started later and to put new values when received
        
        state.value_updated.clear()
        state.loop_task = asyncio.create_task(self._sensor_elaboration_loop(sensor_identifier, config.source))
        
    async def _on_stopping(self, *args, **kwargs):
        await super()._on_stopping(*args, **kwargs)
        
        for state in self.source_states.values():
            if state.loop_task is not None:
                state.loop_task.cancel()
    
    @sink(
        operation_name=OperationName.NEXT
    )
    async def _next_event_handler(self, topic: str, event: Event[DataMessage]):
        assert event.payload is not None, "Payload must be provided for next operation"    
        self.source_states[event.payload.source_identifier].put(event.payload)


    async def _sensor_elaboration_loop(self, sensor_identifier: str, source_identifier: str):
        source_state = self.source_states[source_identifier]
        interval = self.sensors[sensor_identifier].interval
        destinations = self.sensors[sensor_identifier].destinations
        
        if interval is not None:
            await source_state.value_updated.wait()    # await only first value, then loop with fixed interval

            while True:
                source_state.value_updated.clear()
                await asyncio.sleep(interval)

                assert source_state.last_value is not None, "Data must be provided"
                await self._send_by_destinations(source_state.last_value, destinations)
                
        else:
            while True:
                await source_state.value_updated.wait()
                source_state.value_updated.clear()
                
                assert source_state.last_value is not None, "Data must be provided"
                await self._send_by_destinations(source_state.last_value, destinations)

                

    async def _send_by_destinations(self, data: DataMessage, destinations: Dict[str, DestinationRecord]):
        for destination_identifier, destination_record in destinations.items():         
            
            # TODO: replace endpoint with wildcard
               
            data_to_send = SendMessage(
                endpoint=destination_record.endpoint,
                data=data
            )
            
            await self.execute_using_plugin(
                operation_name=OperationName.SEND,
                plugin_identifier=destination_identifier,
                data=data_to_send
            )


