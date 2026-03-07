from dataclasses import dataclass
from typing import Dict, Any
import json
from busline.event.message.avro_message import AvroMessageMixin


@dataclass(frozen=True)
class DataMessage(AvroMessageMixin):
    source_identifier: str
    json_value: str
    
    @classmethod
    def of(cls, source_identifier: str, value: Any) -> "DataMessage":
        return cls(
            source_identifier=source_identifier,
            json_value=json.dumps(value)
        )

    @property
    def value(self) -> Any:
        return json.loads(self.json_value)
    