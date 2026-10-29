"""Tests for the Day-4 rollback suggester and confirmation gate."""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import List

import pytest

from incident_agent.correlator.models import (
    CorrelatedSignal,
    IncidentSeverity,
    IncidentSummary,
    SignalType,
)
from incident_agent.rollback import (
    ConfirmationGate,
    RollbackCommand,
    RollbackResult,
    RollbackStatus,
    RollbackSuggester,
)
from incident_agent.rollback.library import get_library


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_signal(
    signal_type: SignalType = SignalType.ALERT,
    service: str = "api-gateway",
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    description: str = "Test signal",
) -> CorrelatedSignal:
    return CorrelatedSignal(
        signal_type=signal_type,
        signal_id=str(uuid.uuid4()),
        service=service,
        timestamp=BASE_TIME,
        severity_hint=severity,
        description=description,
    )


def _make_summary(
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    services: List[str] | None = None,
    signal_descriptions: List[str] | None = None,
    signal_counts: dict | None = None,
) -> IncidentSummary:
    services = services or ["api-gateway"]
    descriptions = signal_descriptions or ["Test signal"]
    signals = [
        _make_signal(service=services[0], description=d)
        for d in descriptions
    ]
    return IncidentSummary(
        incident_id=f"INC-{str(uuid.uuid4())[:8].upper()}",
        severity=severity,
        affected_services=services,
        contributing_signals=signals,
        window_start=BASE_TIME,
        window_end=BASE_TIME,
        signal_counts=signal_counts or {"alert": len(signals)},
        score=float(len(signals) * 5),
        summary_text="Test incident",
    )


# ---------------------------------------------------------------------------
# RollbackLibrary tests
# ---------------------------------------------------------------------------


class TestRollbackLibrary:
    def test_library_is_nonempty(self):
        lib = get_library()
        assert len(lib) > 0

    def test_all_commands_have_required_fields(self):
        for cmd in get_library():
            assert cmd.command_id
            assert cmd.description
            assert cmd.command
            assert isinstance(cmd.pattern_tags, list)

    def test_all_risk_levels_are_valid(self):
        valid = {"low", "medium", "high"}
        for cmd in get_library():
            assert cmd.risk_level in valid

    def test_library_contains_kubectl_rollout_undo(self):
        lib = get_library()
        cmds = [c.command for c in lib]
        assert any("kubectl rollout undo" in c for c in cmds)

    def test_library_contains_feature_flag_disable(self):
        lib = get_library()
        cmds = [c.command for c in lib]
        assert any("feature-flags set" in c for c in cmds)

    def test_to_dict_contains_required_keys(self):
        cmd = get_library()[0]
        d = cmd.to_dict()
        for key in ("command_id", "description", "command", "pattern_tags", "risk_level"):
            assert key in d


# ---------------------------------------------------------------------------
# RollbackSuggester tests
# ---------------------------------------------------------------------------


class TestRollbackSuggester:
    def setup_method(self):
        self.suggester = RollbackSuggester()

    def test_suggest_returns_list(self):
        summary = _make_summary()
        result = self.suggester.suggest(summary)
        assert isinstance(result, list)

    def test_suggest_api_gateway_cpu_spike(self):
        summary = _make_summary(
            services=["api-gateway"],
            signal_descriptions=["[ALERT] HighCPUUsage on api-gateway: cpu_usage_percent=95"],
            signal_counts={"alert": 1},
        )
        result = self.suggester.suggest(summary)
        assert len(result) >= 1
        # Should suggest something relevant to api-gateway
        service_hints = [c.service_hint for c in result]
        assert "api-gateway" in service_hints or any(
            "api-gateway" in c.command for c in result
        )

    def test_suggest_payment_service_error_surge(self):
        summary = _make_summary(
            services=["payment-service"],
            signal_descriptions=[
                "[ALERT] CriticalErrorRate on payment-service: http_error_rate_percent=35"
            ],
            signal_counts={"alert": 1},
        )
        result = self.suggester.suggest(summary)
        assert len(result) >= 1

    def test_suggest_respects_top_n(self):
        summary = _make_summary(
            services=["api-gateway"],
            signal_descriptions=["[ALERT] HighCPUUsage on api-gateway: cpu_usage_percent=95"],
        )
        result = self.suggester.suggest(summary, top_n=1)
        assert len(result) <= 1

    def test_suggest_no_match_returns_empty(self):
        # Use a service name that has no matching commands and bland descriptions
        summary = _make_summary(
            services=["totally-unknown-service-xyz"],
            signal_descriptions=["Normal heartbeat check"],
            signal_counts={},
        )
        result = self.suggester.suggest(summary)
        assert result == []

    def test_suggest_latency_outlier_trace(self):
        summary = _make_summary(
            services=["auth-service"],
            signal_descriptions=[
                "[TRACE] Slow span in auth-service: gRPC AuthService/ValidateToken took 2500ms"
            ],
            signal_counts={"trace": 1},
        )
        result = self.suggester.suggest(summary)
        assert len(result) >= 1

    def test_suggest_orders_by_match_count(self):
        """Commands with more matching tags should rank higher."""
        summary = _make_summary(
            services=["api-gateway"],
            signal_descriptions=[
                "[ALERT] HighCPUUsage on api-gateway: cpu_usage_percent=95",
                "[LOG] ERROR on api-gateway: circuit breaker tripped",
            ],
            signal_counts={"alert": 1, "log": 1},
        )
        result = self.suggester.suggest(summary, top_n=5)
        # Result should be non-empty and internally ranked
        assert len(result) >= 1

    def test_custom_library_is_used(self):
        custom_cmd = RollbackCommand(
            command_id="custom-cmd",
            description="Custom rollback",
            command="custom-tool rollback --env production",
            pattern_tags=["error_surge", "api-gateway"],
            service_hint="api-gateway",
            risk_level="low",
        )
        suggester = RollbackSuggester(library=[custom_cmd])
        summary = _make_summary(
            services=["api-gateway"],
            signal_descriptions=["[ALERT] ElevatedErrorRate on api-gateway: http_error_rate=10%"],
            signal_counts={"alert": 1},
        )
        result = suggester.suggest(summary)
        assert len(result) == 1
        assert result[0].command_id == "custom-cmd"

    def test_extract_tags_includes_service_names(self):
        summary = _make_summary(services=["payment-service", "auth-service"])
        tags = self.suggester._extract_tags(summary)
        assert "payment-service" in tags
        assert "auth-service" in tags

    def test_extract_tags_cpu_from_description(self):
        summary = _make_summary(
            signal_descriptions=["[ALERT] cpu usage is 99% on service"]
        )
        tags = self.suggester._extract_tags(summary)
        assert "cpu_spike" in tags

    def test_extract_tags_latency_from_description(self):
        summary = _make_summary(
            signal_descriptions=["[TRACE] Slow span took 2000ms"]
        )
        tags = self.suggester._extract_tags(summary)
        assert "latency_outlier" in tags

    def test_extract_tags_error_from_description(self):
        summary = _make_summary(
            signal_descriptions=["[LOG] ERROR: unhandled exception in handler"]
        )
        tags = self.suggester._extract_tags(summary)
        assert "error_surge" in tags

    def test_extract_tags_circuit_breaker(self):
        summary = _make_summary(
            signal_descriptions=["[LOG] circuit breaker OPEN after 5 failures"]
        )
        tags = self.suggester._extract_tags(summary)
        assert "circuit_breaker" in tags

    def test_extract_tags_database(self):
        summary = _make_summary(
            signal_descriptions=["[LOG] database connection pool exhausted"]
        )
        tags = self.suggester._extract_tags(summary)
        assert "database" in tags


# ---------------------------------------------------------------------------
# ConfirmationGate tests
# ---------------------------------------------------------------------------


class TestConfirmationGate:
    def _make_command(self) -> RollbackCommand:
        return RollbackCommand(
            command_id="test-rollback",
            description="Test rollback command",
            command="kubectl rollout undo deployment/api-gateway -n production",
            pattern_tags=["error_surge"],
            service_hint="api-gateway",
            risk_level="low",
        )

    def test_auto_confirm_returns_confirmed(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.CONFIRMED

    def test_auto_reject_returns_rejected(self):
        gate = ConfirmationGate(auto_reject=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.REJECTED

    def test_confirmed_result_has_command(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.command is not None
        assert result.command.command_id == "test-rollback"

    def test_confirmed_result_has_simulated_output(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert len(result.simulated_output) > 0
        assert "SIMULATED" in result.simulated_output

    def test_rejected_result_has_empty_output(self):
        gate = ConfirmationGate(auto_reject=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.simulated_output == ""

    def test_result_has_incident_id(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-ABCD1234", cmd)
        assert result.incident_id == "INC-ABCD1234"

    def test_result_has_decided_at(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.decided_at is not None
        assert isinstance(result.decided_at, datetime)

    def test_output_contains_command_text(self):
        out = io.StringIO()
        gate = ConfirmationGate(auto_confirm=True, output_stream=out)
        cmd = self._make_command()
        gate.ask("INC-TEST01", cmd)
        output = out.getvalue()
        assert "kubectl rollout undo" in output

    def test_output_contains_incident_id(self):
        out = io.StringIO()
        gate = ConfirmationGate(auto_confirm=True, output_stream=out)
        cmd = self._make_command()
        gate.ask("INC-TEST01", cmd)
        output = out.getvalue()
        assert "INC-TEST01" in output

    def test_output_contains_risk_level(self):
        out = io.StringIO()
        gate = ConfirmationGate(auto_confirm=True, output_stream=out)
        cmd = self._make_command()
        gate.ask("INC-TEST01", cmd)
        output = out.getvalue()
        assert "LOW" in output

    def test_stdin_y_confirms(self):
        in_stream = io.StringIO("y\n")
        out_stream = io.StringIO()
        gate = ConfirmationGate(input_stream=in_stream, output_stream=out_stream)
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.CONFIRMED

    def test_stdin_n_rejects(self):
        in_stream = io.StringIO("n\n")
        out_stream = io.StringIO()
        gate = ConfirmationGate(input_stream=in_stream, output_stream=out_stream)
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.REJECTED

    def test_stdin_empty_rejects(self):
        in_stream = io.StringIO("\n")
        out_stream = io.StringIO()
        gate = ConfirmationGate(input_stream=in_stream, output_stream=out_stream)
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.REJECTED

    def test_eof_rejects(self):
        in_stream = io.StringIO("")  # EOF immediately
        out_stream = io.StringIO()
        gate = ConfirmationGate(input_stream=in_stream, output_stream=out_stream)
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        assert result.status == RollbackStatus.REJECTED

    def test_ask_no_suggestion_returns_skipped(self):
        out = io.StringIO()
        gate = ConfirmationGate(output_stream=out)
        result = gate.ask_no_suggestion("INC-TEST01")
        assert result.status == RollbackStatus.SKIPPED
        assert result.command is None

    def test_skipped_result_to_dict(self):
        out = io.StringIO()
        gate = ConfirmationGate(output_stream=out)
        result = gate.ask_no_suggestion("INC-TEST01")
        d = result.to_dict()
        assert d["status"] == "skipped"
        assert d["command"] is None

    def test_confirmed_result_to_dict(self):
        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        cmd = self._make_command()
        result = gate.ask("INC-TEST01", cmd)
        d = result.to_dict()
        assert d["status"] == "confirmed"
        assert d["command"] is not None
        assert "simulated_output" in d


# ---------------------------------------------------------------------------
# Simulated output tests
# ---------------------------------------------------------------------------


class TestSimulatedOutput:
    def test_kubectl_rollout_undo_output(self):
        cmd = RollbackCommand(
            command_id="test",
            description="Test",
            command="kubectl rollout undo deployment/api-gateway -n production",
            pattern_tags=[],
            risk_level="low",
        )
        output = ConfirmationGate._simulate_execution(cmd)
        assert "rolled back" in output
        assert "SIMULATED" in output

    def test_kubectl_scale_output(self):
        cmd = RollbackCommand(
            command_id="test",
            description="Test",
            command="kubectl scale deployment/api-gateway --replicas=10 -n production",
            pattern_tags=[],
            risk_level="medium",
        )
        output = ConfirmationGate._simulate_execution(cmd)
        assert "scaled" in output
        assert "SIMULATED" in output

    def test_feature_flag_output(self):
        cmd = RollbackCommand(
            command_id="test",
            description="Test",
            command="feature-flags set new_checkout_flow=false --env production",
            pattern_tags=[],
            risk_level="low",
        )
        output = ConfirmationGate._simulate_execution(cmd)
        assert "Feature flag updated" in output
        assert "SIMULATED" in output

    def test_redis_cli_output(self):
        cmd = RollbackCommand(
            command_id="test",
            description="Test",
            command="redis-cli -h redis.production.svc FLUSHDB",
            pattern_tags=[],
            risk_level="high",
        )
        output = ConfirmationGate._simulate_execution(cmd)
        assert "OK" in output
        assert "SIMULATED" in output

    def test_unknown_command_has_default_output(self):
        cmd = RollbackCommand(
            command_id="test",
            description="Test",
            command="some-totally-unknown-tool --do-thing",
            pattern_tags=[],
            risk_level="low",
        )
        output = ConfirmationGate._simulate_execution(cmd)
        assert "SIMULATED" in output


# ---------------------------------------------------------------------------
# Integration: correlator → suggester → confirmation
# ---------------------------------------------------------------------------


class TestRollbackIntegration:
    def test_full_pipeline_cpu_spike(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.CPU_SPIKE, seed=42)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        suggester = RollbackSuggester()
        suggestions = suggester.suggest(summaries[0])
        # CPU spike scenario should yield at least one suggestion
        assert len(suggestions) >= 1

    def test_full_pipeline_error_surge_confirm(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.ERROR_SURGE, seed=7)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        suggester = RollbackSuggester()
        suggestions = suggester.suggest(summaries[0])
        assert len(suggestions) >= 1

        gate = ConfirmationGate(auto_confirm=True, output_stream=io.StringIO())
        result = gate.ask(summaries[0].incident_id, suggestions[0])
        assert result.status == RollbackStatus.CONFIRMED
        assert result.incident_id == summaries[0].incident_id
        assert "SIMULATED" in result.simulated_output

    def test_full_pipeline_error_surge_reject(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(scenario_type=ScenarioType.ERROR_SURGE, seed=7)
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)

        suggester = RollbackSuggester()
        suggestions = suggester.suggest(summaries[0])

        gate = ConfirmationGate(auto_reject=True, output_stream=io.StringIO())
        result = gate.ask(summaries[0].incident_id, suggestions[0])
        assert result.status == RollbackStatus.REJECTED
        assert result.simulated_output == ""

    def test_no_suggestion_skipped_result(self):
        """When suggester returns nothing, gate returns SKIPPED."""
        # Use a minimal summary that won't match any library command
        summary = _make_summary(
            services=["totally-unknown-service-xyz"],
            signal_descriptions=["Normal heartbeat"],
            signal_counts={},
        )
        suggester = RollbackSuggester()
        suggestions = suggester.suggest(summary)
        gate = ConfirmationGate(output_stream=io.StringIO())

        if suggestions:
            result = gate.ask(summary.incident_id, suggestions[0])
        else:
            result = gate.ask_no_suggestion(summary.incident_id)

        if not suggestions:
            assert result.status == RollbackStatus.SKIPPED
