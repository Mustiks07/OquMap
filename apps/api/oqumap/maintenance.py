"""Maintenance commands.

    python -m oqumap.maintenance cleanup        # expired demo tenants, API sessions, rate-limit counters
    python -m oqumap.maintenance check-config   # exit 1 when the live LLM configuration is unusable
    python -m oqumap.maintenance probe-llm      # ask the configured provider about the model
    python -m oqumap.maintenance record-live    # probe → eval → council → recorded demo (docs/LIVE_RECORDING.md)

The worker also runs ``cleanup`` every OQUMAP_CLEANUP_INTERVAL seconds (default 600).
"""

from __future__ import annotations

import argparse
import json
import sys

from .db import session_factory


def cleanup() -> dict:
    from .services.demo_tenants import cleanup_expired

    with session_factory()() as s:
        return cleanup_expired(s)


def check_config() -> int:
    from .ai.provider import llm_config_problem
    from .config import get_settings

    s = get_settings()
    problem = llm_config_problem()
    print(json.dumps({"deployment_mode": s.deployment_mode, "llm_provider": s.llm_provider, "llm_model": s.llm_model,
                      "llm_problem": problem}, ensure_ascii=False))
    return 1 if problem else 0


def probe_llm() -> int:
    """Preflight before a demo: config check + capability probe of the configured model (one HTTP call)."""
    from .ai.provider import get_provider, llm_config_problem

    problem = llm_config_problem()
    prov = get_provider()
    out = {"provider": prov.name, "model": prov.model, "config_problem": problem}
    if problem or not prov.available or not hasattr(prov, "probe"):
        print(json.dumps(out, ensure_ascii=False))
        return 1 if problem else 0
    try:
        out["capabilities"] = prov.probe().as_dict()
        needed = [c for c in ("structured_output", "tool_calling") if not out["capabilities"].get(c)]
        out["missing_capabilities"] = needed
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as exc:
        out["probe_error"] = getattr(exc, "reason", type(exc).__name__)
        print(json.dumps(out, ensure_ascii=False))
        return 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["cleanup", "check-config", "probe-llm", "record-live"])
    ap.add_argument("--topics", default="T3", help="record-live: comma-separated topic codes")
    ap.add_argument("--langs", default="ru,kz", help="record-live: comma-separated languages")
    ap.add_argument("--no-eval", action="store_true", help="record-live: skip the provider eval")
    a = ap.parse_args()
    if a.command == "record-live":
        from .ai.record_live import RecordingRefused, record

        with session_factory()() as session:
            try:
                man = record(session, topics=tuple(a.topics.split(",")), langs=tuple(a.langs.split(",")), run_eval=not a.no_eval)
            except RecordingRefused as exc:
                print(json.dumps({"recorded": False, "refused": str(exc)}, ensure_ascii=False))
                sys.exit(2)
        print(json.dumps({"recorded": True, "provider": man["provider"], "model": man["model"], "files": len(man["files"]),
                          "eval": man.get("eval")}, ensure_ascii=False))
    elif a.command == "cleanup":
        print(json.dumps(cleanup(), ensure_ascii=False))
    elif a.command == "probe-llm":
        sys.exit(probe_llm())
    else:
        sys.exit(check_config())


if __name__ == "__main__":
    main()
