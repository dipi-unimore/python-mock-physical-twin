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