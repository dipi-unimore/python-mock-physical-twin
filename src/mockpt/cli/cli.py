from typing import Dict, List

from argparse_dataclass import ArgumentParser
import asyncio
import logging

from busline.client.pubsub_client import PubSubClientBuilder
from busline.local.eventbus.local_eventbus import LocalEventBus
from busline.local.local_publisher import LocalPublisher
from busline.local.local_subscriber import LocalSubscriber

from mockpt.cli.app_config import AppConfig
from mockpt.common import id_wrapper
from mockpt.destination.base import DestinationBase
from mockpt.destination import destination_class_by_type
from mockpt.destination.config import DestinationConfig
from mockpt.device.device import Device
from mockpt.device.config import DeviceConfig
from mockpt.source import source_class_by_type
from mockpt.source.base import SourceBase
from mockpt.source.config import SourceConfig
from dataclasses import dataclass, field


@dataclass
class CliOptions:
    """Command Line Interface options."""
    
    config: str = field(
        metadata=dict(
            args=["-c", "--config"],
            help="Path to the configuration file."
        )
    )
    
    log: str = field(
        default="INFO",
        metadata=dict(
            args=["--log"],
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Set the logging level."
        )
    )
    
    strict_config_validation: bool = field(
        default=False,
        metadata=dict(
            args=["--strict-config-validation"],
            help="Enable strict configuration validation."
        )
    )


def setup_logging(log_level_str: str) -> None:
    """Configure the root logger based on the string level."""
    # Convert the string (e.g., 'DEBUG') to the actual logging constant (e.g., logging.DEBUG)
    numeric_level = getattr(logging, log_level_str.upper(), None)
    
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level_str}")
        
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def build_destinations(destinations_configs: Dict[str, DestinationConfig]) -> Dict[str, DestinationBase]:
    
    destinations: Dict[str, DestinationBase] = {}
    for name, config in destinations_configs.items():
        
        destination = destination_class_by_type(config.type)(
            identifier=name,
            eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
            config=config,
            with_loop=False
        )       
        
        destinations[name] = destination
        
    return destinations
    
def build_sources(sources_configs: Dict[str, SourceConfig]) -> Dict[str, SourceBase]:
    
    sources: Dict[str, SourceBase] = {}
    for name, config in sources_configs.items():
        
        source = source_class_by_type(config.type)(
            identifier=name,
            eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
            config=config,
            with_loop=True
        )       
        
        sources[name] = source
    
    return sources

def build_devices(devices_configs: Dict[str, DeviceConfig]) -> Dict[str, Device]:
    
    devices: Dict[str, Device] = {}
    for name, config in devices_configs.items():
        
        source = Device(
            identifier=name,
            eventbus_client=PubSubClientBuilder()
                .with_subscriber(LocalSubscriber(eventbus=LocalEventBus()))
                .with_publisher(LocalPublisher(eventbus=LocalEventBus()))
                .build(),
            config=config,
            with_loop=False
        )       
        
        devices[name] = source
    
    return devices


async def cli(options: CliOptions):
    setup_logging(options.log)
    
    logger = logging.getLogger(__name__)
    
    logger.info("Application started.")
    logger.debug(f"Loading config from: {options.config}")
    
    # Load and parse the configuration file
    app_config = AppConfig.from_yaml_file(options.config)
    
    app_config.replace_wildcards()
    
    if app_config.wrap_needed():
        logger.warning("Some identifiers are used in multiple contexts (sources, destinations, devices)")
        
        if options.strict_config_validation:
            logger.error("Strict config validation is enabled, but some identifiers are used in multiple contexts. Please fix the config or disable strict validation.")
            raise ValueError("Some identifiers are used in multiple contexts (sources, destinations, devices)")
    
        app_config.wrap_names_if_needed()   # wrap identifiers after loading config, to have them available for validation and building of sources/destinations/devices
    
    destinations = build_destinations(app_config.destinations)
    
    sources = build_sources(app_config.sources)
    
    devices = build_devices(app_config.devices)
    
    # Check if all sources and destinations required by devices are present
    sources_required = set([
        source_config.source
        for device_config in app_config.devices.values()
        for sensor_config in device_config.stream_configs
        for source_config in [sensor_config]
    ])
    
    destinations_required = set([
        dest
        for device_config in app_config.devices.values()
        for sensor_config in device_config.stream_configs
        for dest in sensor_config.destinations.keys()
    ])
    
    missing_sources = sources_required - set(sources.keys())
    missing_destinations = destinations_required - set(destinations.keys())
    
    if len(missing_sources) > 0:
        if options.strict_config_validation:
            logger.error(f"Missing sources required by devices: {missing_sources}")
            raise ValueError(f"Missing sources required by devices: {missing_sources}")
        else:
            logger.warning(f"Missing sources required by devices: {missing_sources}")
    
    if len(missing_destinations) > 0:
        if options.strict_config_validation:
            logger.error(f"Missing destinations required by devices: {missing_destinations}")
            raise ValueError(f"Missing destinations required by devices: {missing_destinations}")
        else:
            logger.warning(f"Missing destinations required by devices: {missing_destinations}")
    
    logger.info(f"Built {len(destinations)} destinations, {len(sources)} sources and {len(devices)} devices.")
    
    logger.info(f"Starting {len(destinations)} destinations...")
    for destination in destinations.values():
        logger.info(f"Starting destination: {destination.identifier} of type {destination.config.type}")
        await destination.start()
        
        await asyncio.sleep(0.1)   # small delay to let the destination start before the sources/devices that may be connected to it
        
    logger.info(f"Starting {len(sources)} sources...")
    for source in sources.values():
        logger.info(f"Starting source: {source.identifier} of type {source.config.type}")
        await source.start()
        
        await asyncio.sleep(0.1)
    
    logger.info(f"Starting {len(devices)} devices...")
    for device in devices.values():
        logger.info(f"Starting device: {device.identifier}")
        await device.start()
        
        await asyncio.sleep(0.1)
        
        assert len(device.remote_identifiers) == len(sources) + len(destinations), f"Device {device.identifier} should have discovered {len(sources) + len(destinations)} remote identifiers (sources + destinations), but discovered {len(device.remote_identifiers)}."
    
    # Turn on datastream for sources after all devices have started, to ensure that devices receive the first data from sources
    for source in sources.values():
        await source.turn_on_datastream()
    
    stop_event = asyncio.Event()

    try:
        logger.info("Application is running. Press Ctrl+C to stop.")
        await stop_event.wait() 
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down application...")
        
    finally:
        for destination in destinations.values():
            await destination.stop()
            
        for source in sources.values():
            await source.stop()
            
        for device in devices.values():
            await device.stop()

        await asyncio.sleep(0.250)
        logger.info("Application stopped.")


def main():
    parser = ArgumentParser(CliOptions)
    options: CliOptions = parser.parse_args()
        
    try:
        asyncio.run(cli(options))
    except KeyboardInterrupt:
        logging.info("Bye!")

if __name__ == "__main__":
    main()
