"""Tests for the Day-1 mock data layer."""

import pytest
from datetime import datetime, timezone

from incident_agent.mock_data import (
    AlertGenerator,
    AlertSeverity,
    TraceGenerator,
    SpanStatus,
    LogGenerator,
    LogLevel,
    IncidentScenario,
    generate_incident_scenario,
)
from incident_agent.mock_data.scenario import ScenarioType


# ---------------------------------------------------------------------------
# AlertGenerator tests
# ---------------------------------------------------------------------------

class TestAlertGenerator:
    def setup_method(self):
        self.gen = AlertGenerator(seed=42)
        self.base = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_cpu_spike_returns_correct_count(self):
        alerts = self.gen.generate_cpu_spike_alerts(base_time=self.base, count=5)
        assert len(alerts) == 5

    def test_cpu_spike_metric_name(self):
        alerts = self.gen.generate_cpu_spike_alerts(base_time=self.base, count=3)
        for a in alerts:
            assert a.metric == "cpu_usage_percent"

    def test_cpu_spike_values_exceed_threshold(self):
        alerts = self.gen.generate_cpu_spike_alerts(base_time=self.base, count=10)
        for a in alerts:
            assert a.value > a.threshold

    def test_error_rate_alerts_count(self):
        alerts = self.gen.generate_error_rate_alerts(base_time=self.base, count=4)
        assert len(alerts) == 4

    def test_error_rate_metric_name(self):
        alerts = self.gen.generate_error_rate_alerts(base_time=self.base, count=3)
        for a in alerts:
            assert a.metric == "http_error_rate_percent"

    def test_latency_alerts_have_ms_metric(self):
        alerts = self.gen.generate_latency_alerts(base_time=self.base, count=3)
        for a in alerts:
            assert a.metric == "latency_p99_ms"

    def test_alert_severity_is_enum(self):
        alerts = self.gen.generate_mixed_incident_alerts(base_time=self.base)
        for a in alerts:
            assert isinstance(a.severity, AlertSeverity)

    def test_alert_to_dict(self):
        alerts = self.gen.generate_cpu_spike_alerts(base_time=self.base, count=1)
        d = alerts[0].to_dict()
        assert "alert_id" in d
        assert "severity" in d
        assert isinstance(d["severity"], str)

    def test_alert_timestamps_are_ordered_monotonically(self):
        alerts = self.gen.generate_cpu_spike_alerts(
            base_time=self.base, count=3
        )
        timestamps = [a.timestamp for a in alerts]
        assert all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1))

    def test_mixed_alerts_has_multiple_metrics(self):
        alerts = self.gen.generate_mixed_incident_alerts(base_time=self.base)
        metrics = {a.metric for a in alerts}
        assert len(metrics) > 1


# ---------------------------------------------------------------------------
# TraceGenerator tests
# ---------------------------------------------------------------------------

class TestTraceGenerator:
    def setup_method(self):
        self.gen = TraceGenerator(seed=42)
        self.base = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_normal_traces_count(self):
        traces = self.gen.generate_normal_traces(count=5, base_time=self.base)
        assert len(traces) == 5

    def test_normal_traces_have_no_errors(self):
        traces = self.gen.generate_normal_traces(count=10, base_time=self.base)
        # Normal traces should all be OK status on all spans
        for trace in traces:
            for span in trace.spans:
                assert span.status == SpanStatus.OK

    def test_high_latency_traces_duration(self):
        traces = self.gen.generate_high_latency_traces(base_time=self.base, count=3)
        for trace in traces:
            # At least one span should be slow (>= 800ms)
            max_dur = max(s.duration_ms for s in trace.spans)
            assert max_dur >= 800.0

    def test_error_traces_have_errors(self):
        traces = self.gen.generate_error_traces(base_time=self.base, count=5)
        for trace in traces:
            assert trace.has_errors

    def test_error_traces_have_error_messages(self):
        traces = self.gen.generate_error_traces(base_time=self.base, count=5)
        for trace in traces:
            error_spans = [
                s for s in trace.spans if s.status != SpanStatus.OK
            ]
            assert all(s.error_message is not None for s in error_spans)

    def test_trace_to_dict(self):
        traces = self.gen.generate_normal_traces(count=1, base_time=self.base)
        d = traces[0].to_dict()
        assert "trace_id" in d
        assert "spans" in d
        assert isinstance(d["spans"], list)

    def test_trace_affected_services(self):
        services = ["api-gateway", "auth-service"]
        traces = self.gen.generate_error_traces(
            services=services, base_time=self.base, count=5
        )
        for trace in traces:
            for svc in trace.affected_services:
                assert svc in services

    def test_mixed_incident_traces(self):
        traces = self.gen.generate_mixed_incident_traces(base_time=self.base)
        assert len(traces) >= 3
        has_error = any(t.has_errors for t in traces)
        assert has_error


# ---------------------------------------------------------------------------
# LogGenerator tests
# ---------------------------------------------------------------------------

class TestLogGenerator:
    def setup_method(self):
        self.gen = LogGenerator(seed=42)
        self.base = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_normal_logs_count(self):
        logs = self.gen.generate_normal_logs(count=20, base_time=self.base)
        assert len(logs) == 20

    def test_normal_logs_no_error_or_critical(self):
        logs = self.gen.generate_normal_logs(count=30, base_time=self.base)
        for entry in logs:
            assert entry.level not in (LogLevel.ERROR, LogLevel.CRITICAL)

    def test_cpu_spike_logs_have_high_severity(self):
        logs = self.gen.generate_cpu_spike_logs(base_time=self.base, count=10)
        levels = {e.level for e in logs}
        # Should include at least WARNING or higher
        high = {LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL}
        assert levels & high

    def test_error_surge_logs_mostly_errors(self):
        logs = self.gen.generate_error_surge_logs(base_time=self.base, count=20)
        error_or_critical = [
            e for e in logs if e.level in (LogLevel.ERROR, LogLevel.CRITICAL)
        ]
        assert len(error_or_critical) / len(logs) >= 0.5

    def test_log_to_dict(self):
        logs = self.gen.generate_normal_logs(count=1, base_time=self.base)
        d = logs[0].to_dict()
        assert "log_id" in d
        assert "level" in d
        assert isinstance(d["level"], str)

    def test_mixed_logs_sorted_by_timestamp(self):
        logs = self.gen.generate_mixed_incident_logs(base_time=self.base)
        timestamps = [e.timestamp for e in logs]
        assert all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1))

    def test_error_surge_logs_have_trace_ids(self):
        logs = self.gen.generate_error_surge_logs(base_time=self.base, count=20)
        with_trace = [e for e in logs if e.trace_id is not None]
        # At least some should have trace IDs
        assert len(with_trace) > 0


# ---------------------------------------------------------------------------
# IncidentScenario / generate_incident_scenario tests
# ---------------------------------------------------------------------------

class TestIncidentScenario:
    def test_cpu_spike_scenario(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.CPU_SPIKE, seed=42
        )
        assert scenario.scenario_type == ScenarioType.CPU_SPIKE
        assert len(scenario.alerts) > 0
        assert len(scenario.traces) > 0
        assert len(scenario.logs) > 0

    def test_error_surge_scenario(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.ERROR_SURGE, seed=42
        )
        assert scenario.scenario_type == ScenarioType.ERROR_SURGE
        assert len(scenario.alerts) > 0

    def test_latency_outlier_scenario(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.LATENCY_OUTLIER, seed=42
        )
        assert scenario.scenario_type == ScenarioType.LATENCY_OUTLIER

    def test_mixed_scenario(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.MIXED, seed=42
        )
        assert len(scenario.alerts) >= 5
        assert len(scenario.traces) >= 5
        assert len(scenario.logs) >= 10

    def test_reproducible_with_seed(self):
        s1 = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=99)
        s2 = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=99)
        assert s1.scenario_id == s2.scenario_id
        assert len(s1.alerts) == len(s2.alerts)
        assert len(s1.logs) == len(s2.logs)

    def test_custom_services(self):
        services = ["api-gateway", "payment-service"]
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.ERROR_SURGE,
            services=services,
            seed=7,
        )
        assert set(scenario.affected_services) == set(services)
        for alert in scenario.alerts:
            assert alert.service in services

    def test_summary_contains_scenario_id(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.MIXED, seed=1
        )
        summary = scenario.summary()
        assert scenario.scenario_id in summary

    def test_scenario_has_description(self):
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.CPU_SPIKE, seed=5
        )
        assert scenario.description != ""
        assert "CPU" in scenario.description or "compute" in scenario.description
