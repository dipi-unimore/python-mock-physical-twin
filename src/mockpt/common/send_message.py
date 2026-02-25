from dataclasses import dataclass
from typing import Dict, Any
import json
from busline.event.message.avro_message import AvroMessageMixin

from mockpt.common.data_message import DataMessage


@dataclass(frozen=True)
class SendMessage(AvroMessageMixin):
    endpoint: str
    data: DataMessage
    
    