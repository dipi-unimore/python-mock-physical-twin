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


# TODO: rinominare in State
@dataclass(kw_only=True)
class SourceState:
    queue: asyncio.Queue[DataMessage] = field(default_factory=lambda: asyncio.Queue(maxsize=1), init=False)
    loop_task: Optional[asyncio.Task] = field(default=None, init=False)
    # TODO: funzione con la logica di elaborazione dei nuovi valori in arrivo, default: identity function
    
    async def put(self, value: DataMessage):
        # TODO: qui la logica di inserimento dei nuovi valori con eventuale raise se non conferme alla logica
        await self.queue.put(value)
        
        

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
        
        # TODO: try-except per "rispondere" alla source
        await self._source_states[source_identifier].put(event.payload)


    async def _sensor_elaboration_loop(self, sensor_identifier: str, source_identifier: str):
        source_state = self._source_states[source_identifier]
        sensor_config = self.config.sensors[sensor_identifier]
        interval = sensor_config.interval
        destinations = sensor_config.destinations
        
        last_processed_value = None

        while True:
            if interval is not None:
                # If an interval is specified, we want to send the last value at that interval, 
                # so we check if there's a new value without waiting, and if there is we update the last value to send. 
                # Then we wait for the specified interval before sending the last value 
                # (which could be the same if no new value arrived, or a new one if it did).
                try:
                    last_processed_value = source_state.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                
                if last_processed_value:
                    await self._send_by_destinations(sensor_identifier, source_identifier, last_processed_value, destinations)
                
                await asyncio.sleep(interval)
            else:
                msg = await source_state.queue.get()
                await self._send_by_destinations(sensor_identifier, source_identifier, msg, destinations)

    
    def _wild_card_replace(self, endpoint: str, sensor_identifier: str, source_identifier: str) -> str:
        endpoint = endpoint.replace("{device}", self.identifier)
        endpoint = endpoint.replace("{sensor}", sensor_identifier)
        endpoint = endpoint.replace("{source}", source_identifier)
        # TODO: destination wildcard
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

