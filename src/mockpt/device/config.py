

from typing import Dict, Optional

from pydantic import BaseModel, Field

from mockpt.device.sensor.base import SensorBaseConfig


class DeviceConfig(BaseModel):
    vars: Dict[str, str] = Field(default_factory=dict)
    sensors: Dict[str, SensorBaseConfig]