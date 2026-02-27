from enum import StrEnum

class SourceName(StrEnum):
    """Enumeration of source names."""
    
    MQTT = "mqtt"
    CSV = "csv"
    RANDOM = "random"