from typing import Type

from mockpt.destination.enum import DestinationName
from mockpt.destination.mqtt import MqttDestination
from mockpt.destination.local import LocalDestination
from mockpt.destination.base import DestinationBase


def destination_class_by_type(type: str) -> Type[DestinationBase]:
    if type == DestinationName.LOCAL.value:
        return LocalDestination
    elif type == DestinationName.MQTT.value:
        return MqttDestination
    else:
        raise ValueError(f"Unsupported destination type: {type}")

