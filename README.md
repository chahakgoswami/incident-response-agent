# Incident Response Agent

AI agent that correlates alerts/logs, drafts post-mortems, and suggests rollbacks for on-call engineers.

> **You make on-call humans faster, not obsolete.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Incident Response Agent                   │
│                                                             │
│  ┌──────────────┐    ┌──────────────────────────────────┐  │
│  │  Mock Data   │    │         CLI (Click)               │  │
│  │   Layer      │───▶│  incident-agent run --scenario …  │  │
│  │              │    └──────────┬────────────────────────┘  │
│  │  • Alerts    │               │                           │
│  │  • Traces    │               ▼                           │
│  │  • Logs      │    ┌──────────────────┐                   │
│  └──────────────┘    │ Correlation      │                   │
│                       │ Engine          │                   │
│  ┌──────────────┐    │ (time-window +  │                   │
│  │  agent.toml  │───▶│  service tags)  │                   │
│  │  (config)    │    └──────┬──────────┘                   │
│  └──────────────┘           │ IncidentSummary               │
│                              ▼                              │
│                   ┌──────────────────┐                      │
│                   │ PostMortem       │                      │
│                   │ Drafter          │                      │
│                   │ (OpenAI / mock)  │                      │
│                   └──────┬───────────┘                      │
│                          │ PostMortem                       │
│                          ▼                                  │
│                   ┌──────────────────┐                      │
│                   │ Rollback         │                      │
│                   │ Suggester        │                      │
│                   └──────┬───────────┘                      │
│                          │ RollbackCommand                  │
│                          ▼                                  │
│                   ┌──────────────────┐                      │
│                   │ Confirmation     │  y/n prompt          │
│                   │ Gate             │◀─────────────────    │
│                   └──────┬───────────┘                      │
│                          │                                  │
│           ┌──────────────┼──────────────┐                   │
│           ▼              ▼              ▼                   │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐            │
│  │ Slack-style  │ │  Audit   │ │  Simulated   │            │
│  │ Notifier     │ │  Log     │ │  Execution   │            │
│  │ (in-process) │ │  (JSON)  │ │  Output      │            │
│  └──────────────┘ └──────────┘ └──────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

## Features

- **Mock data layer** — generates realistic CPU spikes, error surges, and latency outliers in-memory (no external dependencies)
- **Correlation engine** — groups signals by time window and service tag, ranks incidents by severity score
- **LLM post-mortem drafter** — uses OpenAI API when `OPENAI_API_KEY` is set; falls back to a deterministic local stub
- **Rollback suggester** — maps incident patterns to a library of predefined safe rollback commands (kubectl, feature-flags, redis, etc.)
- **Human confirmation gate** — always prints the suggested command and requires explicit `y/n` before simulated execution
- **Interactive CLI** — `Click`-based interface with correlation reports, post-mortem reading, rollback approval, and JSON audit logging
- **Slack-style notifications** — in-process event bus posts correlation summaries, post-mortems, and rollback decisions to a simulated channel
- **Config file** — `agent.toml` lets you tune correlation thresholds, rollback mappings, and all defaults

## Quick Start

### Install

```bash
# From source
pip install -e .

# With LLM support
pip install -e ".[llm]"

# Development
pip install -e ".[dev]"
```

### Run a simulated incident

```bash
# CPU spike scenario (with mock LLM)
incident-agent run --scenario cpu_spike --seed 42 --force-mock

# Error surge with auto-reject rollback
incident-agent run --scenario error_surge --seed 7 --force-mock

# Mixed incident, no notifications, custom audit log
incident-agent run --scenario mixed --seed 99 --no-notify --audit-log my_audit.json
```

### List available scenarios

```bash
incident-agent list-scenarios
```

### View audit log

```bash
incident-agent show-audit --last 5
```

### Clear audit log

```bash
incident-agent clear-audit
```

## Configuration

Copy `agent.toml` to your working directory and edit:

```toml
[correlation]
window_minutes = 5
min_signals = 1
latency_error_threshold_ms = 800.0

[postmortem]
model = "gpt-4o-mini"
force_mock = false

[rollback]
top_n = 3
auto_confirm = false

# Add custom rollback commands:
[[rollback.extra_commands]]
command_id   = "my-custom-rollback"
description  = "Roll back my-service"
command      = "kubectl rollout undo deployment/my-service -n production"
pattern_tags = ["error_surge", "my-service"]
service_hint = "my-service"
risk_level   = "low"

[notifications]
enabled = true
slack_channel = "#incidents"

[audit]
log_path = "incident_audit.json"
```

## LLM Integration

Set `OPENAI_API_KEY` in your environment to use the real OpenAI API:

```bash
export OPENAI_API_KEY=sk-...
incident-agent run --scenario error_surge --seed 7
```

Without the key (or with `--force-mock`), the agent uses a deterministic local stub that produces a fully structured post-mortem without any network calls.

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=incident_agent --cov-report=term-missing

# Integration tests only
pytest tests/test_integration.py -v
```

## Project Structure

```
incident_agent/
├── __init__.py
├── config/             # Config loader (agent.toml)
│   ├── __init__.py
│   └── loader.py
├── mock_data/          # Simulated alert/trace/log generators
│   ├── __init__.py
│   ├── alerts.py
│   ├── traces.py
│   ├── logs.py
│   └── scenario.py
├── correlator/         # Correlation engine
│   ├── __init__.py
│   ├── engine.py
│   └── models.py
├── postmortem/         # LLM post-mortem drafter
│   ├── __init__.py
│   ├── drafter.py
│   └── models.py
├── rollback/           # Rollback suggester + confirmation gate
│   ├── __init__.py
│   ├── library.py
│   ├── models.py
│   ├── suggester.py
│   └── confirmation.py
├── notifications/      # Slack-style event bus + notifier
│   ├── __init__.py
│   ├── bus.py
│   ├── channel.py
│   └── notifier.py
└── cli/                # Click CLI
    ├── __init__.py
    └── main.py
tests/
├── test_mock_data.py
├── test_correlator.py
├── test_postmortem.py
├── test_rollback.py
├── test_notifications.py
├── test_cli.py
└── test_integration.py  # Day-7 end-to-end + config tests
agent.toml              # Default configuration file
pyproject.toml          # Package metadata + console-script entry point
```
