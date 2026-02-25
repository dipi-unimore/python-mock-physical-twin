from typing import Literal, Annotated, Union, Optional
from pydantic import BaseModel, Field



DestinationConfig = Annotated[
    Union[], 
    Field(discriminator="type")
]