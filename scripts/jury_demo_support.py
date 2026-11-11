"""Validation and fixture-only pilot evaluation. No production analytics overrides."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date
from fractions import Fraction

import pandas as pd
from generate_jury_demo import MC, OUT, SEED, truth
from oqumap.analytics import scoring
from oqumap.analytics.comparison import compare_arms
from oqumap.analytics.paired import paired_change
from pypdf import PdfReader


def rows(root, name):
    return list(csv.DictReader(io.StringIO((root / name).read_text(encoding="utf-8"))))


def unique(data, *keys):
    values = [tuple(r[k] for k in keys) for r in data]
    assert len(values) == len(set(values)), keys


def in_range(value, interval):
    assert value is not None and interval[0] <= value <= interval[1], (value, interval)


def validate_files(root=OUT):
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["is_synthetic"] is True and manifest["seed"] == SEED
    for name, entry in manifest["files"].items():
        data = (root / name).read_bytes()
        assert (
            len(data) == entry["bytes"]
            and hashlib.sha256(data).hexdigest() == entry["sha256"]
        ), name
    program = rows(root, "1_program.csv")
    bank = rows(root, "3_item_bank.csv")
    roster = rows(root, "4_roster.csv")
    responses = rows(root, "5_responses.csv")
    specs = json.loads((root / "item_math.json").read_text())
    spec = {s["code"]: s for s in specs}
    unique(program, "objective_code")
    unique(bank, "form_code", "item_code")
    unique(roster, "learner_code")
    unique(responses, "assessment_code", "learner_code", "item_code", "attempt")
    assert len(program) == 18 and len(spec) == 42 and len(roster) == 384
    assert (
        len({r["school_code"] for r in roster}) == 8
        and len({r["class_code"] for r in roster}) == 16
    )
    assert set(Counter(r["class_code"] for r in roster).values()) == {24}
    assert {r["language"] for r in roster} == {"ru", "kz"}
    assert all(re.fullmatch("JDL[0-9]{4}", r["learner_code"]) for r in roster)
    assert all(
        re.fullmatch("Синтетическая школа [0-9]{2}", r["school_name"]) for r in roster
    )
    assert all(re.fullmatch("JDT[0-9]{2}", r["teacher_code"]) for r in roster)
    # Structural allowlist excludes personal names, addresses, contact fields and free-form learner data.
    assert set(roster[0]) == {
        "school_code",
        "school_name",
        "class_code",
        "teacher_code",
        "grade",
        "language",
        "academic_year",
        "learner_code",
        "edition_code",
        "period_start",
        "period_end",
    }
    for name in manifest["files"]:
        if name.endswith((".csv", ".json")):
            text = (root / name).read_text()
            assert not re.search(
                r"\b[^\s@]+@[^\s@]+\.[a-z]{2,}\b|\+7[\s(\d]|\b(?:NaN|Infinity)\b", text
            ), name
    objectives = {r["objective_code"] for r in program}
    for r in program:
        assert all(
            r[k]
            for k in (
                "topic_title_ru",
                "topic_title_kz",
                "objective_text_ru",
                "objective_text_kz",
            )
        )
        assert all(k in objectives for k in r["prerequisite_codes"].split(";") if k)
        assert int(r["hours_min"]) <= int(r["hours_current"]) <= int(r["hours_max"])
        assert int(r["hours_elapsed"]) <= int(r["hours_current"])
    editions = {r["edition_code"] for r in rows(root, "2_editions.csv")}
    classes = {}
    for r in roster:
        assert r["edition_code"] in editions
        sig = tuple(
            r[k] for k in ("school_code", "language", "teacher_code", "edition_code")
        )
        assert classes.setdefault(r["class_code"], sig) == sig
    for r in bank:
        assert r["stem_ru"] and r["stem_kz"]
        links = [p.split(":") for p in r["objective_codes"].split(";")]
        assert all(p[0] in objectives for p in links)
        assert abs(sum(float(p[1]) if len(p) > 1 else 1 for p in links) - 1) < 1e-9
        assert r["mapping_status"] in ("proposed", "confirmed")
    by_form = defaultdict(set)
    for r in bank:
        by_form[r["form_code"]].add(r["item_code"])
    assert len({tuple(sorted(v)) for v in by_form.values()}) == 1, (
        "identical_form requires identical items"
    )
    for s in specs:
        assert Fraction(s["answer"]) == truth(s)
        options = s["options"]
        values = [Fraction(o["text"]) for o in options]
        assert len(set(values)) == 4
        assert [o["key"] for o in options if Fraction(o["text"]) == truth(s)] == [
            s["answer_key"]
        ]
        assert all(o["tag"] in MC for o in options if o["key"] != s["answer_key"])
        for o in options:
            if o["tag"] == "M2":
                a, b = map(Fraction, s["params"])
                sign = 1 if s["op"] == "add" else -1
                assert Fraction(o["text"]) == Fraction(
                    a.numerator + sign * b.numerator,
                    math.lcm(a.denominator, b.denominator),
                )
            if o["tag"] == "M1":
                a, b = map(Fraction, s["params"])
                assert Fraction(o["text"]) == Fraction(
                    a.numerator + b.numerator, a.denominator + b.denominator
                )
    learners = {r["learner_code"] for r in roster}
    sittings = defaultdict(list)
    for r in responses:
        assert r["learner_code"] in learners and r["form_code"] in by_form
        assert r["assessment_code"] == r["form_code"] + "-2026"
        sittings[r["learner_code"], r["assessment_code"]].append(r)
        if r["status"] == "absent":
            assert not r["item_code"] and not r["score"] and not r["response"]
            continue
        assert r["item_code"] in by_form[r["form_code"]]
        if r["status"] == "omitted":
            assert not r["score"] and not r["response"]
        else:
            assert r["status"] == "answered"
            score = float(r["score"])
            s = spec[r["item_code"]]
            assert math.isfinite(score) and 0 <= score <= (
                2 if s["quality"] == "partial_credit" else 1
            )
            if s["quality"] != "partial_credit":
                assert r["response"] in "ABCD"
                assert score == int(r["response"] == s["answer_key"])
            else:
                assert score in (0, 1, 2)
                assert (r["response"] == s["answer"]) == (score == 2)
    assert len(sittings) == 384 * 3
    for sitting in sittings.values():
        assert len(sitting) == (1 if sitting[0]["status"] == "absent" else 42)
    for form in by_form:
        absent = sum(
            1
            for v in sittings.values()
            if v[0]["form_code"] == form and v[0]["status"] == "absent"
        )
        in_range(absent / 384, [0.04, 0.07])
    # Physical and printed numbering are equal, with a real page 47 and complete text layers.
    for ed in "AB":
        reader = PdfReader(root / f"materials/textbook_{ed}.pdf")
        assert len(reader.pages) == 50
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            assert "SYNTHETIC" in text and str(i) in text
        assert "6.2.1" in reader.pages[46].extract_text()
    exercises = json.loads((root / "materials/exercises.json").read_text())
    unique(exercises, "edition_code", "page", "number")
    for ex in exercises:
        assert (
            ex["edition_code"] in editions
            and 1 <= ex["page"] <= 50
            and ex["objective_code"] in objectives
        )
        assert Fraction(ex["answer"]) == truth(ex)
    mappings = json.loads((root / "material_mappings.json").read_text())
    unique(mappings, "edition_code", "item_code", "objective_code", "page_physical")
    for r in mappings:
        assert (
            r["edition_code"] in editions
            and r["item_code"] in spec
            and r["objective_code"] in objectives
        )
        assert str(r["page_physical"]) == r["page_printed"] and r["status"] in (
            "confirmed",
            "proposed",
        )
    interventions = rows(root, "6_interventions.csv")
    pilots = rows(root, "7_pilots.csv")
    logs = rows(root, "8_fidelity_logs.csv")
    follow = rows(root, "9_followups.csv")
    unique(interventions, "intervention_id")
    unique(pilots, "pilot_id")
    unique(logs, "log_id")
    unique(follow, "followup_id")
    unique(follow, "pilot_id", "learner_code")
    ints = {r["intervention_id"] for r in interventions}
    ps = {r["pilot_id"]: r for r in pilots}
    learner_class = {r["learner_code"]: r["class_code"] for r in roster}
    for filename, fields in {
        "4_roster.csv": ("period_start", "period_end"),
        "5_responses.csv": ("date",),
        "7_pilots.csv": ("start_date", "end_date"),
        "8_fidelity_logs.csv": ("date",),
    }.items():
        for record in rows(root, filename):
            for field in fields:
                assert date.fromisoformat(record[field]).isoformat() == record[field]
    for r in interventions:
        assert all(
            int(r[k]) > 0
            for k in ("sessions_planned", "minutes_per_session", "practice_items")
        )
        assert (
            r["objective_code"] in objectives
            and r["misconception"] in MC
            and r["is_synthetic"] == "true"
        )
    for r in pilots:
        assert r["intervention_id"] in ints and r["is_synthetic"] == "true"
        assert set(r["class_codes"].split(";")) <= set(classes)
        assert (
            r["baseline_assessment"] == "JURY-POST-2026"
            and r["followup_assessment"] == "JURY-FOLLOWUP-2026"
        )
    for p in pilots:
        assert date.fromisoformat(p["start_date"]) < date.fromisoformat(p["end_date"])
    for r in logs:
        assert int(r["session"]) in (1, 2)
        p = ps[r["pilot_id"]]
        assert p["start_date"] <= r["date"] <= p["end_date"]
        assert r["pilot_id"] in ps and r["is_synthetic"] == "true"
        assert r["class_code"] in ps[r["pilot_id"]]["class_codes"].split(";")
        for done, planned in [
            ("actual_minutes", "planned_minutes"),
            ("completed_items", "planned_items"),
        ]:
            assert 0 <= int(r[done]) <= int(r[planned])
        assert r["status"] in ("completed", "cancelled")
        if r["status"] == "cancelled":
            assert int(r["actual_minutes"]) == int(r["completed_items"]) == 0
    unique(logs, "pilot_id", "class_code", "session")
    for r in follow:
        assert (
            r["pilot_id"] in ps
            and r["learner_code"] in learners
            and r["is_synthetic"] == "true"
        )
        assert learner_class[r["learner_code"]] in ps[r["pilot_id"]][
            "class_codes"
        ].split(";")
        assert (
            r["assessment_code"] == ps[r["pilot_id"]]["followup_assessment"]
            and int(r["days_since_post"]) == 21
        )
        assert r["included"] in ("true", "false") and r["comparable"] in (
            "true",
            "false",
        )
        assert bool(r["exclusion_reason"]) == (r["included"] == "false")
    return manifest["counts"]


def scoring_frames(root=OUT):
    """Feed CSV values into the actual production scoring functions, not a substitute formula."""
    roster = pd.DataFrame(rows(root, "4_roster.csv")).rename(
        columns=dict(
            learner_code="learner_id",
            class_code="cohort_id",
            school_code="school_id",
            teacher_code="teacher_id",
            edition_code="arm",
        )
    )
    resp = pd.DataFrame(rows(root, "5_responses.csv"))
    resp = resp[resp.status != "absent"].rename(
        columns=dict(
            learner_code="learner_id", item_code="item_id", response="response_value"
        )
    )
    resp = resp.merge(
        roster[["learner_id", "cohort_id", "school_id", "teacher_id"]],
        on="learner_id",
        validate="many_to_one",
    )
    resp["score"] = pd.to_numeric(resp.score, errors="coerce")
    resp["attempt"] = resp.attempt.astype(int)
    bank = {
        r["item_code"]: r
        for r in rows(root, "3_item_bank.csv")
        if r["form_stage"] == "post"
    }
    resp["max_points"] = resp.item_id.map(lambda i: float(bank[i]["max_points"]))
    links = []
    for item, r in bank.items():
        if r["mapping_status"] != "confirmed":
            continue
        for entry in r["objective_codes"].split(";"):
            parts = entry.split(":")
            links.append(
                dict(
                    item_id=item,
                    objective_id=parts[0],
                    weight=float(parts[1]) if len(parts) > 1 else 1,
                )
            )
    return resp, roster, pd.DataFrame(links)


def evaluate(root=OUT, check=True):
    resp, roster, links = scoring_frames(root)
    expected = json.loads((root / "expected_findings.json").read_text())
    obj_topic = {
        r["objective_code"]: r["topic_code"] for r in rows(root, "1_program.csv")
    }

    def scores(stage, unit, objective=False):
        w = scoring.item_unit_weights(
            links, {x: x for x in obj_topic} if objective else obj_topic, unit
        )
        return scoring.learner_unit_scores(
            resp[resp.form_code == f"JURY-{stage.upper()}"], w
        )

    donor_post = scores("post", "JURY-T2")
    donor_follow = scores("followup", "JURY-T2")
    frac = scores("post", "JURY-T1")
    target = scores("post", "6.2.1", True)
    # Baseline includes all shown items, with their actual max_points (including proposed mappings).
    pre = resp[resp.form_code == "JURY-PRE"]
    weights = pd.DataFrame(dict(item_id=pre.item_id.unique(), w=1.0))
    baseline = scoring.learner_unit_scores(pre, weights)
    comp = roster.merge(
        frac[["learner_id", "score"]].rename(columns={"score": "outcome"}),
        on="learner_id",
        how="left",
    )
    comp = comp.merge(
        baseline[["learner_id", "score"]].rename(columns={"score": "baseline"}),
        on="learner_id",
        how="left",
    )
    comparison = compare_arms(comp, "JURY-A", "JURY-B")
    out = dict(
        is_synthetic=True,
        seed=SEED,
        fractions_mean=float(frac.score.mean()),
        target_mean=float(target.score.mean()),
        fractions_pre_mean=float(scores("pre", "JURY-T1").score.mean()),
        raw_A_minus_B=-comparison["raw"]["difference"],
        adjusted_A_minus_B=-comparison["adjusted"]["difference"],
        comparison=comparison,
        donor=dict(
            topic="JURY-T2",
            post_mean=float(donor_post.score.mean()),
            followup_mean=float(donor_follow.score.mean()),
            post_class_sd=float(donor_post.groupby("cohort_id").score.mean().std()),
        ),
    )
    # Item-rest correlations are QA diagnostics. Production API currently exposes p and omissions only.
    post = resp[resp.form_code == "JURY-POST"].copy()
    post["share"] = post.score / post.max_points
    pivot = post.pivot(index="learner_id", columns="item_id", values="share")
    out["item_quality"] = {}
    for code in (
        "JURY-I13",
        "JURY-I14",
        "JURY-I30",
        "JURY-I34",
        "JURY-I35",
        "JURY-I36",
    ):
        d = post[post.item_id == code]
        rest = pivot.drop(columns=[code]).mean(axis=1)
        out["item_quality"][code] = dict(
            p_answered=float(d.share.mean()),
            omission_rate=float(d.status.eq("omitted").mean()),
            item_rest_correlation=float(pivot[code].corr(rest)),
            option_counts={
                str(k): int(v)
                for k, v in d[d.status == "answered"]
                .response_value.value_counts()
                .items()
            },
        )
    specs = {s["code"]: s for s in json.loads((root / "item_math.json").read_text())}
    backend_m2 = MC["M2"][0]
    item_m2 = {
        s["code"]: {o["key"] for o in s["options"] if o["tag"] == "M2"}
        for s in specs.values()
        if s["objective"] == "6.2.1"
    }
    m2 = post[
        post.apply(lambda r: r.response_value in item_m2.get(r.item_id, set()), axis=1)
    ]
    out["M2"] = dict(backend_code=backend_m2, n_learners=int(m2.learner_id.nunique()))
    out["M2"]["rate_denominator"] = (
        "incorrect answered target-item responses; not all learners"
    )
    out["M2"]["by_edition"] = {
        arm: float(
            d.apply(
                lambda r: r.response_value in item_m2.get(r.item_id, set()), axis=1
            ).mean()
        )
        for arm, d in post[
            post.item_id.isin(item_m2) & post.status.eq("answered") & post.score.eq(0)
        ]
        .merge(roster[["learner_id", "arm"]], on="learner_id")
        .groupby("arm")
    }
    before = scores("post", "6.2.1", True).set_index("learner_id").score
    after = scores("followup", "6.2.1", True).set_index("learner_id").score
    pilots = rows(root, "7_pilots.csv")
    logs = rows(root, "8_fidelity_logs.csv")
    follow = rows(root, "9_followups.csv")
    out["pilots"] = {}
    for p in pilots:
        pid = p["pilot_id"]
        included = [
            r for r in follow if r["pilot_id"] == pid and r["included"] == "true"
        ]
        ids = {r["learner_code"] for r in included}
        paired = pd.DataFrame(dict(before=before, after=after)).dropna()
        paired = paired[paired.index.isin(ids)]
        log = [r for r in logs if r["pilot_id"] == pid]
        fidelity = min(
            sum(int(r["actual_minutes"]) for r in log)
            / sum(int(r["planned_minutes"]) for r in log),
            sum(int(r["completed_items"]) for r in log)
            / sum(int(r["planned_items"]) for r in log),
        )
        eligible = sum(r["pilot_id"] == pid for r in follow)
        comparable = all(r["comparable"] == "true" for r in included)
        status = (
            "needs_more_data"
            if len(paired) < 30 or len(paired) / eligible < 0.70 or not comparable
            else "invalid_due_to_fidelity"
            if fidelity < 0.8
            else "positive_signal"
            if (paired.after - paired.before).mean() > 0
            else "not_confirmed"
        )
        # Suppress every outcome cell for small cohorts; report contains no learner IDs or subgroup splits.
        small = len(paired) < 10
        actual_pair = paired_change(
            scores("post", "6.2.1", True).query("learner_id in @ids"),
            scores("followup", "6.2.1", True).query("learner_id in @ids"),
        )
        out["pilots"][pid.rsplit("-", 1)[1]] = dict(
            backend_paired_available=actual_pair["available"],
            backend_paired_reason=actual_pair.get("reason"),
            uncertainty=None,
            fixture_only=True,
            status=status,
            fidelity=fidelity,
            n_paired=None if small else len(paired),
            observed_gain=None
            if small
            else float((paired.after - paired.before).mean()),
            suppressed=small,
            inference="descriptive_paired_change; no causal identification; identical form retest",
        )
    if check:
        for field in (
            "fractions_mean",
            "target_mean",
            "raw_A_minus_B",
            "adjusted_A_minus_B",
        ):
            in_range(out[field], expected[field])
        assert out["fractions_pre_mean"] > out["fractions_mean"]
        assert min(out["donor"]["post_mean"], out["donor"]["followup_mean"]) >= 0.80
        assert abs(out["donor"]["post_mean"] - out["donor"]["followup_mean"]) <= 0.05
        assert out["donor"]["post_class_sd"] < 0.10
        assert out["M2"]["n_learners"] >= 100
        assert out["M2"]["by_edition"]["JURY-B"] > out["M2"]["by_edition"]["JURY-A"]
        assert (
            comparison["inference_level"] == "adjusted_association"
            and comparison["causal_protocol_available"] is False
        )
        assert all(
            min(r["n_a"], r["n_b"]) >= 10 for r in comparison["adjusted"]["strata"]
        )
        for key, e in expected["pilots"].items():
            assert out["pilots"][key]["status"] == e["status"]
            if "gain" in e:
                in_range(out["pilots"][key]["observed_gain"], e["gain"])
        assert out["item_quality"]["JURY-I13"]["p_answered"] > 0.95
        assert out["item_quality"]["JURY-I30"]["p_answered"] < 0.1
        assert out["item_quality"]["JURY-I35"]["omission_rate"] > 0.15
        assert out["item_quality"]["JURY-I36"]["item_rest_correlation"] < 0
        dead_key = specs["JURY-I14"]["options"]
        dead_value = specs["JURY-I14"]["distractors"][-1][0]
        key = next(o["key"] for o in dead_key if o["text"] == dead_value)
        assert key not in out["item_quality"]["JURY-I14"]["option_counts"]
    return out


def connect_material_links(session, dataset_id, root=OUT):
    """Opt-in local fixture adapter. Uses existing models; never adds an API or production code path.

    Documents must already be uploaded/extracted through the normal document path.
    Refuses non-synthetic projects, wrong file hashes and unrelated editions. Idempotent.
    """
    from oqumap import models as m
    from oqumap.services.common import audit, bump_dataset_version
    from sqlalchemy import select

    ds = session.get(m.Dataset, dataset_id)
    assert ds and ds.is_synthetic and ds.program_version_id, (
        "Synthetic imported dataset required"
    )
    manifest = json.loads((root / "manifest.json").read_text())
    pv = session.get(m.ProgramVersion, ds.program_version_id)
    objectives = {
        o.code: o
        for o in session.scalars(
            select(m.LearningObjective).where(
                m.LearningObjective.program_version_id == pv.id
            )
        )
    }
    assert set(objectives) == {r["objective_code"] for r in rows(root, "1_program.csv")}
    editions = {
        e.code: e
        for e in session.scalars(
            select(m.TextbookEdition).where(m.TextbookEdition.org_id == ds.org_id)
        )
    }
    mapping = json.loads((root / "material_mappings.json").read_text())
    added = 0
    for entry in mapping:
        ed = editions[entry["edition_code"]]
        doc = session.get(m.Document, ed.document_id)
        assert doc and doc.org_id == ds.org_id and doc.status == "ready"
        name = f"materials/textbook_{ed.code[-1]}.pdf"
        assert doc.sha256 == manifest["files"][name]["sha256"], (
            "Wrong material; refusing to link"
        )
        fragments = list(
            session.scalars(
                select(m.ContentFragment)
                .where(
                    m.ContentFragment.document_id == doc.id,
                    m.ContentFragment.document_version == doc.version,
                    m.ContentFragment.page_physical == entry["page_physical"],
                )
                .order_by(m.ContentFragment.order_index)
            )
        )
        assert fragments, entry
        frag = fragments[0]
        obj = objectives[entry["objective_code"]]
        exists = session.scalar(
            select(m.FragmentObjective).where(
                m.FragmentObjective.org_id == ds.org_id,
                m.FragmentObjective.fragment_id == frag.id,
                m.FragmentObjective.objective_id == obj.id,
                m.FragmentObjective.role == entry["role"],
            )
        )
        if not exists:
            session.add(
                m.FragmentObjective(
                    org_id=ds.org_id,
                    fragment_id=frag.id,
                    objective_id=obj.id,
                    role=entry["role"],
                    status=entry["status"],
                    origin="template",
                    rationale="Explicit synthetic fixture link; page and objective checked, not a causal claim.",
                )
            )
            session.flush()
            added += 1
    # Importer equates presence of KZ with verification and imported codes with official codes.
    # Correct those metadata flags for this explicitly synthetic, unreviewed fixture using existing fields.
    metadata_changed = not pv.is_demo_codes
    pv.is_demo_codes = True
    for obj in objectives.values():
        metadata_changed |= obj.kz_verified
        obj.kz_verified = False
    for topic in session.scalars(
        select(m.Topic).where(m.Topic.program_version_id == pv.id)
    ):
        metadata_changed |= topic.kz_verified
        topic.kz_verified = False
    for item in session.scalars(
        select(m.Item).where(m.Item.program_version_id == pv.id)
    ):
        metadata_changed |= item.kz_verified
        item.kz_verified = False
    ds.manifest = manifest
    if added or metadata_changed:
        bump_dataset_version(
            session, ds, "explicit synthetic material fixture metadata"
        )
        audit(
            session,
            ds.org_id,
            None,
            "jury_fixture.attach_materials",
            "dataset",
            ds.id,
            added=added,
        )
    session.commit()
    return added
