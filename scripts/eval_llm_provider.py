"""Provider eval: the same fixed task set for any configured provider/model, so the live model for the contest is
chosen by measured behaviour, not by brand.

Checks per task: JSON-schema validity (server-side), correct tool selection, evidence IDs only from the allowed
set, no numbers outside the supplied metrics, Kazakh output when asked, latency and tokens.

Usage (from apps/api, with the provider configured through env, e.g. OQUMAP_LLM_PROVIDER=gemini
OQUMAP_LLM_MODEL=gemini-2.5-flash OQUMAP_GEMINI_API_KEY=...):
    uv run python ../../scripts/eval_llm_provider.py [--provider gemini --model gemini-2.5-flash]
Results: data/ai_eval/provider_eval_<provider>_<model>.json. Uses only synthetic inputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from oqumap.ai import verify  # noqa: E402
from oqumap.ai.llm.base import LLMError, ToolSpec  # noqa: E402

METRICS = {"raw": {"a": 0.498, "b": 0.445, "difference": -0.053}, "adjusted": {"a": 0.445, "b": 0.496, "difference": 0.052},
           "ci": {"low": 0.011, "high": 0.088}, "status": "comparable", "inference_level": "adjusted_association"}
TEXT_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}, "limitations": {"type": "array", "items": {"type": "string"}}},
               "required": ["text", "limitations"], "additionalProperties": False}
CITE_SCHEMA = {"type": "object", "properties": {"action": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}},
               "required": ["action", "evidence_ids"], "additionalProperties": False}
EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
TOPIC = {"type": "object", "properties": {"topic_code": {"type": "string"}}, "required": ["topic_code"], "additionalProperties": False}
QUERY = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}
TOOLS = [ToolSpec("compare_editions", "Сравнение изданий по теме", TOPIC), ToolSpec("search_sources", "Поиск по материалам", QUERY),
         ToolSpec("get_data_quality", "Качество данных набора", EMPTY), ToolSpec("get_overview", "Сводка по темам", EMPTY)]
TOOL_TASKS = [("Сравни пособия A и B по теме T3", "compare_editions"),
              ("Найди в материалах правило сложения дробей с разными знаменателями", "search_sources"),
              ("Достаточно ли в наборе данных для выводов? Сколько пропусков?", "get_data_quality")]
SYSTEM = "Ты помощник методиста. Используй только переданные данные; не придумывай числа. Ответ строго по схеме."
KZ = re.compile(r"[әғқңөұүһі]", re.IGNORECASE)


def run(adapter) -> dict:
    results = []

    def timed(fn):
        t0 = time.monotonic()
        try:
            out = fn()
            return out, None, int((time.monotonic() - t0) * 1000)
        except LLMError as exc:
            return None, exc.reason, int((time.monotonic() - t0) * 1000)

    r, err, ms = timed(lambda: adapter.structured(SYSTEM, json.dumps({"metrics": METRICS, "lang": "ru"}, ensure_ascii=False), TEXT_SCHEMA, "explain"))
    num = verify.check_numbers(r.data["text"] + " " + " ".join(r.data["limitations"]), METRICS) if r else None
    results.append({"task": "structured_explain_ru", "ok": bool(r) and num["status"] == "passed", "error": err, "latency_ms": ms,
                    "tokens": r.usage.total if r else 0, "numbers": num})
    r, err, ms = timed(lambda: adapter.structured(SYSTEM + " Ответ на казахском языке.", json.dumps({"metrics": METRICS, "lang": "kz"}, ensure_ascii=False), TEXT_SCHEMA, "explain_kz"))
    results.append({"task": "structured_explain_kz", "ok": bool(r) and bool(KZ.search(r.data["text"])), "error": err, "latency_ms": ms,
                    "tokens": r.usage.total if r else 0})
    allowed = ["src-1", "src-2", "src-3"]
    r, err, ms = timed(lambda: adapter.structured(SYSTEM + " В evidence_ids укажи только идентификаторы из списка sources.",
                                                  json.dumps({"sources": [{"id": i, "text": f"фрагмент {i}"} for i in allowed]}, ensure_ascii=False), CITE_SCHEMA, "cite"))
    results.append({"task": "evidence_ids_subset", "ok": bool(r) and bool(r.data["evidence_ids"]) and set(r.data["evidence_ids"]) <= set(allowed),
                    "error": err, "latency_ms": ms, "tokens": r.usage.total if r else 0})
    for q, expected in TOOL_TASKS:
        called = []

        def exe(name, args, called=called):
            called.append(name)
            return {"ok": True, "note": "synthetic eval stub"}

        out, err, ms = timed(lambda q=q, exe=exe: adapter.tool_loop(SYSTEM, q, TOOLS, exe, 3))
        results.append({"task": f"tool:{expected}", "ok": bool(called) and called[0] == expected, "called": called, "error": err,
                        "latency_ms": ms, "tokens": out[2].usage.total if out else 0})
    lat = [r["latency_ms"] for r in results]
    return {"tasks": results, "passed": sum(r["ok"] for r in results), "total": len(results),
            "median_latency_ms": sorted(lat)[len(lat) // 2], "tokens": sum(r["tokens"] for r in results)}


def main() -> int:
    from oqumap.ai.provider import build_adapter, llm_config_problem
    from oqumap.config import get_settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--provider")
    ap.add_argument("--model")
    a = ap.parse_args()
    s = get_settings()
    if a.provider:
        s.llm_provider = a.provider
    if a.model:
        s.llm_model = a.model
    problem = llm_config_problem()
    if problem or s.llm_provider in ("none", "recorded"):
        print(json.dumps({"provider": s.llm_provider, "model": s.llm_model, "not_run": problem or "no_live_provider"}))
        return 1
    adapter = build_adapter(s.llm_provider, s.llm_model)
    try:
        caps = adapter.probe().as_dict()
    except LLMError as exc:
        caps = {"probe_error": exc.reason}
    res = {"provider": s.llm_provider, "model": s.llm_model, "data_policy": adapter.data_policy, "capabilities": caps,
           "date_note": "run manually; synthetic inputs only", **run(adapter)}
    out = ROOT / "data" / "ai_eval" / f"provider_eval_{s.llm_provider}_{re.sub(r'[^a-z0-9.-]+', '-', s.llm_model.lower())}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("provider", "model", "passed", "total", "median_latency_ms", "tokens")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
