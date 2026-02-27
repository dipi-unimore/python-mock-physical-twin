from enum import StrEnum

class DestinationName(StrEnum):
    """Enumeration of destination names."""
    
    MQTT = "mqtt"
    LOCAL = "local"