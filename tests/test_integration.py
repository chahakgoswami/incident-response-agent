"""
Day-7 integration test: runs a full simulated incident end-to-end through the CLI
and asserts correct outputs, audit log structure, and config loading.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from incident_agent.cli.main import cli
from incident_agent.config import load_config, get_default_config, AgentConfig
from incident_agent.config.loader import (
    CorrelationConfig,
    PostMortemConfig,
    RollbackConfig,
    _build_config,
    _simple_toml_parse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_audit(tmp_path):
    return str(tmp_path / "integration_audit.json")


@pytest.fixture
def tmp_config(tmp_path):
    """Return a path for a temporary config file."""
    return tmp_path / "agent.toml"


# ---------------------------------------------------------------------------
# Full end-to-end CLI integration tests
# ---------------------------------------------------------------------------


class TestEndToEndCLI:
    """Full pipeline: scenario → correlate → post-mortem → rollback → audit."""

    def test_cpu_spike_full_pipeline_no_rollback(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--force-mock",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        # Should show incident ID
        assert "INC-" in result.output
        # Should show severity
        assert any(s in result.output.upper() for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
        # Should show post-mortem sections
        assert "Executive Summary" in result.output
        assert "Root Cause Hypothesis" in result.output
        assert "Action Items" in result.output
        # Audit log should exist
        assert Path(tmp_audit).exists()

    def test_error_surge_full_pipeline_with_rollback_confirmed(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--force-mock",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
            input="y\n" * 10,  # confirm any rollback prompts
        )
        assert result.exit_code == 0, result.output
        assert "INC-" in result.output

        # Audit log should record the run
        data = json.loads(Path(tmp_audit).read_text())
        assert len(data) >= 1
        entry = data[0]
        assert entry["scenario_type"] == "error_surge"
        assert entry["seed"] == 7
        assert len(entry["incidents"]) >= 1

    def test_error_surge_full_pipeline_with_rollback_rejected(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--force-mock",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
            input="n\n" * 10,  # reject all rollback prompts
        )
        assert result.exit_code == 0, result.output

        data = json.loads(Path(tmp_audit).read_text())
        entry = data[0]
        incidents = entry["incidents"]
        assert len(incidents) >= 1
        # At least one incident should have rollback recorded
        rollback_statuses = [
            inc["rollback"]["status"]
            for inc in incidents
            if inc.get("rollback")
        ]
        assert len(rollback_statuses) >= 1
        # Rejected or skipped (depends on whether a suggestion was found)
        assert all(s in ("rejected", "skipped") for s in rollback_statuses)

    def test_latency_outlier_pipeline_no_postmortem_no_rollback(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "latency_outlier",
                "--seed", "5",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "INC-" in result.output

        data = json.loads(Path(tmp_audit).read_text())
        assert data[0]["scenario_type"] == "latency_outlier"

    def test_mixed_scenario_multiple_incidents(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "mixed",
                "--seed", "99",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

        data = json.loads(Path(tmp_audit).read_text())
        assert data[0]["scenario_type"] == "mixed"
        # Mixed scenario typically produces multiple incidents
        assert len(data[0]["incidents"]) >= 1

    def test_services_filter_appears_in_output(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--services", "api-gateway,payment-service",
                "--seed", "1",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        # At least one of the specified services should appear
        assert "api-gateway" in result.output or "payment-service" in result.output

    def test_window_option_propagated(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--window", "10",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

        data = json.loads(Path(tmp_audit).read_text())
        assert data[0]["window_minutes"] == 10

    def test_force_mock_reflected_in_audit(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--force-mock",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "mock" in result.output.lower()

        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        assert len(incidents) >= 1
        pm = incidents[0].get("postmortem")
        assert pm is not None
        assert "mock" in pm["model_used"]

    def test_audit_entry_structure_complete(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "77",
                "--force-mock",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
            input="n\n" * 10,
        )
        assert result.exit_code == 0, result.output

        data = json.loads(Path(tmp_audit).read_text())
        entry = data[0]

        # Top-level audit fields
        required_top = [
            "started_at", "finished_at", "scenario_id",
            "scenario_type", "seed", "window_minutes", "incidents",
        ]
        for key in required_top:
            assert key in entry, f"Missing top-level audit key: {key}"

        # Incident-level fields
        assert len(entry["incidents"]) >= 1
        inc = entry["incidents"][0]
        required_inc = [
            "incident_id", "severity", "score",
            "affected_services", "signal_counts",
        ]
        for key in required_inc:
            assert key in inc, f"Missing incident audit key: {key}"

        # Severity is a valid string
        assert inc["severity"] in ("critical", "high", "medium", "low", "unknown")
        # Score is a non-negative number
        assert inc["score"] >= 0
        # Affected services is a non-empty list
        assert isinstance(inc["affected_services"], list)
        assert len(inc["affected_services"]) >= 1

    def test_postmortem_sections_in_audit(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--force-mock",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        pm = data[0]["incidents"][0]["postmortem"]
        assert pm is not None
        assert "sections" in pm
        assert isinstance(pm["sections"], list)
        assert len(pm["sections"]) >= 5
        expected_sections = {
            "Executive Summary",
            "Timeline",
            "Root Cause Hypothesis",
            "Impact Estimate",
            "Action Items",
        }
        for sec in expected_sections:
            assert sec in pm["sections"], f"Missing postmortem section: {sec}"

    def test_rollback_confirmed_recorded_in_audit(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
            input="y\n" * 10,
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        rollbacks = [inc["rollback"] for inc in incidents if inc.get("rollback")]
        assert len(rollbacks) >= 1
        # At least one should be confirmed
        statuses = [rb["status"] for rb in rollbacks]
        assert "confirmed" in statuses

    def test_rollback_rejected_recorded_in_audit(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
            input="n\n" * 10,
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        rollbacks = [inc["rollback"] for inc in incidents if inc.get("rollback")]
        assert len(rollbacks) >= 1
        statuses = [rb["status"] for rb in rollbacks]
        assert all(s in ("rejected", "skipped") for s in statuses)

    def test_multiple_runs_append_to_audit(self, runner, tmp_audit):
        for seed in [1, 2, 3]:
            runner.invoke(
                cli,
                [
                    "run",
                    "--scenario", "cpu_spike",
                    "--seed", str(seed),
                    "--no-postmortem",
                    "--no-rollback",
                    "--no-notify",
                    "--audit-log", tmp_audit,
                ],
            )
        data = json.loads(Path(tmp_audit).read_text())
        assert len(data) == 3
        assert data[0]["seed"] == 1
        assert data[1]["seed"] == 2
        assert data[2]["seed"] == 3

    def test_show_audit_after_run(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        result = runner.invoke(cli, ["show-audit", "--audit-log", tmp_audit])
        assert result.exit_code == 0
        assert "cpu_spike" in result.output
        assert "INC-" in result.output

    def test_correlation_output_shows_signal_counts(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "mixed",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        # Signal counts shown as "N type(s)"
        assert "(s)" in result.output

    def test_correlation_output_shows_window_times(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--no-notify",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        # UTC time strings should appear in the window line
        assert "UTC" in result.output

    def test_notify_flag_posts_to_channel(self, runner, tmp_audit):
        """With --no-notify omitted, Slack notifications are posted."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--force-mock",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        # Notification count line should appear
        assert "notification" in result.output.lower() or "SLACK" in result.output

    def test_reproducible_scenario_same_incident_id_structure(self, runner, tmp_audit):
        """Two runs with the same seed produce the same number of incidents."""
        audit1 = tmp_audit
        audit2 = tmp_audit.replace("integration_audit", "integration_audit2")

        for audit_path in [audit1, audit2]:
            runner.invoke(
                cli,
                [
                    "run",
                    "--scenario", "cpu_spike",
                    "--seed", "42",
                    "--no-postmortem",
                    "--no-rollback",
                    "--no-notify",
                    "--audit-log", audit_path,
                ],
            )

        data1 = json.loads(Path(audit1).read_text())
        data2 = json.loads(Path(audit2).read_text())

        assert len(data1[0]["incidents"]) == len(data2[0]["incidents"])
        assert data1[0]["scenario_type"] == data2[0]["scenario_type"]


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------


class TestConfigLoader:
    def test_default_config_returns_agent_config(self):
        cfg = get_default_config()
        assert isinstance(cfg, AgentConfig)

    def test_default_correlation_window(self):
        cfg = get_default_config()
        assert cfg.correlation.window_minutes == 5

    def test_default_min_signals(self):
        cfg = get_default_config()
        assert cfg.correlation.min_signals == 1

    def test_default_latency_threshold(self):
        cfg = get_default_config()
        assert cfg.correlation.latency_error_threshold_ms == 800.0

    def test_default_postmortem_model(self):
        cfg = get_default_config()
        assert cfg.postmortem.model == "gpt-4o-mini"

    def test_default_force_mock_false(self):
        cfg = get_default_config()
        assert cfg.postmortem.force_mock is False

    def test_default_top_n(self):
        cfg = get_default_config()
        assert cfg.rollback.top_n == 3

    def test_default_auto_confirm_false(self):
        cfg = get_default_config()
        assert cfg.rollback.auto_confirm is False

    def test_default_notifications_enabled(self):
        cfg = get_default_config()
        assert cfg.notifications.enabled is True

    def test_default_slack_channel(self):
        cfg = get_default_config()
        assert cfg.notifications.slack_channel == "#incidents"

    def test_default_audit_log_path(self):
        cfg = get_default_config()
        assert cfg.audit.log_path == "incident_audit.json"

    def test_load_config_nonexistent_file_returns_defaults(self, tmp_path):
        path = tmp_path / "nonexistent.toml"
        cfg = load_config(path)
        assert isinstance(cfg, AgentConfig)
        assert cfg.correlation.window_minutes == 5

    def test_load_config_from_toml(self, tmp_config):
        tmp_config.write_text(
            "[correlation]\n"
            "window_minutes = 10\n"
            "min_signals = 2\n"
            "latency_error_threshold_ms = 1000.0\n"
            "[postmortem]\n"
            "force_mock = true\n"
            "[rollback]\n"
            "top_n = 5\n"
        )
        cfg = load_config(tmp_config)
        assert cfg.correlation.window_minutes == 10
        assert cfg.correlation.min_signals == 2
        assert cfg.correlation.latency_error_threshold_ms == 1000.0
        assert cfg.postmortem.force_mock is True
        assert cfg.rollback.top_n == 5

    def test_load_config_partial_overrides_defaults(self, tmp_config):
        tmp_config.write_text(
            "[correlation]\n"
            "window_minutes = 15\n"
        )
        cfg = load_config(tmp_config)
        assert cfg.correlation.window_minutes == 15
        # Unspecified values keep defaults
        assert cfg.correlation.min_signals == 1
        assert cfg.postmortem.model == "gpt-4o-mini"

    def test_load_config_invalid_toml_returns_defaults(self, tmp_config):
        tmp_config.write_text("this is not valid toml {{{ \x00")
        cfg = load_config(tmp_config)
        # Should fall back to defaults gracefully
        assert isinstance(cfg, AgentConfig)

    def test_to_dict_is_json_serializable(self):
        import json
        cfg = get_default_config()
        data = cfg.to_dict()
        serialized = json.dumps(data)
        assert len(serialized) > 0

    def test_to_dict_contains_all_sections(self):
        cfg = get_default_config()
        data = cfg.to_dict()
        for section in ("correlation", "postmortem", "rollback", "notifications", "audit"):
            assert section in data

    def test_extra_commands_loaded_from_config(self, tmp_config):
        tmp_config.write_text(
            "[[rollback.extra_commands]]\n"
            'command_id = "my-rollback"\n'
            'description = "My custom rollback"\n'
            'command = "kubectl rollout undo deployment/my-svc -n production"\n'
            'pattern_tags = ["error_surge", "my-svc"]\n'
            'service_hint = "my-svc"\n'
            'risk_level = "low"\n'
        )
        cfg = load_config(tmp_config)
        assert len(cfg.rollback.extra_commands) == 1
        cmd = cfg.rollback.extra_commands[0]
        assert cmd.command_id == "my-rollback"
        assert cmd.risk_level == "low"
        assert "error_surge" in cmd.pattern_tags

    def test_build_config_from_raw_dict(self):
        raw = {
            "correlation": {"window_minutes": 3},
            "rollback": {"top_n": 10},
        }
        cfg = _build_config(raw)
        assert cfg.correlation.window_minutes == 3
        assert cfg.rollback.top_n == 10
        # Defaults for unspecified values
        assert cfg.postmortem.force_mock is False


# ---------------------------------------------------------------------------
# Config-driven pipeline test
# ---------------------------------------------------------------------------


class TestConfigDrivenPipeline:
    """Ensure the config values are actually used by the pipeline components."""

    def test_correlation_engine_uses_config_window(self):
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.config import get_default_config

        cfg = get_default_config()
        engine = CorrelationEngine(
            window_minutes=cfg.correlation.window_minutes,
            min_signals=cfg.correlation.min_signals,
            latency_error_threshold_ms=cfg.correlation.latency_error_threshold_ms,
        )
        assert engine.window_minutes == 5
        assert engine.min_signals == 1

    def test_postmortem_drafter_uses_config_force_mock(self):
        from incident_agent.postmortem import PostMortemDrafter
        from incident_agent.config import get_default_config

        cfg = get_default_config()
        drafter = PostMortemDrafter(
            model=cfg.postmortem.model,
            force_mock=True,  # override for test
        )
        assert drafter.model == "gpt-4o-mini"
        assert drafter.force_mock is True

    def test_rollback_suggester_uses_config_extra_commands(self):
        from incident_agent.rollback import RollbackSuggester, RollbackCommand
        from incident_agent.config import get_default_config
        from incident_agent.config.loader import ExtraRollbackCommand

        # Simulate config with one extra command
        extra = ExtraRollbackCommand(
            command_id="cfg-custom",
            description="Config-sourced custom rollback",
            command="my-tool rollback --service api-gateway",
            pattern_tags=["error_surge", "api-gateway"],
            service_hint="api-gateway",
            risk_level="low",
        )

        # Convert ExtraRollbackCommand → RollbackCommand for the suggester
        rollback_cmd = RollbackCommand(
            command_id=extra.command_id,
            description=extra.description,
            command=extra.command,
            pattern_tags=extra.pattern_tags,
            service_hint=extra.service_hint,
            risk_level=extra.risk_level,
        )

        from incident_agent.rollback.library import get_library
        library = get_library() + [rollback_cmd]
        suggester = RollbackSuggester(library=library)

        # Create a summary that should match the custom command
        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType

        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.ERROR_SURGE,
            services=["api-gateway"],
            seed=42,
        )
        engine = CorrelationEngine()
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        suggestions = suggester.suggest(summaries[0])
        cmd_ids = [s.command_id for s in suggestions]
        assert "cfg-custom" in cmd_ids

    def test_full_pipeline_with_custom_config(self, tmp_path):
        """Load a TOML config and use it to drive a full scenario run."""
        config_path = tmp_path / "agent.toml"
        config_path.write_text(
            "[correlation]\n"
            "window_minutes = 10\n"
            "min_signals = 1\n"
            "[postmortem]\n"
            "force_mock = true\n"
            "[rollback]\n"
            "top_n = 2\n"
        )
        cfg = load_config(config_path)

        from incident_agent.correlator import CorrelationEngine
        from incident_agent.mock_data import generate_incident_scenario
        from incident_agent.mock_data.scenario import ScenarioType
        from incident_agent.postmortem import PostMortemDrafter
        from incident_agent.rollback import RollbackSuggester

        scenario = generate_incident_scenario(
            scenario_type=ScenarioType.ERROR_SURGE,
            seed=42,
        )
        engine = CorrelationEngine(
            window_minutes=cfg.correlation.window_minutes,
            min_signals=cfg.correlation.min_signals,
        )
        summaries = engine.correlate_scenario(scenario)
        assert len(summaries) >= 1

        drafter = PostMortemDrafter(force_mock=cfg.postmortem.force_mock)
        pm = drafter.draft(summaries[0])
        assert len(pm.sections) == 5

        suggester = RollbackSuggester()
        suggestions = suggester.suggest(summaries[0], top_n=cfg.rollback.top_n)
        assert len(suggestions) <= cfg.rollback.top_n


# ---------------------------------------------------------------------------
# TOML parsing unit tests
# ---------------------------------------------------------------------------


class TestTomlParser:
    def test_parse_simple_section_and_value(self):
        toml = "[correlation]\nwindow_minutes = 10\n"
        result = _simple_toml_parse(toml)
        assert result["correlation"]["window_minutes"] == 10

    def test_parse_float_value(self):
        toml = "[correlation]\nlatency_error_threshold_ms = 1200.5\n"
        result = _simple_toml_parse(toml)
        assert result["correlation"]["latency_error_threshold_ms"] == 1200.5

    def test_parse_bool_true(self):
        toml = "[postmortem]\nforce_mock = true\n"
        result = _simple_toml_parse(toml)
        assert result["postmortem"]["force_mock"] is True

    def test_parse_bool_false(self):
        toml = "[postmortem]\nforce_mock = false\n"
        result = _simple_toml_parse(toml)
        assert result["postmortem"]["force_mock"] is False

    def test_parse_string_value(self):
        toml = '[postmortem]\nmodel = "gpt-4o"\n'
        result = _simple_toml_parse(toml)
        assert result["postmortem"]["model"] == "gpt-4o"

    def test_parse_inline_array(self):
        toml = '[[rollback.extra_commands]]\npattern_tags = ["error_surge", "api-gateway"]\n'
        result = _simple_toml_parse(toml)
        cmds = result.get("rollback", {}).get("extra_commands", [])
        assert len(cmds) == 1
        assert "error_surge" in cmds[0]["pattern_tags"]

    def test_parse_comment_ignored(self):
        toml = "# This is a comment\n[correlation]\nwindow_minutes = 7\n"
        result = _simple_toml_parse(toml)
        assert result["correlation"]["window_minutes"] == 7

    def test_parse_blank_lines_ignored(self):
        toml = "\n\n[audit]\n\nlog_path = \"audit.json\"\n\n"
        result = _simple_toml_parse(toml)
        assert result["audit"]["log_path"] == "audit.json"

    def test_parse_multiple_sections(self):
        toml = (
            "[correlation]\nwindow_minutes = 3\n"
            "[rollback]\ntop_n = 5\n"
        )
        result = _simple_toml_parse(toml)
        assert result["correlation"]["window_minutes"] == 3
        assert result["rollback"]["top_n"] == 5

    def test_parse_empty_string_returns_empty_dict(self):
        result = _simple_toml_parse("")
        assert result == {}
