import importlib.util
import sys
from typing import Dict, List, Optional, Set, Type
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from mockpt.state.identity_logic import IdentityStateLogic
from mockpt.state.logic import StateLogic


class DestinationRecord(BaseModel):
    endpoint: str


class StreamConfig(BaseModel):
    description: Optional[str] = None
    source: str
    interval: Optional[float] = None
    destinations: Dict[str, DestinationRecord] = Field(default_factory=dict)
    logic: Optional[str] = None
    
    @property
    def logic_class(self) -> Type[StateLogic]:
        if self.logic is None:
            return IdentityStateLogic
    
        path = Path(self.logic)
        if not path.exists():
            raise ValueError(f"Logic file not found: {self.logic}")
        
        module_name = path.stem
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load logic module from {self.logic}")
        
        module = importlib.util.module_from_spec(spec)
        
        sys.modules[module_name] = module   # prevent issues with imports in the logic file
        
        spec.loader.exec_module(module)

        for name in dir(module):
            obj = getattr(module, name)
            if (isinstance(obj, type) and 
                issubclass(obj, StateLogic) and 
                obj is not StateLogic):
                return obj
            
        raise ValueError(f"No valid StateLogic subclass found in {self.logic}")


class DeviceConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    
    vars: Dict[str, str] = Field(default_factory=dict)
    
    @model_validator(mode='after')
    def _parse_extra_fields(self) -> 'DeviceConfig':
        if self.model_extra:
            adapter = TypeAdapter(Dict[str, StreamConfig])
            for group_name, content in self.model_extra.items():
                if isinstance(content, dict):
                    # Override the content with the validated and parsed version
                    self.model_extra[group_name] = adapter.validate_python(content)
        return self
    
    @property
    def stream_groups(self) -> Dict[str, Dict[str, StreamConfig]]:
        return self.model_extra or {}
    
    @property
    def stream_configs(self) -> List[StreamConfig]:
        streams = []
        for group in self.stream_groups.values():
            for _, stream_config in group.items():
                streams.append(stream_config)
        return streams
