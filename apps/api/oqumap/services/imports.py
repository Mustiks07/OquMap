"""CSV/XLSX import: read → map columns → validate row by row → commit (idempotent).

Guarantees (tested in tests/test_imports.py):
* rejected rows are never inserted and never become zeros;
* the same file (sha256) cannot be committed twice into one dataset;
* committing the same batch twice returns the first result without inserting anything;
* every batch stores the source hash, column mapping, options and TRANSFORM_VERSION.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import new_id, utcnow
from ..errors import ApiError, not_found
from .common import audit, bump_dataset_version, sha256_bytes

TRANSFORM_VERSION = "import-v1"
MAX_REPORTED_ROWS = 200

FIELDS = {
    "responses": {
        "required": ["learner_code", "assessment_code"],
        "optional": [
            "class_code", "school_code", "teacher_code", "language", "grade", "academic_year", "edition_code",
            "form_code", "item_code", "attempt", "status", "score", "response", "date",
        ],
    },
    "grades": {
        "required": ["learner_code", "class_code", "grade_value"],
        "optional": ["school_code", "teacher_code", "language", "grade", "academic_year", "period", "grade_scale_max"],
    },
}

SYNONYMS = {
    "learner_code": ["learner_code", "learner", "student", "student_id", "ученик", "код ученика", "оқушы", "pupil"],
    "class_code": ["class_code", "class", "класс", "сынып", "cohort"],
    "school_code": ["school_code", "school", "школа", "мектеп"],
    "teacher_code": ["teacher_code", "teacher", "учитель", "мұғалім"],
    "language": ["language", "lang", "язык", "тіл"],
    "grade": ["grade", "параллель", "класс обучения"],
    "academic_year": ["academic_year", "year", "учебный год", "оқу жылы"],
    "edition_code": ["edition_code", "edition", "textbook", "учебник", "издание", "оқулық"],
    "assessment_code": ["assessment_code", "assessment", "test", "тест", "проверка", "работа"],
    "form_code": ["form_code", "form", "вариант", "форма"],
    "item_code": ["item_code", "item", "question", "задание", "вопрос", "тапсырма"],
    "attempt": ["attempt", "попытка", "әрекет"],
    "status": ["status", "статус"],
    "score": ["score", "points", "балл", "баллы", "ұпай"],
    "response": ["response", "answer", "ответ", "жауап", "выбранный ответ"],
    "date": ["date", "дата", "күні"],
    "grade_value": ["grade_value", "оценка", "баға", "mark"],
    "grade_scale_max": ["grade_scale_max", "максимум шкалы"],
    "period": ["period", "период", "четверть", "тоқсан"],
}

STATUSES = {"answered", "omitted", "absent"}
STATUS_ALIASES = {
    "": None, "answered": "answered", "ответ": "answered", "omitted": "omitted", "skip": "omitted",
    "skipped": "omitted", "пропуск": "omitted", "absent": "absent", "отсутствовал": "absent", "н": "absent",
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    sheets: list[str] = field(default_factory=list)
    sheet: str | None = None


def read_table(data: bytes, filename: str, sheet: str | None = None) -> Table:
    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise ApiError("file_too_large", "Файл превышает допустимый размер", 413,
                       {"max_bytes": settings.max_upload_bytes})
    name = filename.lower()
    if name.endswith(".xlsx"):
        return _read_xlsx(data, sheet)
    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(data)
    raise ApiError("unsupported_file_type", "Поддерживаются CSV и XLSX", 415, {"filename": filename})


def _read_csv(data: bytes) -> Table:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise ApiError("file_unreadable", "Не удалось определить кодировку файла", 422)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader]
    if not rows:
        raise ApiError("empty_file", "Файл пуст", 422)
    headers = [h.strip() for h in rows[0]]
    body = rows[1:]
    _check_rows(len(body))
    return Table(headers, body)


def _read_xlsx(data: bytes, sheet: str | None) -> Table:
    from openpyxl import load_workbook

    try:
        # data_only=False: a formula cell is read as its formula text (e.g. "=1+1") and then rejected by
        # validation; formulas are never evaluated and cached results are not trusted. Macros never run.
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as exc:  # corrupted or not an xlsx
        raise ApiError("file_unreadable", "Файл XLSX повреждён или имеет неверный формат", 422,
                       {"reason": type(exc).__name__}) from None
    sheets = wb.sheetnames
    target = sheet or sheets[0]
    if target not in sheets:
        raise ApiError("unknown_sheet", "Лист не найден", 422, {"sheet": target, "sheets": sheets})
    ws = wb[target]
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(["" if v is None else _cell_str(v) for v in row])
    wb.close()
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        raise ApiError("empty_file", "Лист пуст", 422, {"sheet": target})
    headers = [h.strip() for h in rows[0]]
    body = rows[1:]
    _check_rows(len(body))
    return Table(headers, body, sheets, target)


def _cell_str(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, date):
        return v.isoformat()[:10]
    return str(v)


def _check_rows(n: int) -> None:
    if n > get_settings().max_import_rows:
        raise ApiError("too_many_rows", "Слишком много строк в файле", 413, {"max_rows": get_settings().max_import_rows})


def suggest_mapping(headers: list[str], kind: str) -> dict[str, str]:
    fields = FIELDS[kind]["required"] + FIELDS[kind]["optional"]
    out: dict[str, str] = {}
    norm = {h: h.strip().lower() for h in headers}
    for f in fields:
        for h, hn in norm.items():
            if h in out.values():
                continue
            if hn in SYNONYMS.get(f, [f]):
                out[f] = h
                break
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class RowResult:
    row_number: int  # 1-based data row number (header excluded)
    values: dict
    errors: list[dict]


@dataclass
class ProgramIndex:
    items: dict[str, m.Item]
    forms: dict[str, m.AssessmentForm]
    form_items: dict[str, set[str]]  # form_id -> item ids
    editions: dict[str, m.TextbookEdition]
    topics: list[m.Topic]


def program_index(session: Session, org_id: str, program_version_id: str) -> ProgramIndex:
    items = {}
    for it in session.scalars(select(m.Item).where(m.Item.program_version_id == program_version_id)
                              .order_by(m.Item.version)):
        items[it.code] = it  # latest version wins
    forms = {f.code: f for f in session.scalars(select(m.AssessmentForm)
                                                .where(m.AssessmentForm.program_version_id == program_version_id))}
    form_items: dict[str, set[str]] = defaultdict(set)
    if forms:
        for fi in session.scalars(select(m.FormItem).where(m.FormItem.form_id.in_([f.id for f in forms.values()]))):
            form_items[fi.form_id].add(fi.item_id)
    editions = {e.code: e for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == org_id))}
    topics = list(session.scalars(select(m.Topic).where(m.Topic.program_version_id == program_version_id)))
    return ProgramIndex(items, forms, form_items, editions, topics)


def _num(v: str) -> float | None:
    s = v.strip().replace(",", ".")
    if s == "":
        return None
    f = float(s)
    if not math.isfinite(f):
        raise ValueError("non-finite")
    return f


_CODE_RE = re.compile(r"^[\w\-.:/ ]{1,60}$", re.UNICODE)


def validate_rows(
    session: Session,
    dataset: m.Dataset | None,
    program_version_id: str,
    org_id: str,
    table: Table,
    mapping: dict[str, str],
    kind: str,
    options: dict,
) -> tuple[list[RowResult], dict]:
    spec = FIELDS[kind]
    missing = [f for f in spec["required"] if f not in mapping or mapping[f] not in table.headers]
    if kind == "responses" and "item_code" not in mapping:
        missing.append("item_code")
    if missing:
        raise ApiError("mapping_incomplete", "Не сопоставлены обязательные колонки", 422, {"missing": missing})
    col = {f: table.headers.index(h) for f, h in mapping.items() if h in table.headers}
    idx = program_index(session, org_id, program_version_id)

    existing_learners: dict[str, tuple[str, str]] = {}
    existing_cohorts: dict[str, m.Cohort] = {}
    existing_assessments: dict[str, m.Assessment] = {}
    existing_keys: set[tuple] = set()
    if dataset is not None:
        cohorts = {c.id: c for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == dataset.id))}
        existing_cohorts = {c.code: c for c in cohorts.values()}
        for lr in session.scalars(select(m.Learner).where(m.Learner.dataset_id == dataset.id)):
            existing_learners[lr.code] = (lr.id, cohorts[lr.cohort_id].code)
        existing_assessments = {a.code: a for a in session.scalars(select(m.Assessment)
                                                                    .where(m.Assessment.dataset_id == dataset.id))}
        if kind == "responses" and existing_assessments:
            learner_code_by_id = {v[0]: k for k, v in existing_learners.items()}
            item_code_by_id = {it.id: c for c, it in idx.items.items()}
            acode_by_id = {a.id: a.code for a in existing_assessments.values()}
            q = select(m.Response.assessment_id, m.Response.learner_id, m.Response.item_id, m.Response.attempt).where(
                m.Response.dataset_id == dataset.id)
            for a_id, l_id, i_id, att in session.execute(q):
                existing_keys.add((acode_by_id.get(a_id), learner_code_by_id.get(l_id), item_code_by_id.get(i_id), att))

    default_form = options.get("default_form_code")
    seen_keys: set[tuple] = set()
    learner_class_in_file: dict[str, str] = {}
    results: list[RowResult] = []

    for n, raw in enumerate(table.rows, start=1):
        if not any(c.strip() for c in raw):
            continue
        vals = {f: (raw[i].strip() if i < len(raw) else "") for f, i in col.items()}
        errs: list[dict] = []

        def err(code: str, fld: str | None = None, errs=errs, **params):
            errs.append({"code": code, "field": fld, **params})

        for f in spec["required"]:
            if not vals.get(f):
                err("missing_required", f)
        for f in ("learner_code", "class_code", "school_code", "teacher_code", "assessment_code", "item_code"):
            v = vals.get(f)
            if v and not _CODE_RE.match(v):
                err("invalid_code", f)
            if v and v[0] in "=+-@\t\r":
                err("invalid_code", f, reason="formula_like")

        lc = vals.get("learner_code", "")
        cc = vals.get("class_code", "")
        if lc:
            if lc in existing_learners and cc and existing_learners[lc][1] != cc:
                err("learner_class_conflict", "class_code", existing=existing_learners[lc][1])
            if lc not in existing_learners and not cc:
                err("missing_required", "class_code", reason="new_learner")
            if cc and cc not in existing_cohorts and not vals.get("school_code"):
                err("missing_required", "school_code", reason="new_class")
            prev = learner_class_in_file.get(lc)
            if prev and cc and prev != cc:
                err("learner_class_conflict", "class_code", existing=prev)
            elif cc:
                learner_class_in_file[lc] = cc
        ec = vals.get("edition_code")
        if ec and ec not in idx.editions:
            err("unknown_edition", "edition_code", value=ec)
        lang = vals.get("language")
        if lang and lang not in ("ru", "kz", "en"):
            err("invalid_value", "language", value=lang)
        if vals.get("grade"):
            try:
                g = int(vals["grade"])
                if not 1 <= g <= 12:
                    err("out_of_range", "grade", value=vals["grade"])
            except ValueError:
                err("invalid_number", "grade", value=vals["grade"])

        if kind == "responses":
            _validate_response_row(vals, idx, existing_assessments, default_form, err)
            if not errs:
                key = (vals["assessment_code"], lc, vals.get("item_code") or None, int(vals.get("attempt") or 1))
                if vals.get("_status") != "absent":
                    if key in seen_keys:
                        err("duplicate_row", None)
                    elif key in existing_keys:
                        err("already_in_dataset", None)
                    seen_keys.add(key)
        else:
            try:
                gv = _num(vals.get("grade_value", ""))
                gmax = _num(vals.get("grade_scale_max", "") or "5")
                if gv is None:
                    err("missing_required", "grade_value")
                elif gmax is None or gv < 0 or gv > gmax:
                    err("out_of_range", "grade_value", value=vals["grade_value"])
            except ValueError:
                err("invalid_number", "grade_value", value=vals.get("grade_value"))
        results.append(RowResult(n, vals, errs))

    accepted = [r for r in results if not r.errors]
    rejected = [r for r in results if r.errors]
    by_code = Counter(e["code"] for r in rejected for e in r.errors)
    summary = {
        "rows_total": len(results),
        "rows_accepted": len(accepted),
        "rows_rejected": len(rejected),
        "errors_by_code": dict(by_code),
        "rejected_rows": [
            {"row_number": r.row_number, "errors": r.errors, "values": {k: v for k, v in r.values.items() if not k.startswith("_")}}
            for r in rejected[:MAX_REPORTED_ROWS]
        ],
        "rejected_rows_truncated": len(rejected) > MAX_REPORTED_ROWS,
        "new_learners": len({r.values["learner_code"] for r in accepted if r.values.get("learner_code") not in existing_learners}),
        "new_classes": len({r.values["class_code"] for r in accepted if r.values.get("class_code") and r.values["class_code"] not in existing_cohorts}),
        "assessments": sorted({r.values["assessment_code"] for r in accepted if r.values.get("assessment_code")}),
        "status_counts": dict(Counter(r.values.get("_status") for r in accepted if kind == "responses")),
        "derived_scores": sum(1 for r in accepted if r.values.get("_score_derived")),
    }
    summary["available_analysis"] = _available_analysis(kind, accepted, dataset)
    return results, summary


def _validate_response_row(vals, idx: ProgramIndex, existing_assessments, default_form, err) -> None:
    acode = vals.get("assessment_code", "")
    fcode = vals.get("form_code") or default_form
    form = None
    if acode in existing_assessments:
        form_id = existing_assessments[acode].form_id
        form = next((f for f in idx.forms.values() if f.id == form_id), None)
        if fcode and form and form.code != fcode:
            err("form_mismatch", "form_code", expected=form.code, value=fcode)
    elif acode:
        if not fcode:
            err("unknown_assessment", "assessment_code", value=acode)
        elif fcode not in idx.forms:
            err("unknown_form", "form_code", value=fcode)
        else:
            form = idx.forms[fcode]
    vals["_form_code"] = form.code if form else None

    raw_status = vals.get("status", "").strip().lower()
    if raw_status not in STATUS_ALIASES:
        err("invalid_status", "status", value=vals.get("status"))
        return
    status = STATUS_ALIASES[raw_status]
    if status == "absent":
        vals["_status"] = "absent"
        if vals.get("score") or vals.get("response"):
            err("score_with_absent", "score")
        return

    icode = vals.get("item_code", "")
    if not icode:
        err("missing_required", "item_code")
        return
    item = idx.items.get(icode)
    if item is None:
        err("unknown_item", "item_code", value=icode)
        return
    if form is not None and item.id not in idx.form_items.get(form.id, set()):
        err("item_not_in_form", "item_code", value=icode, form=form.code)
    try:
        att = int(vals.get("attempt") or 1)
        if att < 1 or att > 20:
            err("out_of_range", "attempt", value=vals.get("attempt"))
    except ValueError:
        err("invalid_number", "attempt", value=vals.get("attempt"))
    try:
        score = _num(vals.get("score", ""))
    except ValueError:
        err("invalid_number", "score", value=vals.get("score"))
        return
    resp = vals.get("response", "")
    if status is None:
        status = "omitted" if (score is None and not resp) else "answered"
    vals["_status"] = status
    if status == "omitted":
        if score is not None:
            err("score_with_omitted", "score")
        vals["_score"] = None
        return
    if score is None:
        if resp and item.answer_key:
            score = item.max_points if resp.strip().upper() == item.answer_key.upper() else 0.0
            vals["_score_derived"] = True
        else:
            err("missing_required", "score", reason="answered_without_score")
            return
    if score < 0 or score > item.max_points:
        err("score_out_of_range", "score", value=score, max=item.max_points)
        return
    if resp and item.item_type == "single_choice":
        letters = {o["key"] for o in item.options}
        if resp.strip().upper() not in letters:
            err("invalid_value", "response", value=resp)
    vals["_score"] = score


def _available_analysis(kind: str, accepted: list[RowResult], dataset: m.Dataset | None) -> dict:
    if kind == "grades":
        return {
            "level": "grades_only",
            "possible": ["overview_of_grades"],
            "not_possible": ["topic_diagnostics", "material_comparison", "error_analysis"],
            "missing_fields": ["item_code", "score", "assessment_code", "edition_code", "baseline_assessment"],
        }
    has_edition = any(r.values.get("edition_code") for r in accepted)
    return {
        "level": "item_responses",
        "possible": ["topic_diagnostics", "error_analysis"] + (["material_comparison_if_baseline"] if has_edition else []),
        "not_possible": [] if has_edition else ["material_comparison"],
        "missing_fields": [] if has_edition else ["edition_code"],
    }


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------


def store_upload(org_id: str, data: bytes, filename: str) -> tuple[str, str]:
    digest = sha256_bytes(data)
    ext = Path(filename).suffix.lower()[:6] or ".bin"
    root = get_settings().storage_dir / "imports" / org_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}{ext}"  # never use the user-provided name in the path
    if not path.exists():
        path.write_bytes(data)
    return digest, str(path)


def validate_upload(
    session: Session,
    *,
    org: m.Organization,
    user_id: str | None,
    data: bytes,
    filename: str,
    kind: str,
    dataset_id: str | None,
    new_dataset: dict | None,
    sheet: str | None,
    mapping: dict | None,
    options: dict | None,
) -> m.ImportBatch:
    if kind not in FIELDS:
        raise ApiError("invalid_kind", "Неизвестный тип импорта", 422, {"kind": kind})
    options = dict(options or {})
    table = read_table(data, filename, sheet)
    mapping = mapping or suggest_mapping(table.headers, kind)
    dataset = None
    if dataset_id:
        dataset = session.scalar(select(m.Dataset).where(m.Dataset.id == dataset_id, m.Dataset.org_id == org.id))
        if dataset is None:
            raise not_found("dataset", dataset_id)
        program_version_id = dataset.program_version_id
        is_synthetic = dataset.is_synthetic
    else:
        if not new_dataset or not new_dataset.get("name"):
            raise ApiError("dataset_required", "Укажите набор данных или название нового набора", 422)
        program_version_id = new_dataset.get("program_version_id") or _default_program(session, org.id)
        is_synthetic = bool(new_dataset.get("is_synthetic"))
        options["new_dataset"] = {"name": new_dataset["name"], "program_version_id": program_version_id,
                                  "is_synthetic": is_synthetic}
    if org.is_demo and not is_synthetic:
        raise ApiError("demo_requires_synthetic", "В демо-режиме допускаются только синтетические данные", 422)

    digest, path = store_upload(org.id, data, filename)
    duplicate_of = None
    if dataset is not None:
        prev = session.scalar(select(m.ImportBatch).where(
            m.ImportBatch.dataset_id == dataset.id, m.ImportBatch.file_sha256 == digest,
            m.ImportBatch.status == "committed"))
        duplicate_of = prev.id if prev else None

    try:
        _, summary = validate_rows(session, dataset, program_version_id, org.id, table, mapping, kind, options)
    except ApiError as exc:
        if exc.code != "mapping_incomplete":
            raise
        summary = {"rows_total": len(table.rows), "rows_accepted": 0, "rows_rejected": 0,
                                "mapping_error": exc.details}
    summary.update({
        "headers": table.headers,
        "sheets": table.sheets,
        "sheet": table.sheet,
        "suggested_mapping": suggest_mapping(table.headers, kind),
        "fields": FIELDS[kind],
        "preview": [dict(zip(table.headers, r, strict=False)) for r in table.rows[:15]],
        "duplicate_of_batch": duplicate_of,
    })
    batch = m.ImportBatch(
        org_id=org.id, dataset_id=dataset.id if dataset else None, created_by=user_id, kind=kind,
        filename=Path(filename).name[:300], file_sha256=digest, storage_path=path, size_bytes=len(data), sheet=table.sheet,
        column_mapping=mapping, options=options, transform_version=TRANSFORM_VERSION, status="validated",
        report=summary, rows_total=summary.get("rows_total", 0), rows_accepted=summary.get("rows_accepted", 0),
        rows_rejected=summary.get("rows_rejected", 0), is_synthetic=is_synthetic,
    )
    session.add(batch)
    audit(session, org.id, user_id, "import.validate", "import_batch", batch.id, filename=batch.filename,
          sha256=digest, rows=batch.rows_total)
    session.commit()
    return batch


def _default_program(session: Session, org_id: str) -> str:
    pv = session.scalar(select(m.ProgramVersion).where((m.ProgramVersion.org_id == org_id) | (m.ProgramVersion.org_id.is_(None))))
    if pv is None:
        raise ApiError("no_program", "Нет доступной версии программы", 422)
    return pv.id


def commit_batch(session: Session, org_id: str, batch_id: str, user_id: str | None) -> dict:
    """Commit a validated batch. Idempotent; safe against concurrent double commits."""
    batch = session.scalar(select(m.ImportBatch).where(m.ImportBatch.id == batch_id, m.ImportBatch.org_id == org_id))
    if batch is None:
        raise not_found("import_batch", batch_id)
    if batch.status == "committed":
        return {"batch_id": batch.id, "status": "committed", "already_committed": True,
                "dataset_id": batch.dataset_id, "dataset_version": batch.resulting_dataset_version,
                "rows_accepted": batch.rows_accepted, "rows_rejected": batch.rows_rejected}
    if batch.report.get("mapping_error"):
        raise ApiError("mapping_incomplete", "Сопоставление колонок не завершено", 422, batch.report["mapping_error"])
    if batch.dataset_id:
        dup = session.scalar(select(m.ImportBatch).where(
            m.ImportBatch.dataset_id == batch.dataset_id, m.ImportBatch.file_sha256 == batch.file_sha256,
            m.ImportBatch.status == "committed", m.ImportBatch.id != batch.id))
        if dup:
            raise ApiError("duplicate_import", "Этот файл уже загружен в набор", 409, {"batch_id": dup.id})
    # Atomic state transition: only one caller can move validated -> committing.
    res = session.execute(update(m.ImportBatch).where(m.ImportBatch.id == batch.id, m.ImportBatch.status == "validated")
                          .values(status="committing"))
    session.commit()
    if res.rowcount != 1:
        session.refresh(batch)
        if batch.status == "committed":
            return commit_batch(session, org_id, batch_id, user_id)
        raise ApiError("import_in_progress", "Импорт уже выполняется", 409, {"status": batch.status})
    try:
        out = _do_commit(session, batch, user_id)
        session.commit()
        return out
    except Exception:
        session.rollback()
        session.execute(update(m.ImportBatch).where(m.ImportBatch.id == batch.id).values(status="failed"))
        session.commit()
        raise


def _do_commit(session: Session, batch: m.ImportBatch, user_id: str | None) -> dict:
    data = Path(batch.storage_path).read_bytes()
    table = read_table(data, batch.filename, batch.sheet)
    dataset = None
    if batch.dataset_id:
        dataset = session.get(m.Dataset, batch.dataset_id)
    else:
        nd = batch.options["new_dataset"]
        dataset = m.Dataset(
            org_id=batch.org_id, program_version_id=nd["program_version_id"], code=f"import-{batch.id[:8]}",
            name_ru=nd["name"], name_kz=nd["name"], is_synthetic=nd["is_synthetic"],
            data_level="grades_only" if batch.kind == "grades" else "item_responses", version=0,
            manifest={"source": "user_import"},
        )
        session.add(dataset)
        session.flush()
        batch.dataset_id = dataset.id
    results, summary = validate_rows(session, dataset, dataset.program_version_id, batch.org_id, table,
                                     batch.column_mapping, batch.kind, batch.options)
    accepted = [r for r in results if not r.errors]
    idx = program_index(session, batch.org_id, dataset.program_version_id)
    ctx = _EntityCache(session, dataset, idx)
    inserted = Counter()
    responses = []
    sittings: dict[tuple[str, str], str] = {}
    for r in accepted:
        v = r.values
        learner = ctx.learner(v)
        if batch.kind == "grades":
            session.add(m.GradeRecord(org_id=dataset.org_id, dataset_id=dataset.id, learner_id=learner.id,
                                      period=v.get("period") or "итог", grade_value=_num(v["grade_value"]),
                                      grade_scale_max=_num(v.get("grade_scale_max") or "5") or 5,
                                      import_batch_id=batch.id))
            inserted["grades"] += 1
            continue
        assessment = ctx.assessment(v)
        if v["_status"] == "absent":
            sittings.setdefault((assessment.id, learner.id), "absent")
            continue
        sittings[(assessment.id, learner.id)] = "present"
        item = idx.items[v["item_code"]]
        responses.append(dict(
            id=new_id(), org_id=dataset.org_id, dataset_id=dataset.id, assessment_id=assessment.id,
            learner_id=learner.id, item_id=item.id, attempt=int(v.get("attempt") or 1), status=v["_status"],
            score=v.get("_score"), response_value=(v.get("response") or None) and v["response"].strip().upper()[:200],
            import_batch_id=batch.id,
        ))
        if v.get("edition_code"):
            ctx.exposure(learner.cohort_id, idx.editions[v["edition_code"]], v)
    session.flush()
    if responses:
        session.bulk_insert_mappings(m.Response, responses)
        inserted["responses"] = len(responses)
    existing_sittings = {(s.assessment_id, s.learner_id): s for s in session.scalars(
        select(m.Sitting).where(m.Sitting.dataset_id == dataset.id))}
    for (a_id, l_id), st in sittings.items():
        cur = existing_sittings.get((a_id, l_id))
        if cur is None:
            session.add(m.Sitting(org_id=dataset.org_id, dataset_id=dataset.id, assessment_id=a_id, learner_id=l_id,
                                  status=st, import_batch_id=batch.id))
            inserted["sittings"] += 1
        elif cur.status == "absent" and st == "present":
            cur.status = "present"
    _update_data_level(session, dataset, batch.kind)
    version = bump_dataset_version(session, dataset, f"import:{batch.filename}", batch.id)
    batch.status = "committed"
    batch.committed_at = utcnow()
    batch.resulting_dataset_version = version
    batch.rows_total = summary["rows_total"]
    batch.rows_accepted = summary["rows_accepted"]
    batch.rows_rejected = summary["rows_rejected"]
    batch.report = {**batch.report, **{k: summary[k] for k in ("rows_total", "rows_accepted", "rows_rejected",
                                                                   "errors_by_code", "rejected_rows")},
                    "inserted": dict(inserted)}
    audit(session, dataset.org_id, user_id, "import.commit", "import_batch", batch.id, dataset_id=dataset.id,
          dataset_version=version, inserted=dict(inserted), rejected=summary["rows_rejected"])
    return {"batch_id": batch.id, "status": "committed", "already_committed": False, "dataset_id": dataset.id,
            "dataset_version": version, "rows_accepted": summary["rows_accepted"],
            "rows_rejected": summary["rows_rejected"], "inserted": dict(inserted)}


def _update_data_level(session: Session, dataset: m.Dataset, kind: str) -> None:
    if kind == "grades" and dataset.data_level == "grades_only":
        return
    stages = {a.stage for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == dataset.id))}
    has_exposure = session.scalar(select(m.MaterialExposure.id).where(m.MaterialExposure.dataset_id == dataset.id).limit(1))
    if "pre" in stages and "post" in stages and has_exposure:
        dataset.data_level = "pre_post_with_exposure"
    elif stages:
        dataset.data_level = "item_responses"


class _EntityCache:
    def __init__(self, session: Session, dataset: m.Dataset, idx: ProgramIndex):
        self.s = session
        self.ds = dataset
        self.idx = idx
        self.schools = {x.code: x for x in session.scalars(select(m.School).where(m.School.dataset_id == dataset.id))}
        self.teachers = {x.code: x for x in session.scalars(select(m.Teacher).where(m.Teacher.dataset_id == dataset.id))}
        self.cohorts = {x.code: x for x in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == dataset.id))}
        self.learners = {x.code: x for x in session.scalars(select(m.Learner).where(m.Learner.dataset_id == dataset.id))}
        self.assessments = {x.code: x for x in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == dataset.id))}
        self.exposures = {(x.cohort_id, x.topic_id) for x in session.scalars(
            select(m.MaterialExposure).where(m.MaterialExposure.dataset_id == dataset.id))}
        pv = session.get(m.ProgramVersion, dataset.program_version_id)
        self.grade = pv.grade if pv else 6

    def _add(self, obj):
        self.s.add(obj)
        return obj

    def cohort(self, v: dict) -> m.Cohort:
        code = v["class_code"]
        if code in self.cohorts:
            return self.cohorts[code]
        sc = v["school_code"]
        school = self.schools.get(sc) or self._add(m.School(org_id=self.ds.org_id, dataset_id=self.ds.id, code=sc, name=sc))
        self.schools[sc] = school
        teacher = None
        if v.get("teacher_code"):
            tc = v["teacher_code"]
            teacher = self.teachers.get(tc) or self._add(m.Teacher(org_id=self.ds.org_id, dataset_id=self.ds.id, code=tc))
            self.teachers[tc] = teacher
        self.s.flush()
        c = self._add(m.Cohort(org_id=self.ds.org_id, dataset_id=self.ds.id, school_id=school.id,
                               teacher_id=teacher.id if teacher else None, code=code,
                               grade=int(v.get("grade") or self.grade), language=v.get("language") or "ru",
                               academic_year=v.get("academic_year") or ""))
        self.cohorts[code] = c
        self.s.flush()
        return c

    def learner(self, v: dict) -> m.Learner:
        code = v["learner_code"]
        if code in self.learners:
            return self.learners[code]
        c = self.cohort(v)
        lr = self._add(m.Learner(org_id=self.ds.org_id, dataset_id=self.ds.id, cohort_id=c.id, code=code))
        self.learners[code] = lr
        self.s.flush()
        return lr

    def assessment(self, v: dict) -> m.Assessment:
        code = v["assessment_code"]
        if code in self.assessments:
            return self.assessments[code]
        form = self.idx.forms[v["_form_code"]]
        d = None
        if v.get("date"):
            try:
                d = date.fromisoformat(v["date"][:10])
            except ValueError:
                d = None
        a = self._add(m.Assessment(org_id=self.ds.org_id, dataset_id=self.ds.id, form_id=form.id, code=code,
                                   stage=form.stage_hint, administered_on=d))
        self.assessments[code] = a
        self.s.flush()
        return a

    def exposure(self, cohort_id: str, edition: m.TextbookEdition, v: dict) -> None:
        year = v.get("academic_year") or ""
        try:
            y0 = int(year[:4])
        except ValueError:
            y0 = date.today().year
        for t in self.idx.topics:
            if (cohort_id, t.id) in self.exposures:
                continue
            self.exposures.add((cohort_id, t.id))
            self.s.add(m.MaterialExposure(org_id=self.ds.org_id, dataset_id=self.ds.id, cohort_id=cohort_id,
                                          edition_id=edition.id, topic_id=t.id, period_start=date(y0, 9, 1),
                                          period_end=date(y0 + 1, 5, 31), usage_level="primary"))
