from typing import Dict, Optional
from pydantic import BaseModel, Field
import yaml

from mockpt.destination.config import DestinationConfig
from mockpt.device.config import DeviceConfig
from mockpt.source.config import SourceConfig



class AppConfig(BaseModel):
    sources: Dict[str, SourceConfig] = Field(default_factory=dict)
    destinations: Dict[str, DestinationConfig] = Field(default_factory=dict)
    devices: Dict[str, DeviceConfig] = Field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, content: str) -> "AppConfig":
        data = yaml.safe_load(content)
        return cls(**data)
    
    @classmethod
    def from_yaml_file(cls, file_path: str) -> "AppConfig":
        with open(file_path, "r") as f:
            content = f.read()
        return cls.from_yaml(content)










