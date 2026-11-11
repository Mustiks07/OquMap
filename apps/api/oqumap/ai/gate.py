"""Who may spend the model budget, and when the live path must not be used.

Live calls require: a configured provider, a non-demo tenant, an allowed role, remaining call quota (per org per
day, per user per hour) and token budget (per org per day), a closed circuit breaker, and — for non-synthetic
data — an explicit operator permission for a provider whose data policy allows it. All counters live in the
shared ``rate_limits`` table, so they hold across API/worker processes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ApiError
from ..services import ratelimit


@dataclass
class LiveGate:
    session: Session
    org_id: str
    user_id: str
    roles: list[str]
    org_is_ephemeral: bool
    org_is_demo: bool

    @classmethod
    def for_principal(cls, session: Session, p) -> LiveGate:
        return cls(session, p.org_id, p.user_id, list(p.user.roles or []), bool(p.org.is_ephemeral), bool(p.org.is_demo))

    def acquire_dry_run(self) -> str | None:
        s = get_settings()
        if self.org_is_ephemeral or (s.deployment_mode == "public_demo" and self.org_is_demo):
            return "live_disabled_for_public_demo"
        if not set(self.roles) & set(s.llm_live_roles):
            return "live_not_allowed_for_role"
        return None

    def acquire(self, synthetic: bool = True, data_policy: str = "api_default") -> str | None:
        """Consume one live call. Returns None when allowed, otherwise the fallback reason code."""
        s = get_settings()
        dry = self.acquire_dry_run()
        if dry:
            return dry
        if not synthetic and (not s.llm_real_data_allowed or data_policy in ("may_train", "depends_on_route")):
            return "provider_policy_blocks_real_data"
        if ratelimit.peek(self.session, "llm_tokens_org_day", self.org_id, 86400) >= s.llm_max_tokens_per_org_per_day:
            return "live_cost_ceiling"
        try:
            ratelimit.hit(self.session, "llm_org_day", self.org_id, s.llm_live_per_org_per_day, 86400)
            ratelimit.hit(self.session, "llm_user_hour", self.user_id, s.llm_live_per_user_per_hour, 3600)
        except ApiError:
            return "live_quota_exceeded"
        return None

    def record_tokens(self, tokens: int) -> None:
        if tokens > 0:
            try:
                ratelimit.hit(self.session, "llm_tokens_org_day", self.org_id, 10**12, 86400, cost=int(tokens))
            except ApiError:  # pragma: no cover
                pass


live_gate_var: ContextVar[LiveGate | None] = ContextVar("live_gate", default=None)


@contextmanager
def use_gate(gate: LiveGate | None) -> Iterator[None]:
    token = live_gate_var.set(gate)
    try:
        yield
    finally:
        live_gate_var.reset(token)


def live_block_reason(provider, synthetic: bool = True) -> str | None:
    """Reason why a live call must not happen now (None = go ahead; quota is consumed)."""
    if getattr(provider, "config_error", None):
        return f"llm_misconfigured:{provider.config_error}"
    if not provider.available:
        return "model_not_configured"
    if getattr(provider, "is_recorded", False):
        return None  # replay of recorded outputs: no external call, no budget
    gate = live_gate_var.get()
    if gate is None:
        return "no_live_context"
    return gate.acquire(synthetic=synthetic, data_policy=getattr(provider, "data_policy", "api_default"))


def record_usage(tokens: int) -> None:
    gate = live_gate_var.get()
    if gate is not None:
        gate.record_tokens(tokens)


# --- circuit breaker (shared counters) -----------------------------------------------------------------


def _session():
    gate = live_gate_var.get()
    return gate.session if gate is not None else None


def circuit_open(provider_name: str) -> bool:
    s = get_settings()
    sess = _session()
    if sess is None:
        return False
    return ratelimit.peek(sess, "llm_fail", provider_name, s.llm_circuit_window_seconds) >= s.llm_circuit_failures


def record_failure(provider_name: str) -> None:
    s = get_settings()
    sess = _session()
    if sess is None:
        return
    try:
        ratelimit.hit(sess, "llm_fail", provider_name, 10**9, s.llm_circuit_window_seconds)
    except ApiError:  # pragma: no cover
        pass


def record_fallback(primary: str, used: str) -> None:
    gate = live_gate_var.get()
    if gate is None:
        return
    from ..services.common import audit

    audit(gate.session, gate.org_id, gate.user_id, "llm.fallback_provider", "llm", None, primary=primary, used=used)
    gate.session.commit()
