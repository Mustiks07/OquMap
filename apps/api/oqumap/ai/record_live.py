"""Operator command: record a real live-model run for the offline demo (never needed for normal operation).

    probe → provider eval → council on the synthetic demo topic(s) → scrubbed, ID-normalised recording → manifest

Refuses unless: a live provider is configured without diagnostics problems; the data is the synthetic demo
dataset of the demo template organisation; every council step that should use the model actually ran in
``live_model`` mode. Files go to a staging directory first and are moved into ``data/demo/recorded/llm/`` only
after all checks pass; on any failure the staging directory is deleted. The API key is only read from settings,
never written; recordings are scanned for the key value, credential patterns and e-mail addresses.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import REPO_ROOT, get_settings
from ..demo.seed import DEMO_ORG_ID
from ..services.auth import Principal
from . import provider as prov
from .gate import LiveGate, use_gate
from .llm.recording import RecordingProvider

RECORD_DIR = REPO_ROOT / "data" / "demo" / "recorded" / "llm"


class RecordingRefused(Exception):
    pass


def _secrets() -> list[str]:
    s = get_settings()
    out = []
    for name in ("gemini", "openrouter", "openai", "anthropic"):
        v = getattr(s, f"{name}_api_key", None)
        if v is not None and v.get_secret_value().strip():
            out.append(v.get_secret_value().strip())
    return out


def record(session: Session, adapter=None, out_dir: Path = RECORD_DIR, topics: tuple[str, ...] = ("T3",),
           langs: tuple[str, ...] = ("ru", "kz"), run_eval: bool = True) -> dict:
    """``adapter`` defaults to the configured live adapter (tests pass a scripted adapter and a temp dir)."""
    s = get_settings()
    if adapter is None:
        if s.llm_provider in ("none", "recorded"):
            raise RecordingRefused("live provider not configured (OQUMAP_LLM_PROVIDER must be a live provider)")
        problem = prov.llm_config_problem()
        if problem:
            raise RecordingRefused(f"llm configuration problem: {problem}")
        adapter = prov.build_adapter(s.llm_provider, s.llm_model)
    org = session.get(m.Organization, DEMO_ORG_ID)
    ds = session.scalar(select(m.Dataset).where(m.Dataset.org_id == DEMO_ORG_ID, m.Dataset.code == "base"))
    if org is None or ds is None or not ds.is_synthetic or not org.is_demo:
        raise RecordingRefused("synthetic demo dataset not found (seed the demo first)")
    user = session.scalar(select(m.User).where(m.User.org_id == org.id, m.User.username == "demo.methodist"))
    if user is None:
        raise RecordingRefused("demo methodist user not found")
    p = Principal(user=user, org=org)
    staging = out_dir.parent / f".staging-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    rec = RecordingProvider(adapter, staging, _secrets())
    summary: dict = {"provider": adapter.name, "model": adapter.model, "data_policy": adapter.data_policy}
    try:
        try:
            summary["capabilities"] = adapter.probe().as_dict()
        except Exception as exc:  # classified; never contains the key
            summary["capabilities"] = {"probe_error": getattr(exc, "reason", type(exc).__name__)}
        if run_eval:
            import importlib.util

            spec = importlib.util.spec_from_file_location("eval_llm", REPO_ROOT / "scripts" / "eval_llm_provider.py")
            ev = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ev)
            e = ev.run(adapter)
            summary["eval"] = {k: e[k] for k in ("passed", "total", "median_latency_ms", "tokens")}
        from . import council

        # The operator gate: synthetic demo data only; the public-demo block is for anonymous visitors, not this tool.
        gate = LiveGate(session, org.id, user.id, list(user.roles or []), org_is_ephemeral=False, org_is_demo=False)
        runs = []
        with prov.use_provider(prov.ChainProvider([rec])), use_gate(gate):
            meta_topics = {t.code: t.id for t in session.scalars(select(m.Topic).where(m.Topic.program_version_id == ds.program_version_id))}
            for code in topics:
                for lang in langs:
                    out = council.run(session, p, ds.id, meta_topics[code], lang=lang)
                    modes = out["output"]["role_modes"]
                    if modes["analyst"]["mode"] != "live_model" or modes["curriculum"]["mode"] != "live_model":
                        raise RecordingRefused(f"council roles did not run live for {code}/{lang}: "
                                               f"{modes['analyst'].get('fallback_reason') or modes['curriculum'].get('fallback_reason')}")
                    runs.append({"topic": code, "lang": lang, "generation_id": out["generation_id"],
                                 "verification": out["verification"], "highlight": (out["output"]["highlight"] or {}).get("verdict")})
        if not rec.records:
            raise RecordingRefused("no model calls were recorded")
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for r in rec.records:
            src = staging / r["file"]
            data = src.read_bytes()
            (out_dir / r["file"]).write_bytes(data)
            files.append({"file": r["file"], "task": r["task"], "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"recorded_at": datetime.now(UTC).isoformat(timespec="seconds"), **summary, "dataset": {"code": ds.code,
                    "version": ds.version, "is_synthetic": ds.is_synthetic}, "runs": runs, "files": files,
                    "note": "Real live-model outputs on synthetic demo data; replayed as recorded_demo (never shown as live_model)."}
        (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
