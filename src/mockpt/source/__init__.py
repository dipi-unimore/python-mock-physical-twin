from typing import Type

from mockpt.source.enum import SourceName
from mockpt.source.csv import CsvSource
from mockpt.source.mqtt import MqttSource
from mockpt.source.random import RandomSource
from mockpt.source.base import SourceBase
from mockpt.source.http import HttpSource


def source_class_by_type(type: str) -> Type[SourceBase]:
    if type == SourceName.CSV.value:
        return CsvSource
    elif type == SourceName.RANDOM.value:
        return RandomSource
    elif type == SourceName.MQTT.value:
        return MqttSource
    elif type == SourceName.HTTP.value:
        return HttpSource
    else:
        raise ValueError(f"Unsupported source type: {type}")

