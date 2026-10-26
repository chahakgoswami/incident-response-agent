# Incident Response Agent

AI agent that correlates alerts/logs, drafts post-mortems, and suggests rollbacks for on-call engine

**Domain:** Agentic AI
**Language:** python
**Demonstrates:** You make on-call humans faster, not obsolete.

## 7-day build plan

- [ ] Day 1: Set up the project structure with a mock data layer — create simulated alert, trace, and log generators that produce realistic incident data (CPU spikes, error rate surges, latency outliers) in-memory without any external dependencies.
- [ ] Day 2: Build the correlation engine that ingests the mock alerts, traces, and logs, groups them by time window and service tag, and produces a ranked IncidentSummary dataclass with severity, affected services, and contributing signals.
- [ ] Day 3: Integrate an LLM call (OpenAI-compatible, key from env var, with a local mock/stub fallback) to draft a structured post-mortem document from the IncidentSummary, including timeline, root-cause hypothesis, and impact estimate.
- [ ] Day 4: Add a rollback command suggester that maps incident patterns to a library of predefined safe rollback commands (e.g., kubectl rollout undo, feature-flag disable), always printing the suggested command and requiring explicit human y/n confirmation before any simulated execution.
- [ ] Day 5: Build an interactive CLI (using Click) that ties all components together — operators can feed in a simulated incident, view the correlation report, read the drafted post-mortem, and approve or reject the rollback suggestion with full audit logging to a local JSON file.
- [ ] Day 6: Add a Slack-style notification mock (in-process event bus) so the agent posts correlation summaries and post-mortem drafts to a simulated channel, and write pytest unit tests covering the correlator, suggester, and confirmation gate with at least 80% coverage.
- [ ] Day 7: Package the project with pyproject.toml and a console-script entry point, add a config file for tuning correlation thresholds and rollback mappings, and write an integration test that runs a full simulated incident end-to-end through CLI and asserts correct outputs.

_A comprehensive README with an architecture diagram is generated on Day 7._
