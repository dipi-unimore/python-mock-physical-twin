from abc import ABC, abstractmethod

from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class DestinationRecord(BaseModel):
    endpoint: str


class SensorBaseConfig(BaseModel):
    description: Optional[str] = None
    source: str
    interval: Optional[float] = None
    destinations: Dict[str, DestinationRecord] = Field(default_factory=dict)



