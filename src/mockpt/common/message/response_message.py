from dataclasses import dataclass
from typing import Dict, Any
import json
from busline.event.message.avro_message import AvroMessageMixin


@dataclass(frozen=True)
class ResponseMessage(AvroMessageMixin):
    device_identifier: str
    success: bool
    message: str