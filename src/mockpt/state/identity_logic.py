from typing import override

from mockpt.common.message.data_message import DataMessage
from mockpt.state.logic import StateLogic


class IdentityStateLogic(StateLogic):
    
    @override
    def process(self, input: DataMessage) -> DataMessage:
        return input