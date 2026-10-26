"""High-level incident scenario builder that combines alerts, traces, and logs."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from .alerts import Alert, AlertGenerator
from .logs import LogEntry, LogGenerator
from .traces import Trace, TraceGenerator


class ScenarioType(str, Enum):
    CPU_SPIKE = "cpu_spike"
    ERROR_SURGE = "error_surge"
    LATENCY_OUTLIER = "latency_outlier"
    MIXED = "mixed"


@dataclass
class IncidentScenario:
    """A complete simulated incident scenario with all signal types."""

    scenario_id: str
    scenario_type: ScenarioType
    affected_services: List[str]
    start_time: datetime
    alerts: List[Alert] = field(default_factory=list)
    traces: List[Trace] = field(default_factory=list)
    logs: List[LogEntry] = field(default_factory=list)
    description: str = ""

    def summary(self) -> str:
        return (
            f"Scenario [{self.scenario_id}] type={self.scenario_type.value}\n"
            f"  Services : {', '.join(self.affected_services)}\n"
            f"  Start    : {self.start_time.isoformat()}\n"
            f"  Alerts   : {len(self.alerts)}\n"
            f"  Traces   : {len(self.traces)}\n"
            f"  Log lines: {len(self.logs)}\n"
            f"  Desc     : {self.description}"
        )


_SCENARIO_DESCRIPTIONS = {
    ScenarioType.CPU_SPIKE: (
        "Sudden CPU saturation across {services} — likely runaway process or "
        "traffic spike overwhelming compute capacity."
    ),
    ScenarioType.ERROR_SURGE: (
        "Elevated HTTP 5xx error rate detected on {services} — "
        "probable downstream dependency failure or bad deployment."
    ),
    ScenarioType.LATENCY_OUTLIER: (
        "P99 latency outliers observed on {services} — "
        "possible database lock contention or network partition."
    ),
    ScenarioType.MIXED: (
        "Multi-signal incident on {services}: CPU pressure, error surge, "
        "and latency spikes occurring simultaneously."
    ),
}


def generate_incident_scenario(
    scenario_type: ScenarioType = ScenarioType.MIXED,
    services: Optional[List[str]] = None,
    base_time: Optional[datetime] = None,
    seed: Optional[int] = None,
) -> IncidentScenario:
    """
    Generate a complete IncidentScenario with correlated alerts, traces, and logs.

    Args:
        scenario_type: The type of incident to simulate.
        services: Override the list of affected services (random subset if None).
        base_time: Override the incident start timestamp (now() if None).
        seed: Optional RNG seed for reproducible scenarios.

    Returns:
        A fully populated IncidentScenario instance.
    """
    rng = random.Random(seed)
    base_time = base_time or datetime.now(tz=timezone.utc)

    _all_services = [
        "api-gateway",
        "auth-service",
        "payment-service",
        "user-service",
        "recommendation-engine",
        "inventory-service",
    ]
    if services is None:
        k = rng.randint(2, 4)
        services = rng.sample(_all_services, k=k)

    alert_gen = AlertGenerator(seed=seed)
    trace_gen = TraceGenerator(seed=seed)
    log_gen = LogGenerator(seed=seed)

    scenario_id = f"INC-{rng.randint(10000, 99999)}"
    description = _SCENARIO_DESCRIPTIONS[scenario_type].format(
        services=", ".join(services)
    )

    if scenario_type == ScenarioType.CPU_SPIKE:
        alerts = alert_gen.generate_cpu_spike_alerts(
            services=services, base_time=base_time, count=4
        )
        traces = trace_gen.generate_high_latency_traces(
            services=services, base_time=base_time, count=5
        )
        logs = log_gen.generate_cpu_spike_logs(
            services=services, base_time=base_time, count=12
        )

    elif scenario_type == ScenarioType.ERROR_SURGE:
        alerts = alert_gen.generate_error_rate_alerts(
            services=services, base_time=base_time, count=4
        )
        traces = trace_gen.generate_error_traces(
            services=services, base_time=base_time, count=6
        )
        logs = log_gen.generate_error_surge_logs(
            services=services, base_time=base_time, count=15
        )

    elif scenario_type == ScenarioType.LATENCY_OUTLIER:
        alerts = alert_gen.generate_latency_alerts(
            services=services, base_time=base_time, count=4
        )
        traces = trace_gen.generate_high_latency_traces(
            services=services, base_time=base_time, count=6
        )
        logs = log_gen.generate_latency_logs(
            services=services, base_time=base_time, count=10
        )

    else:  # MIXED
        alerts = alert_gen.generate_mixed_incident_alerts(
            services=services, base_time=base_time
        )
        traces = trace_gen.generate_mixed_incident_traces(
            services=services, base_time=base_time
        )
        logs = log_gen.generate_mixed_incident_logs(
            services=services, base_time=base_time
        )

    return IncidentScenario(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        affected_services=services,
        start_time=base_time,
        alerts=alerts,
        traces=traces,
        logs=logs,
        description=description,
    )
