"""Tests for the Day-5 CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from incident_agent.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_audit(tmp_path):
    return str(tmp_path / "audit.json")


# ---------------------------------------------------------------------------
# Basic invocation tests
# ---------------------------------------------------------------------------


class TestCliHelp:
    def test_cli_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Incident Response Agent" in result.output

    def test_run_help(self, runner):
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--scenario" in result.output

    def test_list_scenarios_help(self, runner):
        result = runner.invoke(cli, ["list-scenarios", "--help"])
        assert result.exit_code == 0

    def test_show_audit_help(self, runner):
        result = runner.invoke(cli, ["show-audit", "--help"])
        assert result.exit_code == 0


class TestListScenarios:
    def test_list_scenarios_shows_all_types(self, runner):
        result = runner.invoke(cli, ["list-scenarios"])
        assert result.exit_code == 0
        assert "cpu_spike" in result.output
        assert "error_surge" in result.output
        assert "latency_outlier" in result.output
        assert "mixed" in result.output


# ---------------------------------------------------------------------------
# run command tests
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_run_cpu_spike_no_rollback(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "cpu_spike" in result.output.lower() or "Generating" in result.output

    def test_run_error_surge_no_postmortem(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

    def test_run_mixed_scenario_with_seed(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "mixed",
                "--seed", "99",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

    def test_run_latency_outlier(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "latency_outlier",
                "--seed", "5",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

    def test_run_with_services_filter(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--services", "api-gateway,payment-service",
                "--seed", "1",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output

    def test_run_force_mock_flag(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--force-mock",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "mock" in result.output.lower()

    def test_run_shows_incident_id(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "10",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "INC-" in result.output

    def test_run_shows_severity(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "3",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0
        # At least one severity level should appear
        assert any(
            sev in result.output.upper()
            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        )

    def test_run_shows_signal_counts(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "mixed",
                "--seed", "2",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0
        # Should show signal type breakdown
        assert "(s)" in result.output  # e.g. "3 alert(s)"

    def test_run_rollback_auto_confirm(self, runner, tmp_audit):
        """Simulate user pressing 'y' for rollback confirmation."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--audit-log", tmp_audit,
            ],
            input="y\n",  # auto-confirm rollback
        )
        assert result.exit_code == 0, result.output

    def test_run_rollback_auto_reject(self, runner, tmp_audit):
        """Simulate user pressing 'n' for rollback rejection."""
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-postmortem",
                "--audit-log", tmp_audit,
            ],
            input="n\n",
        )
        assert result.exit_code == 0, result.output

    def test_run_postmortem_sections_shown(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "4",
                "--force-mock",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Executive Summary" in result.output
        assert "Root Cause Hypothesis" in result.output

    def test_run_window_option(self, runner, tmp_audit):
        result = runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--window", "10",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Audit log tests
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_audit_log_created(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        assert Path(tmp_audit).exists()

    def test_audit_log_is_valid_json(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_audit_entry_has_required_fields(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        entry = data[0]
        assert "started_at" in entry
        assert "finished_at" in entry
        assert "scenario_id" in entry
        assert "scenario_type" in entry
        assert "incidents" in entry

    def test_audit_entry_scenario_type_matches(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        assert data[0]["scenario_type"] == "error_surge"

    def test_audit_log_appends_entries(self, runner, tmp_audit):
        """Two separate runs should produce two entries in the audit log."""
        for seed in [1, 2]:
            runner.invoke(
                cli,
                [
                    "run",
                    "--scenario", "cpu_spike",
                    "--seed", str(seed),
                    "--no-postmortem",
                    "--no-rollback",
                    "--audit-log", tmp_audit,
                ],
            )
        data = json.loads(Path(tmp_audit).read_text())
        assert len(data) == 2

    def test_audit_incident_has_severity(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        assert len(incidents) >= 1
        assert "severity" in incidents[0]

    def test_audit_incident_has_affected_services(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        assert "affected_services" in incidents[0]
        assert isinstance(incidents[0]["affected_services"], list)

    def test_audit_rollback_status_recorded(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--audit-log", tmp_audit,
            ],
            input="n\n",
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        rollback = incidents[0].get("rollback")
        assert rollback is not None
        assert "status" in rollback

    def test_audit_postmortem_recorded(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--force-mock",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        incidents = data[0]["incidents"]
        pm = incidents[0].get("postmortem")
        assert pm is not None
        assert "title" in pm
        assert "model_used" in pm

    def test_audit_seed_recorded(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "mixed",
                "--seed", "123",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        data = json.loads(Path(tmp_audit).read_text())
        assert data[0]["seed"] == 123


# ---------------------------------------------------------------------------
# show-audit command tests
# ---------------------------------------------------------------------------


class TestShowAudit:
    def test_show_audit_empty(self, runner, tmp_audit):
        result = runner.invoke(cli, ["show-audit", "--audit-log", tmp_audit])
        assert result.exit_code == 0
        assert "No audit entries" in result.output

    def test_show_audit_after_run(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "42",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        result = runner.invoke(cli, ["show-audit", "--audit-log", tmp_audit])
        assert result.exit_code == 0
        assert "cpu_spike" in result.output

    def test_show_audit_shows_scenario_id(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "error_surge",
                "--seed", "7",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        result = runner.invoke(cli, ["show-audit", "--audit-log", tmp_audit])
        assert result.exit_code == 0
        assert "INC-" in result.output

    def test_show_audit_last_option(self, runner, tmp_audit):
        # Run three times
        for seed in [1, 2, 3]:
            runner.invoke(
                cli,
                [
                    "run",
                    "--scenario", "cpu_spike",
                    "--seed", str(seed),
                    "--no-postmortem",
                    "--no-rollback",
                    "--audit-log", tmp_audit,
                ],
            )
        result = runner.invoke(
            cli, ["show-audit", "--audit-log", tmp_audit, "--last", "2"]
        )
        assert result.exit_code == 0
        assert "2 of 3" in result.output


# ---------------------------------------------------------------------------
# clear-audit command tests
# ---------------------------------------------------------------------------


class TestClearAudit:
    def test_clear_audit_confirmed(self, runner, tmp_audit):
        # Write some entries first
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "1",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        # Clear with confirmation
        result = runner.invoke(
            cli,
            ["clear-audit", "--audit-log", tmp_audit],
            input="y\n",
        )
        assert result.exit_code == 0
        data = json.loads(Path(tmp_audit).read_text())
        assert data == []

    def test_clear_audit_aborted(self, runner, tmp_audit):
        runner.invoke(
            cli,
            [
                "run",
                "--scenario", "cpu_spike",
                "--seed", "1",
                "--no-postmortem",
                "--no-rollback",
                "--audit-log", tmp_audit,
            ],
        )
        # Abort clear
        result = runner.invoke(
            cli,
            ["clear-audit", "--audit-log", tmp_audit],
            input="N\n",
        )
        # Exit code 1 means aborted by click
        assert result.exit_code != 0 or "Aborted" in result.output
        # Audit log should still have entries
        data = json.loads(Path(tmp_audit).read_text())
        assert len(data) >= 1
