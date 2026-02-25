from typing import Literal, Annotated, Union, Optional
from pydantic import BaseModel, Field

from source.csv import CsvSourceConfig
from source.random import RandomSourceConfig


SourceConfig = Annotated[
    Union[CsvSourceConfig, RandomSourceConfig], 
    Field(discriminator="type")
]