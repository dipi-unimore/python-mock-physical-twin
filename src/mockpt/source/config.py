from typing import Literal, Annotated, Union, Optional
from pydantic import BaseModel, Field

from mockpt.source.csv import CsvSourceConfig
from mockpt.source.random import RandomSourceConfig


SourceConfig = Annotated[
    Union[CsvSourceConfig, RandomSourceConfig], 
    Field(discriminator="type")
]