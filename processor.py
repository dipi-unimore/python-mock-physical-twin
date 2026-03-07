from typing import override

from mockpt.common.message.data_message import DataMessage
from mockpt.state.logic import StateLogic


class CiaoStateLogic(StateLogic):
    
    @override
    def process(self, input: DataMessage) -> DataMessage:
        return DataMessage.of(
            source_identifier="ciao",
            value="ciao"
        )