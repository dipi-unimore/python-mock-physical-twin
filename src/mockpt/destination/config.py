from typing import Literal, Annotated, Union, Optional
from pydantic import BaseModel, Field

from mockpt.destination.http import HttpDestinationConfig
from mockpt.destination.local import LocalDestinationConfig
from mockpt.destination.mqtt import MqttDestinationConfig



DestinationConfig = Annotated[
    Union[LocalDestinationConfig, MqttDestinationConfig, HttpDestinationConfig], 
    Field(discriminator="type")
]