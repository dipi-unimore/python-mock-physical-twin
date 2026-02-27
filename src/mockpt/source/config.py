from typing import Literal, Annotated, Union, Optional
from pydantic import BaseModel, Field

from mockpt.source.csv import CsvSourceConfig
from mockpt.source.http import HttpSourceConfig
from mockpt.source.mqtt import MqttSourceConfig
from mockpt.source.random import RandomSourceConfig


SourceConfig = Annotated[
    Union[CsvSourceConfig, RandomSourceConfig, MqttSourceConfig, HttpSourceConfig], 
    Field(discriminator="type")
]