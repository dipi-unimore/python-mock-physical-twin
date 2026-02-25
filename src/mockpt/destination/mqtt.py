from typing import Literal, Optional, List, Any, Dict
from dataclasses import dataclass
from busline.mqtt.mqtt_publisher import MqttPublisher

from mockpt.destination.base import DestinationBase, DestinationBaseConfig
from mockpt.common.data_message import DataMessage


class MqttDestinationConfig(DestinationBaseConfig):
    type: Literal["mqtt"] = "mqtt" # type: ignore
    broker_hostname: str
    broker_port: int


@dataclass
class MqttDestination(DestinationBase):
    config: MqttDestinationConfig # type: ignore
    mqtt_client: MqttPublisher = None # type: ignore

    def __post_init__(self):
        super().__post_init__()

        self.mqtt_client = MqttPublisher(
            hostname=self.config.broker_hostname,
            port=self.config.broker_port
        )

    async def _on_starting(self, *args, **kwargs):
        await super()._on_starting(*args, **kwargs)
        
        await self.mqtt_client.connect()

    async def _send(self, endpoint: str, data: DataMessage):
        print("Sending data to MQTT destination...")
        await self.mqtt_client.publish(endpoint, data.json_value)






