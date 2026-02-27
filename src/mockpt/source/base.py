from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from busline.event.event import Event
from orbitalis.plugin.plugin import Plugin
from orbitalis.plugin.operation import Policy
from orbitalis.plugin.operation import operation
from orbitalis.orbiter.schemaspec import Input
from busline.event.message.avro_message import AvroMessageMixin

from mockpt.common.data_message import DataMessage
from mockpt.common.operation_name import OperationName


class SourceBaseConfig(BaseModel):
    type: str = Field(frozen=True)
    description: Optional[str] = None


@dataclass
class SourceBase(Plugin, ABC):
    config: SourceBaseConfig

    @property
    def source_identifier(self) -> str:
        return self.identifier

    @abstractmethod
    async def _next(self) -> Dict[str, Any]:
        pass

    @operation(
        name=OperationName.NEXT,
        input=Input.no_input(),
        output=DataMessage,
        default_policy=Policy.no_constraints()
    )
    async def next(self, topic: str, event: Event):
        pass    # nothing to do

    async def _on_loop_iteration(self):
        await super()._on_loop_iteration()

        data = await self._next()

        message = DataMessage.of(
            source_identifier=self.source_identifier,
            value=data
        )

        await self.eventbus_client.multi_publish(
            topics=[str(connections[OperationName.NEXT].output_topic) for connections in self._connections.values() if connections[OperationName.NEXT].has_output],
            message=message
        )

        # for connections in self._connections.values():
        #     connection = connections["next"]

        #     assert connection.has_output

        #     await self.eventbus_client.publish(
        #         topic=str(connection.output_topic),
        #         message=message
        #     )


    




