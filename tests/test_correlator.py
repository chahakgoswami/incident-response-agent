"""Tests for the Day-2 correlation engine."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from incident_agent.mock_data import (
    AlertGenerator,
    TraceGenerator,
    LogGenerator,
    generate_incident_scenario,
)
from incident_agent.mock_data.scenario import ScenarioType
from incident_agent.correlator import (
    CorrelationEngine,
    IncidentSummary,
    IncidentSeverity,
    SignalType,
)


BASE_TIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# CorrelationEngine basic tests
# ---------------------------------------------------------------------------

class TestCorrelationEngineBasic:
    def setup_method(self):
        self.engine = CorrelationEngine(window_minutes=5)
        self.alert_gen = AlertGenerator(seed=42)
        self.trace_gen = TraceGenerator(seed=42)
        self.log_gen = LogGenerator(seed=42)

    def test_empty_inputs_return_empty_list(self):
        result = self.engine.correlate()
        assert result == []

    def test_returns_list_of_incident_summaries(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(alerts=alerts)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, IncidentSummary)

    def test_alerts_only_produces_summaries(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=5)
        result = self.engine.correlate(alerts=alerts)
        assert len(result) >= 1

    def test_traces_only_produces_summaries(self):
        traces = self.trace_gen.generate_error_traces(base_time=BASE_TIME, count=4)
        result = self.engine.correlate(traces=traces)
        assert len(result) >= 1

    def test_logs_only_produces_summaries(self):
        logs = self.log_gen.generate_error_surge_logs(base_time=BASE_TIME, count=10)
        result = self.engine.correlate(logs=logs)
        assert len(result) >= 1

    def test_normal_traces_produce_no_summaries(self):
        # Normal (healthy) traces have OK spans with low latency — no signals expected
        traces = self.trace_gen.generate_normal_traces(count=5, base_time=BASE_TIME)
        result = self.engine.correlate(traces=traces)
        # Healthy spans are filtered out; no groups should have min_signals
        assert result == []

    def test_normal_logs_produce_no_summaries(self):
        # Normal logs are DEBUG/INFO — below WARNING threshold
        logs = self.log_gen.generate_normal_logs(count=20, base_time=BASE_TIME)
        result = self.engine.correlate(logs=logs)
        assert result == []


# ---------------------------------------------------------------------------
# Severity ranking
# ---------------------------------------------------------------------------

class TestSeverityRanking:
    def setup_method(self):
        self.engine = CorrelationEngine()
        self.alert_gen = AlertGenerator(seed=7)

    def test_results_ordered_by_score_descending(self):
        alerts = self.alert_gen.generate_mixed_incident_alerts(base_time=BASE_TIME)
        result = self.engine.correlate(alerts=alerts)
        scores = [s.score for s in result]
        assert scores == sorted(scores, reverse=True)

    def test_critical_alert_produces_critical_severity(self):
        from incident_agent.mock_data.alerts import Alert, AlertSeverity
        import uuid
        alert = Alert(
            alert_id=str(uuid.uuid4()),
            name="CriticalTest",
            severity=AlertSeverity.CRITICAL,
            service="api-gateway",
            metric="cpu_usage_percent",
            value=99.0,
            threshold=80.0,
            timestamp=BASE_TIME,
            description="Critical CPU",
        )
        result = self.engine.correlate(alerts=[alert])
        assert len(result) == 1
        assert result[0].severity == IncidentSeverity.CRITICAL

    def test_incident_severity_rank_ordering(self):
        assert IncidentSeverity.rank(IncidentSeverity.CRITICAL) > IncidentSeverity.rank(IncidentSeverity.HIGH)
        assert IncidentSeverity.rank(IncidentSeverity.HIGH) > IncidentSeverity.rank(IncidentSeverity.MEDIUM)
        assert IncidentSeverity.rank(IncidentSeverity.MEDIUM) > IncidentSeverity.rank(IncidentSeverity.LOW)
        assert IncidentSeverity.rank(IncidentSeverity.LOW) > IncidentSeverity.rank(IncidentSeverity.UNKNOWN)


# ---------------------------------------------------------------------------
# Time-window grouping
# ---------------------------------------------------------------------------

class TestTimeWindowGrouping:
    def setup_method(self):
        self.engine = CorrelationEngine(window_minutes=5)
        self.alert_gen = AlertGenerator(seed=1)

    def test_signals_in_same_window_grouped_together(self):
        """All alerts within a 5-minute window on the same service should land in one group."""
        from incident_agent.mock_data.alerts import Alert, AlertSeverity
        import uuid
        from datetime import timedelta

        service = "payment-service"
        alerts = [
            Alert(
                alert_id=str(uuid.uuid4()),
                name="Test",
                severity=AlertSeverity.HIGH,
                service=service,
                metric="cpu_usage_percent",
                value=90.0,
                threshold=80.0,
                timestamp=BASE_TIME + timedelta(minutes=i),
                description="",
            )
            for i in range(4)  # 4 alerts within 4 minutes — same 5-min window
        ]
        result = self.engine.correlate(alerts=alerts)
        # Should produce exactly 1 summary for the single service/window combo
        assert len(result) == 1
        assert len(result[0].contributing_signals) == 4

    def test_signals_in_different_windows_produce_separate_groups(self):
        """Alerts 10 minutes apart should land in different windows."""
        from incident_agent.mock_data.alerts import Alert, AlertSeverity
        import uuid
        from datetime import timedelta

        service = "auth-service"
        alerts = [
            Alert(
                alert_id=str(uuid.uuid4()),
                name="Test",
                severity=AlertSeverity.HIGH,
                service=service,
                metric="cpu_usage_percent",
                value=90.0,
                threshold=80.0,
                timestamp=BASE_TIME + timedelta(minutes=offset),
                description="",
            )
            for offset in [0, 10]  # 0 and 10 minutes — different 5-min windows
        ]
        result = self.engine.correlate(alerts=alerts)
        assert len(result) == 2

    def test_window_start_and_end_are_populated(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(alerts=alerts)
        for summary in result:
            assert isinstance(summary.window_start, datetime)
            assert isinstance(summary.window_end, datetime)
            assert summary.window_start <= summary.window_end


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------

class TestSignalClassification:
    def setup_method(self):
        self.engine = CorrelationEngine(latency_error_threshold_ms=800.0)
        self.trace_gen = TraceGenerator(seed=99)
        self.log_gen = LogGenerator(seed=99)

    def test_error_traces_classified_as_high(self):
        traces = self.trace_gen.generate_error_traces(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(traces=traces)
        signal_types = [
            s.signal_type for summary in result for s in summary.contributing_signals
        ]
        assert SignalType.TRACE in signal_types

    def test_high_latency_traces_included(self):
        traces = self.trace_gen.generate_high_latency_traces(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(traces=traces)
        # Should produce at least one summary
        assert len(result) >= 1

    def test_log_warning_included_as_signal(self):
        from incident_agent.mock_data.logs import LogEntry, LogLevel
        import uuid
        entry = LogEntry(
            log_id=str(uuid.uuid4()),
            timestamp=BASE_TIME,
            level=LogLevel.WARNING,
            service="user-service",
            message="Slow query detected",
        )
        result = self.engine.correlate(logs=[entry])
        assert len(result) == 1
        assert result[0].contributing_signals[0].signal_type == SignalType.LOG

    def test_log_debug_excluded_as_signal(self):
        from incident_agent.mock_data.logs import LogEntry, LogLevel
        import uuid
        entry = LogEntry(
            log_id=str(uuid.uuid4()),
            timestamp=BASE_TIME,
            level=LogLevel.DEBUG,
            service="user-service",
            message="Debug message",
        )
        result = self.engine.correlate(logs=[entry])
        assert result == []


# ---------------------------------------------------------------------------
# IncidentSummary structure
# ---------------------------------------------------------------------------

class TestIncidentSummaryStructure:
    def setup_method(self):
        self.engine = CorrelationEngine()
        self.alert_gen = AlertGenerator(seed=5)

    def test_summary_has_incident_id(self):
        alerts = self.alert_gen.generate_error_rate_alerts(base_time=BASE_TIME, count=2)
        result = self.engine.correlate(alerts=alerts)
        for s in result:
            assert s.incident_id.startswith("INC-")

    def test_summary_has_affected_services(self):
        alerts = self.alert_gen.generate_mixed_incident_alerts(base_time=BASE_TIME)
        result = self.engine.correlate(alerts=alerts)
        for s in result:
            assert len(s.affected_services) >= 1

    def test_summary_has_contributing_signals(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(alerts=alerts)
        for s in result:
            assert len(s.contributing_signals) >= 1

    def test_summary_signal_counts_match(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=4)
        result = self.engine.correlate(alerts=alerts)
        for summary in result:
            total_from_counts = sum(summary.signal_counts.values())
            assert total_from_counts == len(summary.contributing_signals)

    def test_summary_to_dict_is_serializable(self):
        import json
        alerts = self.alert_gen.generate_mixed_incident_alerts(base_time=BASE_TIME)
        result = self.engine.correlate(alerts=alerts)
        for summary in result:
            d = summary.to_dict()
            # Should be JSON-serializable
            json_str = json.dumps(d)
            assert len(json_str) > 0

    def test_summary_text_is_nonempty(self):
        alerts = self.alert_gen.generate_error_rate_alerts(base_time=BASE_TIME, count=2)
        result = self.engine.correlate(alerts=alerts)
        for s in result:
            assert s.summary_text != ""

    def test_score_is_positive(self):
        alerts = self.alert_gen.generate_cpu_spike_alerts(base_time=BASE_TIME, count=3)
        result = self.engine.correlate(alerts=alerts)
        for s in result:
            assert s.score > 0


# ---------------------------------------------------------------------------
# correlate_scenario integration
# ---------------------------------------------------------------------------

class TestCorrelateScenario:
    def setup_method(self):
        self.engine = CorrelationEngine()

    def test_cpu_spike_scenario(self):
        scenario = generate_incident_scenario(scenario_type=ScenarioType.CPU_SPIKE, seed=42)
        result = self.engine.correlate_scenario(scenario)
        assert len(result) >= 1

    def test_error_surge_scenario(self):
        scenario = generate_incident_scenario(scenario_type=ScenarioType.ERROR_SURGE, seed=42)
        result = self.engine.correlate_scenario(scenario)
        assert len(result) >= 1

    def test_latency_outlier_scenario(self):
        scenario = generate_incident_scenario(scenario_type=ScenarioType.LATENCY_OUTLIER, seed=42)
        result = self.engine.correlate_scenario(scenario)
        assert len(result) >= 1

    def test_mixed_scenario_multiple_summaries(self):
        scenario = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=42)
        result = self.engine.correlate_scenario(scenario)
        assert len(result) >= 1

    def test_scenario_services_appear_in_summaries(self):
        services = ["api-gateway", "payment-service"]
        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.ERROR_SURGE, services=services, seed=10
        )
        result = self.engine.correlate_scenario(scenario)
        found_services = set()
        for summary in result:
            found_services.update(summary.affected_services)
        # At least one scenario service should appear
        assert found_services & set(services)

    def test_top_result_has_highest_score(self):
        scenario = generate_incident_scenario(scenario_type=ScenarioType.MIXED, seed=77)
        result = self.engine.correlate_scenario(scenario)
        if len(result) >= 2:
            assert result[0].score >= result[1].score

    def test_min_signals_filter(self):
        """With min_signals=3, groups smaller than 3 should be excluded."""
        engine = CorrelationEngine(window_minutes=5, min_signals=3)
        # Single alert should produce nothing
        from incident_agent.mock_data.alerts import Alert, AlertSeverity
        import uuid
        alert = Alert(
            alert_id=str(uuid.uuid4()),
            name="Solo",
            severity=AlertSeverity.HIGH,
            service="api-gateway",
            metric="cpu_usage_percent",
            value=90.0,
            threshold=80.0,
            timestamp=BASE_TIME,
            description="",
        )
        result = engine.correlate(alerts=[alert])
        assert result == []
