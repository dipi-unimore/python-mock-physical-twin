from abc import ABC, abstractmethod

from mockpt.common.message.data_message import DataMessage


class StateLogic(ABC):
    
    @abstractmethod
    def process(self, input: DataMessage) -> DataMessage:
        pass