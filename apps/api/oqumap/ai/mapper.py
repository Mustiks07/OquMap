"""Rule-based (``template`` mode) mapper from text to learning objectives.

A transparent keyword lexicon per demonstration objective. It is used when no model is configured and as a
baseline in the evaluation (docs/AI_EVAL.md). Proposals are always ``proposed`` and require review.
"""

from __future__ import annotations

LEXICON: dict[str, list[str]] = {
    "DEMO-M6-1.1": ["нод", "наибольш", "общий делитель", "делител"],
    "DEMO-M6-1.2": ["нок", "наименьшее общее кратное", "кратн"],
    "DEMO-M6-1.3": ["делится", "признак", "делимост"],
    "DEMO-M6-2.1": ["сократ", "несократим", "равна", "равную", "основное свойство дроби"],
    "DEMO-M6-2.2": ["общему знаменателю", "общий знаменатель", "общего знаменателя", "дополнительн", "одинаковые доли"],
    "DEMO-M6-2.3": ["больше", "меньше", "сравн", "возрастан", " < ", " > "],
    "DEMO-M6-3.1": ["слож", "вычит", " + ", " − ", "сумм", "разными знаменателями"],
    "DEMO-M6-3.2": ["смешанн", "занима", "числовой прям", "целой части"],
    "DEMO-M6-3.3": ["задач", "прошли", "отрезали", "купили", "пути", "массa", "масса покупки"],
    "DEMO-M6-4.1": ["умнож", "произведен", " · ", "площад"],
    "DEMO-M6-4.2": ["раздел", "делени", " : ", "обратн", "помещается"],
    "DEMO-M6-4.3": ["дробь от числа", "от числа", "найти 3/5 от", "найдите 2/3", "найдите 3/5"],
    "DEMO-M6-5.1": ["десятичн", "0,75", "0,6", "сотых", "0,3"],
    "DEMO-M6-5.2": ["0,5 + 0,25", "1,2 · 0,3", "2,4 : 0,6", "действия с десятичн"],
    "DEMO-M6-6.1": ["отношени", "упростите"],
    "DEMO-M6-6.2": ["пропорци", "тетрад", "скорост", "проедет", "прямо пропорциональн"],
    "DEMO-M6-7.1": ["%", "процент"],
    "DEMO-M6-7.2": ["сколько процентов", "процентов составляет", "% которого", "какой процент"],
    "DEMO-M6-8.1": ["координатн"],
    "DEMO-M6-8.2": ["отрицательн", "рациональн"],
}

TEMPLATE_VERSION = "lexicon-v1"


def propose(text: str, allowed_codes: list[str] | None = None, max_links: int = 2) -> list[dict]:
    t = f" {text.lower()} "
    scores = []
    for code, words in LEXICON.items():
        if allowed_codes is not None and code not in allowed_codes:
            continue
        hits = [w.strip() for w in words if w in t]
        if hits:
            scores.append((len(hits), code, hits))
    if not scores:
        return []
    scores.sort(key=lambda x: (-x[0], x[1]))
    best = scores[0][0]
    out = []
    for n, code, hits in scores[:max_links]:
        if n == best or (n >= 2 and n >= best - 1):
            out.append({"objective_code": code, "matched": hits, "score": n,
                        "rationale_ru": "Совпали признаки: " + ", ".join(hits)})
    return out
