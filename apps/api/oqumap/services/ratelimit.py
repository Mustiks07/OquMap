"""Database-backed fixed-window rate limiting and quotas.

Counters live in the ``rate_limits`` table, so limits hold across several API processes and the worker.
Each hit is an atomic INSERT … ON CONFLICT DO UPDATE in its own short transaction (independent of the request
transaction). Expired rows are removed by ``oqumap.maintenance``.
"""

from __future__ import annotations

import ipaddress
import math
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings, parse_rate
from ..db import utcnow
from ..errors import ApiError

client_ip_var: ContextVar[str] = ContextVar("client_ip", default="unknown")


def resolve_client_ip(peer: str | None, forwarded_for: str | None) -> str:
    """Use X-Forwarded-For only when the direct peer is a trusted reverse proxy."""
    peer = peer or "unknown"
    if not forwarded_for:
        return peer
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    nets = []
    for c in get_settings().trusted_proxies:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    if not any(peer_ip in n for n in nets):
        return peer
    # right-most address that is not itself a trusted proxy
    for candidate in reversed([x.strip() for x in forwarded_for.split(",") if x.strip()]):
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not any(ip in n for n in nets):
            return str(ip)
    return peer


def _engine(session: Session) -> Engine:
    return session.get_bind()


def hit(session: Session, bucket: str, subject: str, limit: int, window_seconds: int, cost: int = 1) -> int:
    """Count one event; raise 429 when the window's limit is exceeded. Returns the new count."""
    now = utcnow()
    window = math.floor(now.timestamp() / window_seconds)
    key = f"{bucket}:{subject}:{window}"[:250]
    expires = datetime.fromtimestamp((window + 1) * window_seconds, UTC) + timedelta(seconds=60)
    eng = _engine(session)
    if eng.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(m.RateLimitCounter).values(key=key, count=cost, expires_at=expires)
    stmt = stmt.on_conflict_do_update(index_elements=["key"],
                                      set_={"count": m.RateLimitCounter.count + cost}).returning(m.RateLimitCounter.count)
    with eng.begin() as conn:
        count = conn.execute(stmt).scalar_one()
    if count > limit:
        retry = int((window + 1) * window_seconds - now.timestamp()) + 1
        raise ApiError("rate_limited", "Слишком много запросов. Повторите позже.", 429,
                       {"bucket": bucket, "limit": limit, "window_seconds": window_seconds, "retry_after": retry})
    return count


def check(session: Session, bucket: str, subject: str, spec_attr: str) -> None:
    limit, seconds = parse_rate(getattr(get_settings(), spec_attr))
    hit(session, bucket, subject, limit, seconds)


def peek(session: Session, bucket: str, subject: str, window_seconds: int) -> int:
    now = utcnow()
    key = f"{bucket}:{subject}:{math.floor(now.timestamp() / window_seconds)}"[:250]
    row = session.get(m.RateLimitCounter, key)
    return row.count if row else 0


def purge_expired(session: Session) -> int:
    res = session.execute(delete(m.RateLimitCounter).where(m.RateLimitCounter.expires_at < utcnow()))
    session.commit()
    return res.rowcount or 0
