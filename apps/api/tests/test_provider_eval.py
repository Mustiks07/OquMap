"""The provider eval harness itself works (with a scripted adapter); real providers are evaluated manually."""

import importlib.util
import json
from pathlib import Path

from oqumap.ai.llm.base import LLMProvider, LLMResult, Usage

spec = importlib.util.spec_from_file_location("eval_llm", Path(__file__).resolve().parents[3] / "scripts" / "eval_llm_provider.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class Scripted(LLMProvider):
    name = "scripted"

    def structured(self, system, user, schema, name="result"):
        if name == "cite":
            data = {"action": "a", "evidence_ids": ["src-1", "made-up"]}  # one invented id → must fail
        elif name == "explain_kz":
            data = {"text": "Түзетілген айырма оң.", "limitations": []}
        else:
            data = {"text": "Разница после поправки +5,2 п.п., а не 37%.", "limitations": []}
        return LLMResult(self.name, "m", 5, Usage(10, 5), json.dumps(data), self._validated(data, schema))

    def tool_loop(self, system, user, tools, execute, max_steps=4):
        name = "compare_editions" if "Сравни" in user else "get_overview"
        execute(name, {"topic_code": "T3"} if name == "compare_editions" else {})
        return "ok", [], LLMResult(self.name, "m", 5, Usage(1, 1), "ok")


def test_eval_scores_schema_numbers_ids_kz_and_tools():
    res = ev.run(Scripted("m"))
    by = {t["task"]: t for t in res["tasks"]}
    assert by["structured_explain_ru"]["ok"] is False  # invented "37%" is caught
    assert by["structured_explain_kz"]["ok"] is True
    assert by["evidence_ids_subset"]["ok"] is False
    assert by["tool:compare_editions"]["ok"] is True and by["tool:search_sources"]["ok"] is False
    assert res["total"] == 6
