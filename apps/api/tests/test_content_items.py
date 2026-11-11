"""Every demo item must have exactly one correct option and only wrong distractors."""

from fractions import Fraction as F
from math import gcd

import pytest

from oqumap.demo.content import ITEMS, MISCONCEPTIONS, OBJECTIVES, TOPICS, FORMS, is_reduced, parse_value


def _ratio(text):
    a, b = (int(x) for x in text.replace(" ", "").split(":"))
    return a, b


def _pair(text):
    left, right = text.split(" и ")
    return left.strip(), right.strip()


def _explicit_correct(item, text) -> bool:
    code = item.code
    if code == "I05":
        return int(text) % 9 == 0
    if code == "I06":
        return int(text) % 2 == 0 and int(text) % 5 == 0
    if code == "I09":
        a, b = _pair(text)
        va, vb = parse_value(a), parse_value(b)
        da, db = int(a.split("/")[1]), int(b.split("/")[1])
        return va == F(3, 4) and vb == F(5, 6) and da == db == 12
    if code in {"I10", "I12", "I39"}:
        v = parse_value(text)
        return v is not None and v == item.expr
    if code == "I11":
        vals = [parse_value(p) for p in text.split(";")]
        return vals == sorted(vals) and sorted(vals) == sorted([F(1, 2), F(1, 3), F(1, 4)])
    if code == "I41":
        a, b = _ratio(text)
        return F(a, b) == F(12, 18) and gcd(a, b) == 1
    if code == "I44":
        a, b = _ratio(text)
        return F(a, b) == F(12, 28) and gcd(a, b) == 1
    raise AssertionError(f"no explicit rule for {code}")


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i.code)
def test_item_has_exactly_one_correct_option(item):
    correct = []
    for letter, (text, misconception) in zip(item.letters, item.options, strict=True):
        if item.mode == "explicit":
            ok = _explicit_correct(item, text)
        elif item.mode == "reduced":
            v = parse_value(text)
            ok = v == item.expr and is_reduced(text)
        else:
            ok = parse_value(text) == F(item.expr)
        if ok:
            correct.append(letter)
            assert misconception is None, f"{item.code}: correct option {letter} tagged {misconception}"
        else:
            assert misconception in MISCONCEPTIONS, f"{item.code}: distractor {letter} lacks a known tag"
    assert correct == [item.key], f"{item.code}: correct={correct} key={item.key}"


def test_item_objective_weights_sum_to_one_and_codes_exist():
    codes = {o[0] for o in OBJECTIVES}
    topic_of = {o[0]: o[1] for o in OBJECTIVES}
    for item in ITEMS:
        assert abs(sum(w for _, w in item.objectives) - 1) < 1e-9, item.code
        for code, _ in item.objectives:
            assert code in codes
        # every item's primary objective lies in the item's topic
        assert topic_of[item.objectives[0][0]] == item.topic


def test_content_volume_matches_brief():
    assert 6 <= len(TOPICS) <= 10
    assert 15 <= len(OBJECTIVES) <= 25
    assert len(ITEMS) >= 40
    assert len({i.code for i in ITEMS}) == len(ITEMS)
    for form in FORMS.values():
        assert len(set(form["items"])) == len(form["items"])
