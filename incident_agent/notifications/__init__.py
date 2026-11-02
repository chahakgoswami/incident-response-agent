"""Slack-style in-process notification mock for the Incident Response Agent."""

from .bus import EventBus, get_default_bus
from .channel import SlackChannel, ChannelMessage
from .notifier import IncidentNotifier

__all__ = [
    "EventBus",
    "get_default_bus",
    "SlackChannel",
    "ChannelMessage",
    "IncidentNotifier",
]
