"""Configuration loader for the Incident Response Agent."""

from .loader import AgentConfig, load_config, get_default_config

__all__ = [
    "AgentConfig",
    "load_config",
    "get_default_config",
]
