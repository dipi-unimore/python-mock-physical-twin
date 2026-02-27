import asyncio
import logging

from busline.client.pubsub_client import PubSubClientBuilder
from busline.local.eventbus.local_eventbus import LocalEventBus
from busline.local.local_publisher import LocalPublisher
from busline.local.local_subscriber import LocalSubscriber

from mockpt.destination.local import LocalDestination, LocalDestinationConfig
from mockpt.destination.mqtt import MqttDestination, MqttDestinationConfig
from mockpt.device.config import DeviceConfig
from mockpt.device.sensor.base import DestinationRecord, SensorBaseConfig
from mockpt.device.base import Device
from mockpt.source.csv import CsvSource, CsvSourceConfig
from mockpt.source.random import RandomSource, RandomSourceConfig

logging.basicConfig(level=logging.INFO)

async def main():

    mqtt_destination = MqttDestination(
        identifier="mqtt_destination",
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        config=MqttDestinationConfig(
            broker_hostname="localhost",
            broker_port=1883
        ),
        with_loop=False
    )
    
    await mqtt_destination.start()

    await asyncio.sleep(0.1)
    
    local_destination = LocalDestination(
        identifier="local_destination",
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        config=LocalDestinationConfig(
            directory="/home/nricciardi/Repositories/python-mock-physical-twin/output"
        ),
        with_loop=False
    )
    
    await local_destination.start()

    await asyncio.sleep(0.1)

    random_source = RandomSource(
        identifier="temperature_source",
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        config=RandomSourceConfig(
            rv="norm",
            step=1,
            min=0,
        ),
        with_loop=True
    )

    await random_source.start()

    await asyncio.sleep(0.1)
    
    csv_source = CsvSource(
        identifier="humidity_source",
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        config=CsvSourceConfig(
            file="/home/nricciardi/Repositories/python-mock-physical-twin/data/humidity.csv",
            columns=["value"],
            timestamp_column="timestamp",
        ),
        with_loop=True
    )

    await csv_source.start()

    await asyncio.sleep(0.1)

    device = Device(
        config=DeviceConfig(
            vars={
                "room1": "living_room"
            },
            sensors={
            "temperature_sensor": SensorBaseConfig(
                source="temperature_source",
                destinations={
                    "mqtt_destination": DestinationRecord(
                        endpoint="{device}/{sensor}/{var:room1}/{source}"
                    ),
                    "local_destination": DestinationRecord(
                        endpoint="{device}/{sensor}/{var:room1}/{source}.txt"
                    )
                }
            ),
            "humidity_sensor": SensorBaseConfig(
                source="humidity_source",
                destinations={
                    "mqtt_destination": DestinationRecord(
                        endpoint="home/humidity"
                    ),
                    "local_destination": DestinationRecord(
                        endpoint="humidity.txt"
                    )
                }
            )
        }
        ),
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        with_loop=False
    )

    assert len(device.remote_identifiers) == 0

    await device.start()

    await asyncio.sleep(0.1)

    assert len(device.remote_identifiers) == 4, f"Device should have discovered the source and destination plugin, number of remove identifiers: {len(device.remote_identifiers)}"

    # await device.execute_using_plugin("read", plugin_identifier="temperature_source")

    while True:
        await asyncio.sleep(0.1)




if __name__ == "__main__":
    asyncio.run(main())







