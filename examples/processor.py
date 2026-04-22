from typing import override

from mockpt.common.message.data_message import DataMessage
from mockpt.state.logic import StateLogic


def value(v: int):
    return { "value": v }


class FortyTwoStateLogic(StateLogic):
    
    @override
    def process(self, input: DataMessage) -> DataMessage:
        return DataMessage.of(
            source_identifier=input.source_identifier,
            value=value(42)
        )