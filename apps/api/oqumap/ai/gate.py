"""Who may spend the model budget. Live calls require: a configured provider, a non-demo tenant, an allowed role
and remaining quota (per organisation per day, per user per hour, stored in the shared rate-limit table)."""

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

    def acquire(self) -> str | None:
        """Consume one live call. Returns None when allowed, otherwise the fallback reason code."""
        s = get_settings()
        if self.org_is_ephemeral or (s.deployment_mode == "public_demo" and self.org_is_demo):
            return "live_disabled_for_public_demo"
        if not set(self.roles) & set(s.llm_live_roles):
            return "live_not_allowed_for_role"
        try:
            ratelimit.hit(self.session, "llm_org_day", self.org_id, s.llm_live_per_org_per_day, 86400)
            ratelimit.hit(self.session, "llm_user_hour", self.user_id, s.llm_live_per_user_per_hour, 3600)
        except ApiError:
            return "live_quota_exceeded"
        return None


live_gate_var: ContextVar[LiveGate | None] = ContextVar("live_gate", default=None)


@contextmanager
def use_gate(gate: LiveGate | None) -> Iterator[None]:
    token = live_gate_var.set(gate)
    try:
        yield
    finally:
        live_gate_var.reset(token)


def live_block_reason(provider) -> str | None:
    """Reason why a live call must not happen now (None = go ahead and consume quota)."""
    if getattr(provider, "config_error", None):
        return f"llm_misconfigured:{provider.config_error}"
    if not provider.available:
        return "model_not_configured"
    gate = live_gate_var.get()
    if gate is None:
        return "no_live_context"
    return gate.acquire()
