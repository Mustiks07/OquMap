"""Background worker: ``python -m oqumap.worker`` claims queued jobs from the database."""

from __future__ import annotations

import logging
import signal
import time

from .api import routes  # noqa: F401  (registers job handlers)
from .db import session_factory
from .services import documents  # noqa: F401
from .services.jobs import claim_next, execute

log = logging.getLogger("oqumap.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def main(poll_seconds: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started")
    while _running:
        with session_factory()() as session:
            job = claim_next(session)
            if job is None:
                time.sleep(poll_seconds)
                continue
            log.info("running job %s kind=%s", job.id, job.kind)
            execute(session, job)


if __name__ == "__main__":
    main()
