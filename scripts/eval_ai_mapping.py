"""Measure the objective-linking quality on a small developer-labelled set.

Sets:
  * fragments: 25 text markers from the two demo materials (apps/api/oqumap/demo/materials.py: GOLD);
  * items: the 52 demo items with the item-bank author's objective links (content.py).
Both sets were labelled by the developer, not by an independent methodist: the numbers describe agreement with
that labelling on a tiny corpus and are not an external benchmark.

Usage: cd apps/api && uv run python ../../scripts/eval_ai_mapping.py [--live]
--live additionally evaluates the configured model provider (requires OQUMAP_LLM_PROVIDER=anthropic and a key).
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from oqumap.ai import mapper  # noqa: E402
from oqumap.demo import materials  # noqa: E402
from oqumap.demo.content import ITEMS, OBJECTIVES  # noqa: E402


def fragment_cases():
    texts = {"EDA": [p for _, ps in materials.PDF_PAGES for p in ps], "EDB": [t for _, t in materials.DOCX_BLOCKS]}
    cases = []
    for doc, marker, gold in materials.GOLD:
        text = next(t for t in texts[doc] if marker in t)
        cases.append({"id": f"{doc}:{marker[:30]}", "text": text, "gold": set(gold)})
    return cases


def item_cases():
    return [{"id": it.code, "text": it.stem_ru + " " + " ".join(o for o, _ in it.options),
             "gold": {c for c, _ in it.objectives}} for it in ITEMS]


def score(cases, predict):
    tp = fp = fn = top1 = exact = empty = 0
    errors = []
    for c in cases:
        pred = predict(c["text"])
        ps = set(pred)
        tp += len(ps & c["gold"])
        fp += len(ps - c["gold"])
        fn += len(c["gold"] - ps)
        top1 += bool(pred) and pred[0] in c["gold"]
        exact += ps == c["gold"]
        empty += not pred
        if ps != c["gold"]:
            errors.append({"id": c["id"], "gold": sorted(c["gold"]), "predicted": pred})
    n = len(cases)
    return {"n": n, "precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3),
            "top1_accuracy": round(top1 / n, 3), "exact_match": round(exact / n, 3), "no_proposal_rate": round(empty / n, 3),
            "errors": errors}


def template_predict(text):
    return [p["objective_code"] for p in mapper.propose(text)]


def live_predict_factory():
    from oqumap.ai.provider import get_provider
    from oqumap.ai.tasks import LINK_SCHEMA, SYSTEM_BASE

    p = get_provider()
    if not p.available:
        raise SystemExit("live provider not configured")
    objs = [{"code": c, "text": t} for c, _, t, _ in OBJECTIVES]

    def predict(text):
        data, _ = p.complete_json(SYSTEM_BASE + " Укажи 0–2 кода целей для фрагмента.",
                                  json.dumps({"fragments": [{"ref": "x", "text": text}], "objectives": objs}, ensure_ascii=False),
                                  LINK_SCHEMA)
        return [c for c in data["links"][0]["objective_codes"]][:2] if data["links"] else []

    return predict


def main():
    results = {"date": date.today().isoformat(), "labelled_by": "developer (not an independent methodist)",
               "template": {"fragments": score(fragment_cases(), template_predict), "items": score(item_cases(), template_predict)},
               "live_model": None}
    if "--live" in sys.argv:
        pred = live_predict_factory()
        results["live_model"] = {"fragments": score(fragment_cases(), pred), "items": score(item_cases(), pred)}
    out = ROOT / "data" / "ai_eval" / "results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for mode in ("template", "live_model"):
        if results[mode]:
            for k, v in results[mode].items():
                print(mode, k, {kk: vv for kk, vv in v.items() if kk != "errors"})
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
