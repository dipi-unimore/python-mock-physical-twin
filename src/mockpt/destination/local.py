from typing import Literal, Optional, List, Any, Dict
import os
from dataclasses import dataclass, field
import aiomqtt
from contextlib import AsyncExitStack

from mockpt.destination.enum import DestinationName
from mockpt.destination.base import DestinationBase, DestinationBaseConfig
from mockpt.common.data_message import DataMessage


class LocalDestinationConfig(DestinationBaseConfig):
    type: Literal[DestinationName.LOCAL.value] = DestinationName.LOCAL.value # type: ignore
    directory: str
    force: bool = True
    append: bool = True
    separator: str = "\n"
    


@dataclass
class LocalDestination(DestinationBase):
    config: LocalDestinationConfig # type: ignore

    def __post_init__(self):
        super().__post_init__()
        
        if os.path.exists(self.config.directory):
            if not self.config.force:
                raise FileExistsError(f"Directory '{self.config.directory}' already exists and 'force' is set to False.")        

    async def _send(self, endpoint: str, data: DataMessage):
        if endpoint.endswith('/'):
            raise ValueError("Endpoint cannot end with a slash ('/').")
        
        file_path = os.path.join(self.config.directory, endpoint)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        if self.config.append: 
            with open(file_path, 'a') as f:
                f.write(data.json_value + self.config.separator)
        else:
            with open(file_path, 'w') as f:
                f.write(data.json_value)






