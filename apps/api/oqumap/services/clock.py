"""Single source of "today" for the measurement modules (patchable in tests: ``monkeypatch.setattr(clock, "today", …)``).

Every date-dependent calculation (fidelity, follow-up, portfolio, calendar) reads the date through ``clock.today()``
so that one request uses one consistent date and tests do not depend on the real calendar."""

from __future__ import annotations

from datetime import date


def today() -> date:
    return date.today()
