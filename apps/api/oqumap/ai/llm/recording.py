"""Recording and replay of real live-model outputs for the offline demo.

* ``RecordingProvider`` wraps a live adapter. Every structured call is forwarded unchanged; the answer is written
  to a staging directory only after ``scrub`` has checked it: no API key value, no credential-looking strings
  (Bearer tokens, ``sk-…``, ``AIza…``), no e-mail addresses. Inputs are synthetic demo data only (the recording
  command refuses anything else).
* Database IDs (UUIDs) are replaced by placeholders ``<ID1>…`` in order of first appearance in the input, both in
  the stored input and in the stored output. The replay key is computed from the normalised input, so a recording
  made in the demo template replays in any disposable demo tenant (whose IDs differ), and IDs in the output are
  mapped back to the current request's IDs. Unknown IDs still fail the server-side checks.
* Nothing here creates a recording without a real model call: there is no way to write a record except by
  passing an actual adapter response through ``RecordingProvider``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .base import LLMError, LLMProvider, LLMResult

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
PLACEHOLDER_RE = re.compile(r"<ID(\d+)>")
CREDENTIAL_RE = re.compile(r"(Bearer\s+[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|x-api-key|x-goog-api-key)",
                           re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RECORD_VERSION = 1


def normalize(text: str) -> tuple[str, list[str]]:
    ids: list[str] = []

    def sub(m: re.Match) -> str:
        if m.group(0) not in ids:
            ids.append(m.group(0))
        return f"<ID{ids.index(m.group(0)) + 1}>"

    return UUID_RE.sub(sub, text), ids


def _apply_ids(obj, ids: list[str], forward: bool):
    if isinstance(obj, str):
        if forward:
            return UUID_RE.sub(lambda m: f"<ID{ids.index(m.group(0)) + 1}>" if m.group(0) in ids else "<ID?>", obj)
        return PLACEHOLDER_RE.sub(lambda m: ids[int(m.group(1)) - 1] if int(m.group(1)) <= len(ids) else m.group(0), obj)
    if isinstance(obj, dict):
        return {k: _apply_ids(v, ids, forward) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_apply_ids(v, ids, forward) for v in obj]
    return obj


def record_key(name: str, normalized_user: str) -> str:
    return hashlib.sha256((name + "\n" + normalized_user).encode()).hexdigest()[:24]


def scrub(obj, secrets: list[str]) -> None:
    """Raise if anything that looks like a secret or personal contact data would be written."""
    text = json.dumps(obj, ensure_ascii=False)
    for s in secrets:
        if s and len(s) >= 6 and s in text:
            raise LLMError("policy", "secret_in_recording")
    if CREDENTIAL_RE.search(text):
        raise LLMError("policy", "credential_pattern_in_recording")
    if EMAIL_RE.search(text):
        raise LLMError("policy", "email_in_recording")


class RecordingProvider(LLMProvider):
    """Forwards to a live adapter and stores scrubbed, ID-normalised outputs in ``out_dir``."""

    def __init__(self, inner: LLMProvider, out_dir: Path, secrets: list[str]):
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.data_policy = inner.data_policy
        self.capabilities = inner.capabilities
        self.out_dir = out_dir
        self._secrets = secrets
        self.records: list[dict] = []

    def probe(self):
        return self.inner.probe()

    def structured(self, system: str, user: str, schema: dict, name: str = "result") -> LLMResult:
        r = self.inner.structured(system, user, schema, name)
        norm_user, ids = normalize(user)
        rec = {"record_version": RECORD_VERSION, "task": name, "key": record_key(name, norm_user),
               "recorded_provider": r.provider, "recorded_model": r.model, "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
               "latency_ms": r.latency_ms, "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens},
               "structured_mode": r.structured_mode, "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
               "input": json.loads(norm_user) if norm_user.lstrip().startswith("{") else norm_user,
               "output": _apply_ids(r.data, ids, forward=True)}
        scrub(rec, self._secrets)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{name}-{rec['key']}.json"
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.records.append({"file": path.name, "task": name, "model": r.model})
        return r

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        return self.inner.tool_loop(system, user, tools, execute, max_steps)


def replay(directory: Path, name: str, user: str) -> tuple[dict, str] | None:
    """Recorded output for this request with IDs mapped back to the current request, or None."""
    norm_user, ids = normalize(user)
    p = directory / f"{name}-{record_key(name, norm_user)}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return _apply_ids(data["output"], ids, forward=False), data.get("recorded_model", "recorded")
