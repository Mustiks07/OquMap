"""Import guarantees: row report, no zeros for invalid rows, idempotent commit, duplicate-file protection,
grades-only limitations, XLSX sheets and formula safety."""

import io
from pathlib import Path

from conftest import login
from openpyxl import Workbook

REPO = Path(__file__).resolve().parents[3]
SAMPLE = REPO / "data/demo/imports/upload_sample_with_errors.csv"


def _validate(c, H, data, name="sample.csv", **form):
    r = c.post("/api/v1/imports/validate", files={"file": (name, data, "text/csv")}, data=form, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_row_report_and_partial_commit(fresh_client):
    c = fresh_client
    H = login(c)
    v = _validate(c, H, SAMPLE.read_bytes(), new_dataset_name="Тестовая загрузка", is_synthetic="true")
    rep = v["report"]
    assert v["rows_rejected"] == 10
    expected = {"unknown_item", "score_out_of_range", "invalid_number", "missing_required", "invalid_status",
                "duplicate_row", "item_not_in_form", "learner_class_conflict", "invalid_code", "score_with_omitted"}
    assert expected <= set(rep["errors_by_code"])
    assert all("row_number" in r for r in rep["rejected_rows"])
    job = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=H).json()
    assert job["status"] == "succeeded", job
    res = job["result"]
    assert res["rows_rejected"] == 10
    # rejected rows were not inserted: the response count equals the accepted non-absent rows
    accepted_rows = v["rows_accepted"]
    absent = v["report"]["status_counts"].get("absent", 0)
    assert res["inserted"]["responses"] == accepted_rows - absent

    # idempotency: committing the same batch again inserts nothing
    again = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=H).json()
    assert again["id"] == job["id"]
    b = c.get(f"/api/v1/imports/{v['id']}", headers=H).json()
    assert b["status"] == "committed" and b["transform_version"] == "import-v1" and len(b["file_sha256"]) == 64

    # same file into the same dataset is detected and refused
    ds_id = res["dataset_id"]
    v2 = _validate(c, H, SAMPLE.read_bytes(), dataset_id=ds_id)
    assert v2["report"]["duplicate_of_batch"] == v["id"]
    r = c.post("/api/v1/imports/commit", json={"batch_id": v2["id"], "wait": True}, headers=H).json()
    assert r["status"] == "failed" and r["error"]["code"] == "duplicate_import"
    q = c.get(f"/api/v1/datasets/{ds_id}/quality", headers=H).json()
    assert q["dataset"]["version"] == 1
    assert sum(a["n_responses"] for a in q["assessments"]) == res["inserted"]["responses"]


def test_demo_org_rejects_non_synthetic_upload(fresh_client):
    c = fresh_client
    H = login(c)
    r = c.post("/api/v1/imports/validate", files={"file": ("x.csv", SAMPLE.read_bytes(), "text/csv")},
               data={"new_dataset_name": "real"}, headers=H)
    # the route marks uploads in a demo org as synthetic; the service-level guard is tested below
    assert r.status_code == 200 and r.json()["is_synthetic"] is True
    from oqumap import db
    from oqumap import models as m
    from oqumap.errors import ApiError
    from oqumap.services import imports

    with db.session_factory()() as s:
        org = s.query(m.Organization).filter_by(is_demo=True).first()
        try:
            imports.validate_upload(s, org=org, user_id=None, data=SAMPLE.read_bytes(), filename="x.csv", kind="responses",
                                    dataset_id=None, new_dataset={"name": "real", "is_synthetic": False}, sheet=None,
                                    mapping=None, options=None)
            raise AssertionError("expected demo_requires_synthetic")
        except ApiError as e:
            assert e.code == "demo_requires_synthetic"


def test_grades_only_import_explains_missing_fields(fresh_client):
    c = fresh_client
    H = login(c)
    data = (REPO / "data/demo/imports/grades_only_sample.csv").read_bytes()
    v = _validate(c, H, data, name="grades.csv", kind="grades", new_dataset_name="Оценки")
    assert v["rows_rejected"] == 0
    av = v["report"]["available_analysis"]
    assert av["level"] == "grades_only" and "topic_diagnostics" in av["not_possible"] and "item_code" in av["missing_fields"]
    job = c.post("/api/v1/imports/commit", json={"batch_id": v["id"], "wait": True}, headers=H).json()
    q = c.get(f"/api/v1/datasets/{job['result']['dataset_id']}/quality", headers=H).json()
    assert q["data_level"] == "grades_only" and "item_level_responses" in q["capabilities"]["missing"]


def test_xlsx_sheet_selection_and_mapping(fresh_client):
    c = fresh_client
    H = login(c)
    wb = Workbook()
    wb.active.title = "Инструкция"
    wb.active.append(["Этот лист не содержит данных"])
    ws = wb.create_sheet("Ответы")
    ws.append(["Ученик", "Класс", "Школа", "Тест", "Форма", "Задание", "Балл"])
    ws.append(["X1", "X-6А", "X01", "POST-X", "F-POST-1", "I14", 1])
    ws.append(["X2", "X-6А", "X01", "POST-X", "F-POST-1", "I14", "=1+1"])
    buf = io.BytesIO()
    wb.save(buf)
    r = c.post("/api/v1/imports/validate", files={"file": ("a.xlsx", buf.getvalue(), "application/octet-stream")},
               data={"new_dataset_name": "XLSX", "sheet": "Ответы"}, headers=H).json()
    assert r["report"]["sheets"] == ["Инструкция", "Ответы"]
    m = r["column_mapping"]
    assert m["learner_code"] == "Ученик" and m["item_code"] == "Задание" and m["score"] == "Балл"
    assert r["rows_accepted"] == 1 and r["rows_rejected"] == 1  # formula text is not a number, never evaluated


def test_corrupted_xlsx_is_reported(fresh_client):
    c = fresh_client
    H = login(c)
    r = c.post("/api/v1/imports/validate", files={"file": ("bad.xlsx", b"PK\x03\x04garbage", "application/octet-stream")},
               data={"new_dataset_name": "bad"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_unreadable"


def test_xlsx_container_checks_reject_bombs_macros_traversal_and_fake_csv():
    import zipfile

    import pytest

    from oqumap.errors import ApiError
    from oqumap.services import imports

    def zipped(members: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        return buf.getvalue()

    base = {"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<w/>"}
    bomb = zipped({**base, "xl/worksheets/sheet1.xml": b"\0" * (5 * 1024 * 1024)})
    macro = zipped({**base, "xl/worksheets/sheet1.xml": b"<x/>", "xl/vbaProject.bin": b"x"})
    trav = zipped({**base, "xl/worksheets/sheet1.xml": b"<x/>", "../evil.txt": b"x"})
    cases = [(bomb, "file_too_large"), (macro, "macros_not_allowed"), (trav, "file_unreadable"),
             (b"not a zip at all", "unsupported_file_type"), (zipped({"a.txt": b"x"}), "unsupported_file_type")]
    for data, code in cases:
        with pytest.raises(ApiError) as e:
            imports.read_table(data, "upload.xlsx")
        assert e.value.code == code
    with pytest.raises(ApiError) as e:
        imports.read_table(bomb, "renamed.csv")  # binary content behind a .csv name
    assert e.value.code == "unsupported_file_type"


def test_xlsx_row_limit_stops_streaming(monkeypatch):
    import pytest

    from oqumap.config import get_settings
    from oqumap.errors import ApiError
    from oqumap.services import imports

    monkeypatch.setattr(get_settings(), "max_import_rows", 10)
    wb = Workbook()
    ws = wb.active
    for i in range(2000):
        ws.append([f"L{i}", i])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ApiError) as e:
        imports.read_table(buf.getvalue(), "big.xlsx")
    assert e.value.code == "too_many_rows"
