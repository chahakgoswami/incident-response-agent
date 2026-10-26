"""Simulated alert generator producing realistic incident alerts in-memory."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Alert:
    """Represents a single monitoring alert."""

    alert_id: str
    name: str
    severity: AlertSeverity
    service: str
    metric: str
    value: float
    threshold: float
    timestamp: datetime
    labels: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "name": self.name,
            "severity": self.severity.value,
            "service": self.service,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Alert templates keyed by incident type
# ---------------------------------------------------------------------------

_CPU_TEMPLATES = [
    {
        "name": "HighCPUUsage",
        "metric": "cpu_usage_percent",
        "threshold": 80.0,
        "value_range": (82.0, 99.5),
        "severity": AlertSeverity.HIGH,
        "description": "CPU usage has exceeded {threshold}% (current: {value:.1f}%)",
    },
    {
        "name": "CriticalCPUSaturation",
        "metric": "cpu_usage_percent",
        "threshold": 95.0,
        "value_range": (95.1, 100.0),
        "severity": AlertSeverity.CRITICAL,
        "description": "CPU is saturated at {value:.1f}% — node at risk of OOM kill",
    },
]

_ERROR_RATE_TEMPLATES = [
    {
        "name": "ElevatedErrorRate",
        "metric": "http_error_rate_percent",
        "threshold": 5.0,
        "value_range": (5.1, 20.0),
        "severity": AlertSeverity.HIGH,
        "description": "HTTP 5xx error rate is {value:.1f}% (threshold: {threshold}%)",
    },
    {
        "name": "CriticalErrorRate",
        "metric": "http_error_rate_percent",
        "threshold": 20.0,
        "value_range": (20.1, 60.0),
        "severity": AlertSeverity.CRITICAL,
        "description": "Critical error surge: {value:.1f}% of requests are failing",
    },
]

_LATENCY_TEMPLATES = [
    {
        "name": "HighP99Latency",
        "metric": "latency_p99_ms",
        "threshold": 500.0,
        "value_range": (520.0, 1500.0),
        "severity": AlertSeverity.MEDIUM,
        "description": "P99 latency is {value:.0f}ms — SLO breach imminent",
    },
    {
        "name": "LatencyOutlier",
        "metric": "latency_p99_ms",
        "threshold": 1000.0,
        "value_range": (1001.0, 8000.0),
        "severity": AlertSeverity.HIGH,
        "description": "Severe latency outlier: P99={value:.0f}ms far above baseline",
    },
]

_SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-service",
    "user-service",
    "recommendation-engine",
    "inventory-service",
]


class AlertGenerator:
    """Generates realistic in-memory alert streams for simulated incidents."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_cpu_spike_alerts(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 3,
    ) -> List[Alert]:
        """Generate a burst of CPU spike alerts across one or more services."""
        services = services or self._rng.sample(_SERVICES, k=min(2, len(_SERVICES)))
        base_time = base_time or datetime.now(tz=timezone.utc)
        alerts: List[Alert] = []
        for i in range(count):
            template = self._rng.choice(_CPU_TEMPLATES)
            service = self._rng.choice(services)
            value = self._rng.uniform(*template["value_range"])
            ts = base_time + timedelta(seconds=self._rng.randint(0, 30) + i * 15)
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    name=template["name"],
                    severity=template["severity"],
                    service=service,
                    metric=template["metric"],
                    value=round(value, 2),
                    threshold=template["threshold"],
                    timestamp=ts,
                    labels={"region": "us-east-1", "env": "production"},
                    description=template["description"].format(
                        value=value, threshold=template["threshold"]
                    ),
                )
            )
        return alerts

    def generate_error_rate_alerts(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 3,
    ) -> List[Alert]:
        """Generate a burst of error-rate surge alerts."""
        services = services or self._rng.sample(_SERVICES, k=min(2, len(_SERVICES)))
        base_time = base_time or datetime.now(tz=timezone.utc)
        alerts: List[Alert] = []
        for i in range(count):
            template = self._rng.choice(_ERROR_RATE_TEMPLATES)
            service = self._rng.choice(services)
            value = self._rng.uniform(*template["value_range"])
            ts = base_time + timedelta(seconds=self._rng.randint(0, 20) + i * 10)
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    name=template["name"],
                    severity=template["severity"],
                    service=service,
                    metric=template["metric"],
                    value=round(value, 2),
                    threshold=template["threshold"],
                    timestamp=ts,
                    labels={"region": "us-east-1", "env": "production"},
                    description=template["description"].format(
                        value=value, threshold=template["threshold"]
                    ),
                )
            )
        return alerts

    def generate_latency_alerts(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 3,
    ) -> List[Alert]:
        """Generate latency outlier alerts."""
        services = services or self._rng.sample(_SERVICES, k=min(2, len(_SERVICES)))
        base_time = base_time or datetime.now(tz=timezone.utc)
        alerts: List[Alert] = []
        for i in range(count):
            template = self._rng.choice(_LATENCY_TEMPLATES)
            service = self._rng.choice(services)
            value = self._rng.uniform(*template["value_range"])
            ts = base_time + timedelta(seconds=self._rng.randint(0, 25) + i * 12)
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    name=template["name"],
                    severity=template["severity"],
                    service=service,
                    metric=template["metric"],
                    value=round(value, 2),
                    threshold=template["threshold"],
                    timestamp=ts,
                    labels={"region": "us-east-1", "env": "production"},
                    description=template["description"].format(
                        value=value, threshold=template["threshold"]
                    ),
                )
            )
        return alerts

    def generate_mixed_incident_alerts(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
    ) -> List[Alert]:
        """Generate a realistic mixed-type incident alert stream."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=3)
        return (
            self.generate_cpu_spike_alerts(services, base_time, count=2)
            + self.generate_error_rate_alerts(services, base_time, count=3)
            + self.generate_latency_alerts(services, base_time, count=2)
        )
