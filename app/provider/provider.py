from __future__ import annotations

class Provider:
    """
    Abstract base class representing a provider.
    """

    def __init__(self,
                 provider_id,
                 protocol_config,
                 payload_config):
        """
        Initialize a Provider instance.
        """

    def start(self):
        """
        Start method to be implemented by subclasses.
        This method should be overridden by subclasses to define the start behavior of the protocol.
        """
        raise NotImplementedError("start method must be implemented by subclasses")
    
    def stop(self):
        """
       Stop method to be implemented by subclasses.
       This method should be overridden by subclasses to define the stop behavior of the protocol.
       """
        raise NotImplementedError("stop method must be implemented by subclasses")

    def validate_config(self):
        """
        Validate configuration method to be implemented by subclasses.
        This method should be overridden by subclasses to validate the protocol configuration.
        """
        raise NotImplementedError("validate_config method must be implemented by subclasses")

    def publish_sensor_telemetry_data(self, device_id, sensor_id, payload):
        """
        Publish telemetry data of a single sensor, method to be implemented by subclasses.

        This method should be overridden by subclasses to define how sensor telemetry data is published
        by the protocol.

        :param device_id: The ID of the device.
        :type device_id: str
        :param sensor_id: The ID of the sensor.
        :type sensor_id: str
        :param payload: The data payload to be published.
        """
        raise NotImplementedError("publish_sensor_telemetry_data method must be implemented by subclasses")
