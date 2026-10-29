"""Predefined library of safe rollback commands mapped to incident patterns."""

from __future__ import annotations

from typing import List

from .models import RollbackCommand

# ---------------------------------------------------------------------------
# The rollback command library
# ---------------------------------------------------------------------------
# Each command is tagged with one or more incident pattern strings.
# The suggester matches these tags against IncidentSummary signals.
# ---------------------------------------------------------------------------

ROLLBACK_LIBRARY: List[RollbackCommand] = [
    # -----------------------------------------------------------------------
    # Kubernetes deployment rollbacks
    # -----------------------------------------------------------------------
    RollbackCommand(
        command_id="k8s-rollout-undo-api-gateway",
        description="Roll back the api-gateway Deployment to the previous revision.",
        command="kubectl rollout undo deployment/api-gateway -n production",
        pattern_tags=["error_surge", "cpu_spike", "high_error_rate", "api-gateway"],
        service_hint="api-gateway",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="k8s-rollout-undo-payment-service",
        description="Roll back the payment-service Deployment to the previous revision.",
        command="kubectl rollout undo deployment/payment-service -n production",
        pattern_tags=["error_surge", "high_error_rate", "payment-service"],
        service_hint="payment-service",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="k8s-rollout-undo-auth-service",
        description="Roll back the auth-service Deployment to the previous revision.",
        command="kubectl rollout undo deployment/auth-service -n production",
        pattern_tags=["error_surge", "latency_outlier", "auth-service"],
        service_hint="auth-service",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="k8s-rollout-undo-user-service",
        description="Roll back the user-service Deployment to the previous revision.",
        command="kubectl rollout undo deployment/user-service -n production",
        pattern_tags=["error_surge", "cpu_spike", "user-service"],
        service_hint="user-service",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="k8s-rollout-undo-recommendation-engine",
        description="Roll back the recommendation-engine Deployment to the previous revision.",
        command="kubectl rollout undo deployment/recommendation-engine -n production",
        pattern_tags=["latency_outlier", "cpu_spike", "recommendation-engine"],
        service_hint="recommendation-engine",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="k8s-rollout-undo-inventory-service",
        description="Roll back the inventory-service Deployment to the previous revision.",
        command="kubectl rollout undo deployment/inventory-service -n production",
        pattern_tags=["error_surge", "latency_outlier", "inventory-service"],
        service_hint="inventory-service",
        risk_level="low",
    ),
    # -----------------------------------------------------------------------
    # Feature-flag disables
    # -----------------------------------------------------------------------
    RollbackCommand(
        command_id="ff-disable-new-checkout-flow",
        description="Disable the 'new_checkout_flow' feature flag to revert checkout changes.",
        command="feature-flags set new_checkout_flow=false --env production",
        pattern_tags=["error_surge", "payment-service", "high_error_rate"],
        service_hint="payment-service",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="ff-disable-new-recommendation-algo",
        description="Disable the 'new_recommendation_algo' feature flag.",
        command="feature-flags set new_recommendation_algo=false --env production",
        pattern_tags=["latency_outlier", "cpu_spike", "recommendation-engine"],
        service_hint="recommendation-engine",
        risk_level="low",
    ),
    RollbackCommand(
        command_id="ff-disable-aggressive-caching",
        description="Disable aggressive caching feature flag that may cause stale data.",
        command="feature-flags set aggressive_caching=false --env production",
        pattern_tags=["error_surge", "latency_outlier"],
        service_hint=None,
        risk_level="low",
    ),
    # -----------------------------------------------------------------------
    # Scaling actions
    # -----------------------------------------------------------------------
    RollbackCommand(
        command_id="k8s-scale-up-api-gateway",
        description="Scale api-gateway to 10 replicas to absorb a traffic spike.",
        command="kubectl scale deployment/api-gateway --replicas=10 -n production",
        pattern_tags=["cpu_spike", "api-gateway", "high_load"],
        service_hint="api-gateway",
        risk_level="medium",
    ),
    RollbackCommand(
        command_id="k8s-scale-up-payment-service",
        description="Scale payment-service to 6 replicas to handle elevated load.",
        command="kubectl scale deployment/payment-service --replicas=6 -n production",
        pattern_tags=["cpu_spike", "latency_outlier", "payment-service"],
        service_hint="payment-service",
        risk_level="medium",
    ),
    # -----------------------------------------------------------------------
    # Circuit-breaker / rate-limit resets
    # -----------------------------------------------------------------------
    RollbackCommand(
        command_id="reset-circuit-breaker-auth",
        description="Reset the circuit breaker for auth-service to allow traffic flow.",
        command="curl -X POST https://internal-api/circuit-breaker/auth-service/reset",
        pattern_tags=["error_surge", "auth-service", "circuit_breaker"],
        service_hint="auth-service",
        risk_level="medium",
    ),
    RollbackCommand(
        command_id="reset-rate-limit-api-gateway",
        description="Reset rate-limiting counters on the api-gateway to restore normal throughput.",
        command="curl -X DELETE https://internal-api/rate-limits/api-gateway",
        pattern_tags=["latency_outlier", "api-gateway", "rate_limit"],
        service_hint="api-gateway",
        risk_level="medium",
    ),
    # -----------------------------------------------------------------------
    # Database / cache
    # -----------------------------------------------------------------------
    RollbackCommand(
        command_id="restart-db-connection-pool",
        description="Restart the database connection pool manager to clear exhausted connections.",
        command="kubectl rollout restart deployment/db-pool-manager -n production",
        pattern_tags=["error_surge", "latency_outlier", "database"],
        service_hint=None,
        risk_level="medium",
    ),
    RollbackCommand(
        command_id="flush-redis-cache",
        description="Flush the Redis cache to clear potentially corrupted entries.",
        command="redis-cli -h redis.production.svc FLUSHDB",
        pattern_tags=["error_surge", "latency_outlier", "cache"],
        service_hint=None,
        risk_level="high",
    ),
]


def get_library() -> List[RollbackCommand]:
    """Return the full rollback command library."""
    return list(ROLLBACK_LIBRARY)
