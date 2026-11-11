"""Background worker: ``python -m oqumap.worker`` claims queued jobs from the database.

Resilient start: while the database or the schema is not available yet (e.g. the API container is still
running migrations) the worker retries with bounded exponential backoff instead of exiting. It also runs the
periodic cleanup of expired demo tenants, sessions and rate-limit counters.
"""

from __future__ import annotations

import logging
import os
import signal
import time

from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from .api import routes  # noqa: F401  (registers job handlers)
from .db import session_factory
from .services import documents  # noqa: F401
from .services.jobs import claim_next, execute

log = logging.getLogger("oqumap.worker")
_running = True
MAX_BACKOFF = 30.0


def _stop(*_):
    global _running
    _running = False


def main(poll_seconds: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    cleanup_every = float(os.environ.get("OQUMAP_CLEANUP_INTERVAL", "600"))
    last_cleanup = -cleanup_every  # run once at start
    backoff = 1.0
    log.info("worker started")
    while _running:
        try:
            if time.monotonic() - last_cleanup > cleanup_every:
                from .maintenance import cleanup

                log.info("cleanup %s", cleanup())
                last_cleanup = time.monotonic()
            with session_factory()() as session:
                job = claim_next(session)
                backoff = 1.0
                if job is None:
                    time.sleep(poll_seconds)
                    continue
                log.info("running job %s kind=%s", job.id, job.kind)
                execute(session, job)
        except (OperationalError, ProgrammingError, DBAPIError) as exc:
            # database not reachable or schema not migrated yet: wait and retry, never exit
            log.warning("database not ready (%s); retrying in %.0fs", type(exc).__name__, backoff)
            time.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)


if __name__ == "__main__":
    main()
