"""Create the demonstration organisations, curriculum, materials and synthetic datasets.

Run: ``python -m oqumap.demo.seed`` (idempotent: an existing demo seed is left untouched unless --reset).
All learner data goes through the regular import pipeline (validate → commit), exactly like a user upload.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import REPO_ROOT, get_settings
from ..db import Base, engine, session_factory, stable_id
from ..services import documents as docsvc
from ..services import imports as imp
from . import generator as gen
from . import materials
from .content import (
    FORMS,
    ITEMS,
    OBJECTIVES,
    PREREQUISITES,
    PROGRAM,
    SCALES,
    TOPICS,
    UNVERIFIED_MAPPING_TOPICS,
)

log = logging.getLogger("oqumap.seed")

DEMO_ORG_ID = stable_id("org", "demo")
OTHER_ORG_ID = stable_id("org", "other")
FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
IMPORTS_DIR = REPO_ROOT / "data" / "demo" / "imports"
GENERATED_DIR = REPO_ROOT / "data" / "demo" / "generated"

DATASETS = [
    {
        "code": "base", "scenario": gen.base_scenario,
        "name_ru": "Основной демо-корпус: математика 6 класс, 2025–2026",
        "name_kz": "Негізгі демо-корпус: математика 6-сынып, 2025–2026",
        "description_ru": "~800 синтетических учеников, 32 класса, 8 условных школ, пособия А и Б, входная и "
                          "итоговая проверки. Пособием А чаще пользуются более подготовленные школы (эффект состава "
                          "групп); тема T6 размечена без подтверждения; тема T8 не измерялась; есть пропуски, "
                          "отсутствия и повторные попытки.",
        "description_kz": "~800 синтетикалық оқушы, 32 сынып, 8 шартты мектеп, А және Б құралдары, кіріс және қорытынды "
                          "тексерулер. Топ құрамының әсері бар; T6 тақырыбы расталмаған; T8 өлшенбеген.",
        "expected": ["composition_changes_ranking", "unverified_topic", "unmeasured_topic", "missing_and_retakes"],
    },
    {
        "code": "no_difference", "scenario": gen.no_difference_scenario,
        "name_ru": "Сценарий: нет различий между пособиями", "name_kz": "Сценарий: құралдар арасында айырма жоқ",
        "description_ru": "Пособия распределены внутри каждой школы поровну; синтетический механизм не содержит эффекта пособия.",
        "description_kz": "Құралдар әр мектепте тең бөлінген; синтетикалық механизмде құрал әсері жоқ.",
        "expected": ["no_difference"],
    },
    {
        "code": "few_clusters", "scenario": gen.few_clusters_scenario,
        "name_ru": "Сценарий: мало классов при большом числе ответов", "name_kz": "Сценарий: жауап көп, сынып аз",
        "description_ru": "4 класса (по 2 на пособие), по три попытки темы T3: тысячи ответов, но мало независимых групп.",
        "description_kz": "4 сынып, T3 тақырыбы бойынша үш әрекет: жауаптар көп, тәуелсіз топтар аз.",
        "expected": ["few_clusters"],
    },
    {
        "code": "unlinked_forms", "scenario": gen.unlinked_forms_scenario,
        "name_ru": "Сценарий: разные итоговые тесты без выравнивания шкал", "name_kz": "Сценарий: шкаласы теңестірілмеген әртүрлі тесттер",
        "description_ru": "Классы пособия Б писали локальную форму F-POST-X, не связанную со шкалой итоговой проверки.",
        "description_kz": "Б құралы сыныптары қорытынды шкаламен байланыспаған F-POST-X формасын жазды.",
        "expected": ["forms_not_linked"],
    },
    {
        "code": "confounded", "scenario": gen.confounded_scenario,
        "name_ru": "Сценарий: пособие совпадает с единственным учителем", "name_kz": "Сценарий: құрал жалғыз мұғаліммен сәйкес келеді",
        "description_ru": "Пособием А пользуются только классы одного учителя одной школы.",
        "description_kz": "А құралын бір мектептің бір мұғалімінің сыныптары ғана қолданады.",
        "expected": ["edition_confounded_with_teacher"],
    },
]


def _hash_password(raw: str) -> str:
    from ..services.auth import hash_password

    return hash_password(raw)


def seed(session: Session, reset: bool = False) -> dict:
    existing = session.get(m.Organization, DEMO_ORG_ID)
    if existing is not None and not reset:
        from .measurement_seed import (
            seed_measurement,  # idempotent add-on for databases seeded before it existed
        )

        return {"status": "exists", "measurement": seed_measurement(session, DEMO_ORG_ID)["status"]}
    if existing is not None and reset:
        raise SystemExit("Use scripts/reset_db to drop the database before reseeding.")
    s = get_settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)

    session.add_all([
        m.Organization(id=DEMO_ORG_ID, name="Демо-сеть школ (синтетические данные)", is_demo=True),
        m.Organization(id=OTHER_ORG_ID, name="Другая организация (пустая, для проверки изоляции)", is_demo=True),
    ])
    session.flush()
    session.add_all([
        m.User(id=stable_id("user", "demo-methodist"), org_id=DEMO_ORG_ID, username="demo.methodist",
               display_name="Методист (демо)", roles=["methodist", "approver", "teacher"], is_demo=True),
        m.User(id=stable_id("user", "demo-viewer"), org_id=DEMO_ORG_ID, username="demo.viewer",
               display_name="Наблюдатель (демо)", roles=["viewer"], is_demo=True),
        m.User(id=stable_id("user", "other-methodist"), org_id=OTHER_ORG_ID, username="other.methodist",
               display_name="Методист другой организации (демо)", roles=["methodist", "approver"], is_demo=True),
    ])
    for org_id in (DEMO_ORG_ID, OTHER_ORG_ID):
        _seed_program(session, org_id)
    _seed_scales_forms(session)
    session.commit()

    editions = _seed_editions_and_documents(session)
    session.commit()

    _write_upload_files()
    datasets = {}
    for spec in DATASETS:
        datasets[spec["code"]] = _seed_dataset_via_import(session, spec)
    datasets["illustration"] = _seed_illustration(session)
    _seed_plan(session, datasets["base"])
    session.commit()
    from .measurement_seed import seed_measurement

    datasets["measurement_loop"] = session.get(m.Dataset, seed_measurement(session, DEMO_ORG_ID)["dataset_id"])
    _write_manifest(datasets)
    try:
        from ..ai.tasks import propose_fragment_links_for_document

        user_id = stable_id("user", "demo-methodist")
        for ed in editions.values():
            doc = session.get(m.Document, ed.document_id)
            propose_fragment_links_for_document(session, DEMO_ORG_ID, user_id, doc.id)
        session.commit()
    except ImportError:  # pragma: no cover - AI module optional during early bootstrap
        pass
    return {"status": "created", "datasets": {k: v.id for k, v in datasets.items()}}


def _seed_program(session: Session, org_id: str) -> None:
    pv_id = stable_id(org_id, "program", PROGRAM["code"])
    session.add(m.ProgramVersion(id=pv_id, org_id=org_id, subject=PROGRAM["subject"], grade=PROGRAM["grade"],
                                 language=PROGRAM["language"], version=PROGRAM["version"], title=PROGRAM["title"],
                                 source=PROGRAM["source"], is_demo_codes=True))
    for i, (code, ru, kz) in enumerate(TOPICS):
        session.add(m.Topic(id=stable_id(org_id, "topic", code), program_version_id=pv_id, code=code, order_index=i,
                            title_ru=ru, title_kz=kz, kz_verified=False))
    session.flush()
    for code, topic, ru, kz in OBJECTIVES:
        session.add(m.LearningObjective(id=stable_id(org_id, "objective", code), program_version_id=pv_id,
                                        topic_id=stable_id(org_id, "topic", topic), code=code, text_ru=ru, text_kz=kz))
    session.flush()
    for src, dst in PREREQUISITES:
        session.add(m.ObjectiveRelation(id=stable_id(org_id, "rel", src, dst),
                                        source_objective_id=stable_id(org_id, "objective", src),
                                        target_objective_id=stable_id(org_id, "objective", dst),
                                        relation_type="prerequisite", confirmed=True))
    for it in ITEMS:
        options = [{"key": letter, "text": text, "correct": letter == it.key, "misconception": tag}
                   for letter, (text, tag) in zip(it.letters, it.options, strict=True)]
        iid = stable_id(org_id, "item", it.code)
        session.add(m.Item(id=iid, program_version_id=pv_id, code=it.code, version=1, item_type="single_choice",
                           stem_ru=it.stem_ru, stem_kz=it.stem_kz, options=options, answer_key=it.key, max_points=1.0))
        unverified = it.topic in UNVERIFIED_MAPPING_TOPICS
        for obj_code, w in it.objectives:
            session.add(m.ItemObjective(id=stable_id(org_id, "io", it.code, obj_code), item_id=iid,
                                        objective_id=stable_id(org_id, "objective", obj_code), weight=w,
                                        status="proposed" if unverified else "confirmed",
                                        origin="item_bank_author", org_id=org_id))
    session.flush()


def _seed_scales_forms(session: Session) -> None:
    for code, name, method, desc in SCALES:
        if session.scalar(select(m.Scale).where(m.Scale.code == code)) is None:
            session.add(m.Scale(id=stable_id("scale", code), code=code, name=name, linking_method=method, description=desc))
    session.flush()
    for org_id in (DEMO_ORG_ID, OTHER_ORG_ID):
        pv_id = stable_id(org_id, "program", PROGRAM["code"])
        for fcode, f in FORMS.items():
            fid = stable_id(org_id, "form", fcode)
            session.add(m.AssessmentForm(id=fid, program_version_id=pv_id, code=fcode, name=f["name"],
                                         scale_id=stable_id("scale", f["scale"]), stage_hint=f["stage"]))
            session.flush()
            for pos, icode in enumerate(f["items"], start=1):
                session.add(m.FormItem(id=stable_id(org_id, "fi", fcode, icode), form_id=fid,
                                       item_id=stable_id(org_id, "item", icode), position=pos))
    session.flush()


def _seed_editions_and_documents(session: Session) -> dict[str, m.TextbookEdition]:
    eds = {
        "EDA": m.TextbookEdition(id=stable_id(DEMO_ORG_ID, "edition", "EDA"), org_id=DEMO_ORG_ID, code="EDA",
                                 title="Демонстрационное пособие А", edition_label="демо-издание 1", year=2025,
                                 language="ru", grade=6, is_demo=True,
                                 usage_permission="Собственный демонстрационный материал OquMap"),
        "EDB": m.TextbookEdition(id=stable_id(DEMO_ORG_ID, "edition", "EDB"), org_id=DEMO_ORG_ID, code="EDB",
                                 title="Демонстрационное пособие Б", edition_label="демо-издание 1", year=2025,
                                 language="ru", grade=6, is_demo=True,
                                 usage_permission="Собственный демонстрационный материал OquMap"),
    }
    session.add_all(eds.values())
    session.flush()
    out_dir = REPO_ROOT / "data" / "demo" / "materials"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = materials.build_pdf(str(FONT_DIR / "DejaVuSans.ttf"), str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    docx_bytes = materials.build_docx()
    (out_dir / "demo_posobie_A.pdf").write_bytes(pdf)
    (out_dir / "demo_posobie_B.docx").write_bytes(docx_bytes)
    for code, data, name in (("EDA", pdf, "demo_posobie_A.pdf"), ("EDB", docx_bytes, "demo_posobie_B.docx")):
        doc, _ = docsvc.store_document(session, DEMO_ORG_ID, None, data, name, edition_id=eds[code].id, is_demo=True)
        docsvc.extract_document(session, doc)
    return eds


def _write_upload_files() -> None:
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (IMPORTS_DIR / "followup_2026_2027.csv").write_text(gen.to_csv(gen.generate_rows(gen.followup_scenario())), encoding="utf-8")
    (IMPORTS_DIR / "upload_sample_with_errors.csv").write_text(gen.to_csv(gen.errors_sample_rows()), encoding="utf-8")
    import csv
    import io

    buf = io.StringIO()
    rows = gen.grades_only_rows()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (IMPORTS_DIR / "grades_only_sample.csv").write_text(buf.getvalue(), encoding="utf-8")


def _seed_dataset_via_import(session: Session, spec: dict) -> m.Dataset:
    sc = spec["scenario"]()
    csv_text = gen.to_csv(gen.generate_rows(sc))
    path = GENERATED_DIR / f"{spec['code']}.csv"
    path.write_text(csv_text, encoding="utf-8")
    pv_id = stable_id(DEMO_ORG_ID, "program", PROGRAM["code"])
    ds = m.Dataset(
        id=stable_id(DEMO_ORG_ID, "dataset", spec["code"]), org_id=DEMO_ORG_ID, program_version_id=pv_id,
        code=spec["code"], name_ru=spec["name_ru"], name_kz=spec["name_kz"], description_ru=spec["description_ru"],
        description_kz=spec["description_kz"], is_synthetic=True, scenario=spec["code"], version=0,
        manifest={"generator": "oqumap.demo.generator", "scenario": sc.code, "seed": sc.seed,
                  "expected_behaviour": spec["expected"], "edition_effects": {f"{k[0]}:{k[1]}": v for k, v in sc.edition_effects.items()},
                  "academic_year": sc.academic_year},
    )
    session.add(ds)
    session.commit()
    org = session.get(m.Organization, DEMO_ORG_ID)
    batch = imp.validate_upload(session, org=org, user_id=None, data=csv_text.encode("utf-8"),
                                filename=f"{spec['code']}.csv", kind="responses", dataset_id=ds.id, new_dataset=None,
                                sheet=None, mapping=None, options={})
    if batch.rows_rejected:
        raise RuntimeError(f"seed dataset {spec['code']} has rejected rows: {batch.report['errors_by_code']}")
    imp.commit_batch(session, DEMO_ORG_ID, batch.id, None)
    session.refresh(ds)
    return ds


def _seed_illustration(session: Session) -> m.Dataset:
    from ..analytics.fixtures import load_fixture

    fx = load_fixture()
    rows = []
    n = 0
    for cell in fx["cells"]:
        for i in range(cell["total"]):
            n += 1
            cls = f"IL-{cell['arm']}-{cell['stratum']}-{i % 2}"
            base = dict(school_code=f"IL-SCH-{cls[3:]}", class_code=cls, teacher_code=f"IL-T-{cls[3:]}", language="ru",
                        grade=6, academic_year="2025-2026", edition_code="EDA" if cell["arm"] == "A" else "EDB",
                        learner_code=f"IL{n:04d}", attempt=1, status="answered", response="")
            rows.append(dict(base, assessment_code="IL-PRE", form_code="F-ILLUS-PRE", item_code="I24",
                             score="1" if cell["stratum"] == "high" else "0", date="2025-09-08"))
            rows.append(dict(base, assessment_code="IL-POST", form_code="F-ILLUS-POST", item_code="I14",
                             score="1" if i < cell["passed"] else "0", date="2026-05-20"))
    csv_text = gen.to_csv(rows)
    pv_id = stable_id(DEMO_ORG_ID, "program", PROGRAM["code"])
    ds = m.Dataset(
        id=stable_id(DEMO_ORG_ID, "dataset", "illustration"), org_id=DEMO_ORG_ID, program_version_id=pv_id,
        code="illustration", name_ru="Учебная иллюстрация: стандартизация состава групп (76/63 → 60/75)",
        name_kz="Оқу иллюстрациясы: топ құрамын стандарттау (76/63 → 60/75)",
        description_ru=fx["purpose"] + " Строки построены из data/demo/fixtures/composition_fixture.json.",
        description_kz="Стандарттау әдісін түсіндіруге арналған арифметикалық мысал; себептілік дәлелі емес.",
        is_synthetic=True, scenario="illustration", version=0,
        manifest={"fixture": fx["fixture_id"], "strata_scheme": fx["strata_scheme"], "weights": "equal",
                  "expected_behaviour": ["raw_76_63", "standardized_60_75", "no_intervals"]},
    )
    session.add(ds)
    session.commit()
    org = session.get(m.Organization, DEMO_ORG_ID)
    batch = imp.validate_upload(session, org=org, user_id=None, data=csv_text.encode(), filename="illustration.csv",
                                kind="responses", dataset_id=ds.id, new_dataset=None, sheet=None, mapping=None, options={})
    assert batch.rows_rejected == 0, batch.report.get("errors_by_code")
    imp.commit_batch(session, DEMO_ORG_ID, batch.id, None)
    session.refresh(ds)
    return ds


PLAN_HOURS = {"T1": (12, 12, 8, 16), "T2": (14, 6, 10, 18), "T3": (14, 0, 10, 20), "T4": (14, 0, 10, 18),
              "T5": (16, 0, 10, 18), "T6": (10, 0, 8, 14), "T7": (12, 0, 8, 16), "T8": (10, 0, 8, 14)}


def _seed_plan(session: Session, ds: m.Dataset) -> None:
    group = stable_id(DEMO_ORG_ID, "plan-group", "base")
    plan = m.TeachingPlan(id=stable_id(DEMO_ORG_ID, "plan", "base", "1"), org_id=DEMO_ORG_ID, dataset_id=ds.id,
                          plan_group_id=group, version=1, name="Действующий план часов по темам (условный)",
                          scope="6 класс, все классы набора", horizon="2026–2027 учебный год (по состоянию на 11.11.2026)",
                          status="current")
    session.add(plan)
    session.flush()
    for code, (planned, elapsed, lo, hi) in PLAN_HOURS.items():
        session.add(m.PlanTopicHours(plan_id=plan.id, topic_id=stable_id(DEMO_ORG_ID, "topic", code),
                                     planned_hours=planned, elapsed_hours=elapsed, min_hours=lo, max_hours=hi))


def _write_manifest(datasets: dict[str, m.Dataset]) -> None:
    out = {
        "generated_on": date.today().isoformat(),
        "is_synthetic": True,
        "generator": "apps/api/oqumap/demo/generator.py",
        "datasets": {code: {"id": ds.id, "name": ds.name_ru, "version": ds.version, "manifest": ds.manifest}
                     for code, ds in datasets.items()},
        "upload_files": sorted(p.name for p in IMPORTS_DIR.glob("*.csv")),
    }
    (REPO_ROOT / "data" / "demo" / "manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-schema", action="store_true", help="create tables without Alembic (tests only)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.create_schema:
        Base.metadata.create_all(engine())
    with session_factory()() as session:
        print(json.dumps(seed(session), ensure_ascii=False))


if __name__ == "__main__":
    main()
