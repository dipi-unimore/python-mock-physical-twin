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
from mockpt.common.operation_name import OperationName
from mockpt.common.send_message import SendMessage
from mockpt.device.config import DeviceConfig
from mockpt.device.sensor.base import DestinationRecord, SensorBaseConfig
from mockpt.common.data_message import DataMessage


@dataclass(kw_only=True)
class SourceState:
    last_value: Optional[DataMessage] = None
    value_updated: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    loop_task: Optional[asyncio.Task] = field(default=None, init=False)
    
    async def put(self, value: DataMessage):
        while self.value_updated.is_set():
            await asyncio.sleep(0)    # wait until the current value is processed and cleared by the loop
        
        self.last_value = value
        self.value_updated.set()
        
        

@dataclass(kw_only=True)
class Device(Core):
    config: DeviceConfig
    _source_states: Dict[str, SourceState] = field(default_factory=dict)

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

        self.operation_requirements[OperationName.SEND] = OperationRequirement(
            constraint=Constraint(
                inputs=[Input.from_message(SendMessage)],
                outputs=[Output.no_output()],
            )
        )

        for identifier, sensor in self.config.sensors.items():
            self.register_sensor(
                identifier,
                sensor
            )


    def register_sensor(self, sensor_identifier: str, config: SensorBaseConfig):
        self.operation_requirements[OperationName.NEXT].constraint.mandatory.append(config.source)
        
        state = SourceState()
        
        source_identifier = config.source
        self._source_states[source_identifier] = state      # must be stored to be started later and to put new values when received
        
        state.value_updated.clear()
        state.loop_task = asyncio.create_task(self._sensor_elaboration_loop(sensor_identifier, source_identifier))
        
    async def _on_stopping(self, *args, **kwargs):
        await super()._on_stopping(*args, **kwargs)
        
        for state in self._source_states.values():
            if state.loop_task is not None:
                state.loop_task.cancel()
    
    @sink(
        operation_name=OperationName.NEXT
    )
    async def _next_event_handler(self, topic: str, event: Event[DataMessage]):
        assert event.payload is not None, "Payload must be provided for next operation"
        
        source_identifier = event.payload.source_identifier
        
        if source_identifier not in self._source_states:
            logging.warning(f"Received data from unknown source '{source_identifier}' for device '{self.identifier}'. Ignoring.")
            return
        
        await self._source_states[source_identifier].put(event.payload)


    async def _sensor_elaboration_loop(self, sensor_identifier: str, source_identifier: str):
        source_state = self._source_states[source_identifier]
        interval = self.config.sensors[sensor_identifier].interval
        destinations = self.config.sensors[sensor_identifier].destinations
        
        if interval is not None:
            await source_state.value_updated.wait()    # await only first value, then loop with fixed interval

            while True:
                source_state.value_updated.clear()
                await asyncio.sleep(interval)

                assert source_state.last_value is not None, "Data must be provided"
                await self._send_by_destinations(sensor_identifier, source_identifier, source_state.last_value, destinations)
                
        else:
            while True:
                
                await source_state.value_updated.wait()
                source_state.value_updated.clear()
                
                assert source_state.last_value is not None, "Data must be provided"
                await self._send_by_destinations(sensor_identifier, source_identifier, source_state.last_value, destinations)

    
    def _wild_card_replace(self, endpoint: str, sensor_identifier: str, source_identifier: str) -> str:
        endpoint = endpoint.replace("{device}", self.identifier)
        endpoint = endpoint.replace("{sensor}", sensor_identifier)
        endpoint = endpoint.replace("{source}", source_identifier)
        for var_name, var_value in self.config.vars.items():
            endpoint = endpoint.replace(f"{{var:{var_name}}}", var_value)
            
        return endpoint

    async def _send_by_destinations(self, sensor_identifier: str, source_identifier: str, data: DataMessage, destinations: Dict[str, DestinationRecord]):
        for destination_identifier, destination_record in destinations.items():         
            
            endpoint = self._wild_card_replace(destination_record.endpoint, sensor_identifier, source_identifier)
               
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

