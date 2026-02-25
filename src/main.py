import asyncio
import logging

from busline.client.pubsub_client import PubSubClientBuilder
from busline.local.eventbus.local_eventbus import LocalEventBus
from busline.local.local_publisher import LocalPublisher
from busline.local.local_subscriber import LocalSubscriber

from mockpt.destination.mqtt import MqttDestination, MqttDestinationConfig
from mockpt.device.sensor.base import DestinationRecord, SensorBaseConfig
from mockpt.device.base import Device
from mockpt.source.random import RandomSource, RandomSourceConfig

logging.basicConfig(level=logging.INFO)

async def main():

    destination = MqttDestination(
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
    
    await destination.start()

    await asyncio.sleep(0.1)

    source = RandomSource(
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

    await source.start()

    await asyncio.sleep(0.1)

    device = Device(
        sensors={
            "temperature_sensor": SensorBaseConfig(
                source="temperature_source",
                destinations={
                    "mqtt_destination": DestinationRecord(
                        endpoint="home/temperature"
                    )
                }
            )
        },
        eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
        with_loop=False
    )

    assert len(device.remote_identifiers) == 0

    await device.start()

    await asyncio.sleep(0.1)

    assert len(device.remote_identifiers) == 2, f"Device should have discovered the source and destination plugin, number of remove identifiers: {len(device.remote_identifiers)}"

    # await device.execute_using_plugin("read", plugin_identifier="temperature_source")

    while True:
        await asyncio.sleep(0.1)




if __name__ == "__main__":
    asyncio.run(main())







