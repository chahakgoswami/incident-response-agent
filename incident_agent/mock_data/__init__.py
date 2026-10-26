"""Mock data layer for the Incident Response Agent."""

from .alerts import AlertGenerator, Alert, AlertSeverity
from .traces import TraceGenerator, Trace, SpanStatus
from .logs import LogGenerator, LogEntry, LogLevel
from .scenario import IncidentScenario, generate_incident_scenario

__all__ = [
    "AlertGenerator",
    "Alert",
    "AlertSeverity",
    "TraceGenerator",
    "Trace",
    "SpanStatus",
    "LogGenerator",
    "LogEntry",
    "LogLevel",
    "IncidentScenario",
    "generate_incident_scenario",
]
