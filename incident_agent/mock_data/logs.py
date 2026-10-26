"""Simulated log entry generator for incident scenarios."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """Represents a single structured log line."""

    log_id: str
    timestamp: datetime
    level: LogLevel
    service: str
    message: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "log_id": self.log_id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "service": self.service,
            "message": self.message,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "fields": self.fields,
        }


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

_INFO_MESSAGES = [
    "Request processed successfully in {duration}ms",
    "Cache hit for key user:{user_id}",
    "Scheduled job completed: cleanup_expired_sessions",
    "Health check passed",
    "Loaded feature flags from config store",
    "Connected to database pool (size={pool_size})",
]

_WARNING_MESSAGES = [
    "Slow query detected: {duration}ms for SELECT * FROM orders",
    "Retry attempt {attempt}/3 for downstream auth-service",
    "Memory usage at {pct}% — approaching limit",
    "Connection pool utilization at {pct}%",
    "Rate limit approaching: {current}/{max} requests/min",
    "Cache miss rate elevated: {pct}%",
]

_ERROR_MESSAGES = [
    "Failed to connect to database: connection refused",
    "Unhandled exception in request handler: NullPointerException",
    "HTTP 500 returned for POST /api/v1/payments — downstream timeout",
    "Circuit breaker tripped for payment-service after 5 consecutive failures",
    "Redis WRONGTYPE error on key session:{session_id}",
    "Out of disk space on /var/log — log rotation failed",
    "gRPC deadline exceeded calling auth-service.ValidateToken",
]

_CRITICAL_MESSAGES = [
    "OOM Killer invoked — process {pid} terminated",
    "Node unreachable: health check failed 10 consecutive times",
    "Database primary down — failover initiated",
    "Deployment rollout failed: pods CrashLoopBackOff",
    "SSL certificate expired for api.example.com",
]

_CPU_LOG_MESSAGES = [
    "CPU throttling detected — {pct}% steal time in last 60s",
    "High CPU usage: {pct}% for the past 5 minutes",
    "Worker thread pool exhausted due to CPU saturation",
    "Go GC pressure high — CPU spent {pct}% in garbage collection",
]

_SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-service",
    "user-service",
    "recommendation-engine",
    "inventory-service",
]


class LogGenerator:
    """Generates realistic structured log entries in-memory."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_entry(
        self,
        level: LogLevel,
        service: str,
        message: str,
        timestamp: datetime,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        extra_fields: Optional[dict] = None,
    ) -> LogEntry:
        return LogEntry(
            log_id=str(uuid.uuid4()),
            timestamp=timestamp,
            level=level,
            service=service,
            message=message,
            trace_id=trace_id,
            span_id=span_id,
            fields=extra_fields or {},
        )

    def _fmt(self, template: str) -> str:
        """Fill template placeholders with random realistic values."""
        return template.format(
            duration=self._rng.randint(100, 9000),
            user_id=self._rng.randint(1000, 9999),
            pool_size=self._rng.randint(5, 50),
            attempt=self._rng.randint(1, 3),
            pct=self._rng.randint(60, 99),
            current=self._rng.randint(900, 1100),
            max=1000,
            session_id=str(uuid.uuid4())[:8],
            pid=self._rng.randint(1000, 65535),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_normal_logs(
        self,
        count: int = 20,
        base_time: Optional[datetime] = None,
        services: Optional[List[str]] = None,
    ) -> List[LogEntry]:
        """Generate a baseline healthy log stream."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or _SERVICES
        entries: List[LogEntry] = []
        for i in range(count):
            ts = base_time + timedelta(seconds=i * 3)
            level = self._rng.choices(
                [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING],
                weights=[10, 75, 15],
            )[0]
            service = self._rng.choice(services)
            if level == LogLevel.WARNING:
                msg = self._fmt(self._rng.choice(_WARNING_MESSAGES))
            else:
                msg = self._fmt(self._rng.choice(_INFO_MESSAGES))
            entries.append(self._make_entry(level, service, msg, ts))
        return entries

    def generate_cpu_spike_logs(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 10,
    ) -> List[LogEntry]:
        """Generate log entries characteristic of a CPU spike incident."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=min(2, len(_SERVICES)))
        entries: List[LogEntry] = []
        for i in range(count):
            ts = base_time + timedelta(seconds=i * 6)
            service = self._rng.choice(services)
            level = self._rng.choices(
                [LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL],
                weights=[50, 35, 15],
            )[0]
            if level == LogLevel.CRITICAL:
                msg = self._fmt(self._rng.choice(_CRITICAL_MESSAGES))
            elif level == LogLevel.ERROR:
                msg = self._fmt(self._rng.choice(_ERROR_MESSAGES))
            else:
                msg = self._fmt(self._rng.choice(_CPU_LOG_MESSAGES))
            entries.append(
                self._make_entry(
                    level,
                    service,
                    msg,
                    ts,
                    extra_fields={"incident_type": "cpu_spike"},
                )
            )
        return entries

    def generate_error_surge_logs(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 15,
    ) -> List[LogEntry]:
        """Generate a surge of error log entries."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=min(3, len(_SERVICES)))
        entries: List[LogEntry] = []
        for i in range(count):
            ts = base_time + timedelta(seconds=i * 4)
            service = self._rng.choice(services)
            level = self._rng.choices(
                [LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.WARNING],
                weights=[60, 20, 20],
            )[0]
            if level == LogLevel.CRITICAL:
                msg = self._fmt(self._rng.choice(_CRITICAL_MESSAGES))
            elif level == LogLevel.ERROR:
                msg = self._fmt(self._rng.choice(_ERROR_MESSAGES))
            else:
                msg = self._fmt(self._rng.choice(_WARNING_MESSAGES))
            trace_id = str(uuid.uuid4()) if self._rng.random() > 0.3 else None
            entries.append(
                self._make_entry(
                    level,
                    service,
                    msg,
                    ts,
                    trace_id=trace_id,
                    extra_fields={"incident_type": "error_surge"},
                )
            )
        return entries

    def generate_latency_logs(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
        count: int = 10,
    ) -> List[LogEntry]:
        """Generate log entries reflecting high-latency conditions."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=min(2, len(_SERVICES)))
        entries: List[LogEntry] = []
        for i in range(count):
            ts = base_time + timedelta(seconds=i * 5)
            service = self._rng.choice(services)
            level = self._rng.choices(
                [LogLevel.WARNING, LogLevel.ERROR],
                weights=[65, 35],
            )[0]
            if level == LogLevel.ERROR:
                msg = self._fmt(self._rng.choice(_ERROR_MESSAGES))
            else:
                msg = self._fmt(self._rng.choice(_WARNING_MESSAGES))
            entries.append(
                self._make_entry(
                    level,
                    service,
                    msg,
                    ts,
                    extra_fields={"incident_type": "latency_outlier"},
                )
            )
        return entries

    def generate_mixed_incident_logs(
        self,
        services: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
    ) -> List[LogEntry]:
        """Generate a realistic mixed log stream for an incident window."""
        base_time = base_time or datetime.now(tz=timezone.utc)
        services = services or self._rng.sample(_SERVICES, k=3)
        entries = (
            self.generate_normal_logs(count=10, base_time=base_time, services=services)
            + self.generate_cpu_spike_logs(services=services, base_time=base_time, count=6)
            + self.generate_error_surge_logs(services=services, base_time=base_time, count=8)
            + self.generate_latency_logs(services=services, base_time=base_time, count=5)
        )
        # Sort by timestamp for realism
        entries.sort(key=lambda e: e.timestamp)
        return entries
