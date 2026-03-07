from typing import Dict, Optional
from pydantic import BaseModel, Field
import yaml
from collections import Counter

from mockpt.common import id_wrapper
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
    
    def _wild_card_replace(self, endpoint: str, device_identifier: str, vars: Dict[str, str], sensor_identifier: str, source_identifier: str, destination_identifier: str) -> str:
        endpoint = endpoint.replace("{device}", device_identifier)
        endpoint = endpoint.replace("{stream}", sensor_identifier)
        endpoint = endpoint.replace("{source}", source_identifier)
        endpoint = endpoint.replace("{destination}", destination_identifier)
        
        for var_name, var_value in vars.items():
            endpoint = endpoint.replace(f"{{var:{var_name}}}", var_value)
            
        return endpoint
    
    def replace_wildcards(self):
        for device_identifier, device_config in self.devices.items():
            for stream_config in device_config.stream_configs:
                for destination_identifier, destination_record in stream_config.destinations.items():
                    endpoint = self._wild_card_replace(
                        destination_record.endpoint,
                        device_identifier=device_identifier,
                        vars=device_config.vars,
                        sensor_identifier=stream_config.source,
                        source_identifier=stream_config.source,
                        destination_identifier=destination_identifier
                    )
                    destination_record.endpoint = endpoint
    
    
    def wrap_names(self):
        self.destinations = {
            id_wrapper.destination_identifier(name): config for name, config in self.destinations.items()
        }
        
        self.sources = {
            id_wrapper.source_identifier(name): config for name, config in self.sources.items()
        }
        
        self.devices = {
            id_wrapper.device_identifier(name): config for name, config in self.devices.items()
        }
        
        for device_config in self.devices.values():
            for stream_config in device_config.stream_configs:
                stream_config.source = id_wrapper.source_identifier(stream_config.source)
                stream_config.destinations = {
                    id_wrapper.destination_identifier(dest): config for dest, config in stream_config.destinations.items()
                }
                
    def wrap_needed(self) -> bool:
        counts = Counter()
        
        counts.update(self.destinations.keys())
        counts.update(self.sources.keys())
        counts.update(self.devices.keys())
        
        for device_config in self.devices.values():
            for stream_config in device_config.stream_configs:
                counts[stream_config.source] += 1
                counts.update(stream_config.destinations.keys())
                
        return any(count >= 2 for count in counts.values())
                
    def wrap_names_if_needed(self):
        counts = Counter()
        
        counts.update(self.destinations.keys())
        counts.update(self.sources.keys())
        counts.update(self.devices.keys())
                
        for device_config in self.devices.values():
            for stream_config in device_config.stream_configs:
                counts[stream_config.source] += 1
                counts.update(stream_config.destinations.keys())
                
        def _wrap(name, wrapper_func):
            return wrapper_func(name) if counts[name] >= 2 else name

        self.destinations = {
            _wrap(name, id_wrapper.destination_identifier): config 
            for name, config in self.destinations.items()
        }
        
        self.sources = {
            _wrap(name, id_wrapper.source_identifier): config 
            for name, config in self.sources.items()
        }
        
        self.devices = {
            _wrap(name, id_wrapper.device_identifier): config 
            for name, config in self.devices.items()
        }
        
        for device_config in self.devices.values():
            for stream_config in device_config.stream_configs:
                stream_config.source = _wrap(stream_config.source, id_wrapper.source_identifier)
                stream_config.destinations = {
                    _wrap(dest, id_wrapper.destination_identifier): config 
                    for dest, config in stream_config.destinations.items()
                }









