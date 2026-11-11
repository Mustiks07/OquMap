"""Decision report export. Everything is rendered from the decision snapshot (and recorded follow-ups), so
numbers, filters and versions match the analysis snapshot shown on screen.

* PDF: human-readable report (reportlab, embedded DejaVu font for Cyrillic/Kazakh).
* CSV / XLSX: tabular results; any cell starting with = + - @ tab or CR is prefixed with an apostrophe so no
  user text becomes an executable formula.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .messages import COMPARABILITY, INFERENCE

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    if isinstance(v, str) and v.startswith(FORMULA_PREFIXES):
        return "'" + v
    return v


def pct(x, digits=1):
    return "—" if x is None else f"{100 * x:.{digits}f}%".replace(".", ",")


def pp(x, digits=1):
    return "—" if x is None else (f"{100 * x:+.{digits}f}".replace(".", ",") + " п.п.")


def rows_for_tables(dec: dict) -> list[list]:
    """Long table: section, metric, group, value, unit, note."""
    s = dec["snapshot"]
    rows: list[list] = [["section", "metric", "group", "value", "unit", "note"]]
    rows.append(["context", "decision_id", "", dec["id"], "", f"version {dec['version']} / {dec['status']}"])
    rows.append(["context", "dataset", "", s["dataset"]["name_ru"], "", f"version {s['dataset']['version']}"])
    rows.append(["context", "is_synthetic", "", str(s["dataset"]["is_synthetic"]).lower(), "", ""])
    for k, v in s["filters"].items():
        rows.append(["filters", k, "", ",".join(v) if isinstance(v, list) else ("" if v is None else str(v)), "", ""])
    for a in s["analyses"]:
        rows.append(["analysis", a["kind"], "", a["analysis_id"], "", f"dataset_version={a['dataset_version']}; method={a['method_version']}"])
    t = s.get("topic")
    if t:
        sm = t.get("summary") or {}
        rows.append(["topic", "mean_score_share", t["code"], sm.get("mean"), "share", t["status"]])
        rows.append(["topic", "ci_low", t["code"], sm.get("ci_low"), "share", sm.get("ci_method") or sm.get("ci_unavailable_reason")])
        rows.append(["topic", "ci_high", t["code"], sm.get("ci_high"), "share", ""])
        for k in ("n_learners", "n_classes", "n_schools"):
            rows.append(["topic", k, t["code"], sm.get(k), "count", ""])
        for o in t["objectives"]:
            rows.append(["objective", "mean_score_share", o["code"], o["mean"], "share", o["status"]])
        for it in t["items"]:
            rows.append(["item", "p_correct", it["code"], it["p_correct"], "share", f"answered={it['n_answered']}; omitted={it['n_omitted']}"])
        for mc in t["misconceptions"]:
            rows.append(["misconception", "share_of_learners", mc["code"], mc["share_of_learners"], "share", mc["label_ru"]])
        for k, v in t["exclusions"].items():
            rows.append(["exclusions", k, t["code"], v, "count", ""])
    c = s.get("comparison")
    if c:
        ea, eb = c["editions"]["a"]["code"], c["editions"]["b"]["code"]
        rows.append(["comparison", "status", "", c["status"], "", c["inference_level"]])
        rows.append(["comparison", "raw_mean", ea, c["raw"]["a"]["mean"], "share", f"n={c['raw']['a']['n_learners']}"])
        rows.append(["comparison", "raw_mean", eb, c["raw"]["b"]["mean"], "share", f"n={c['raw']['b']['n_learners']}"])
        rows.append(["comparison", "adjusted_mean", ea, c["adjusted"]["a"], "share", c["adjusted"]["weight_mode"]])
        rows.append(["comparison", "adjusted_mean", eb, c["adjusted"]["b"], "share", c["adjusted"]["weight_mode"]])
        rows.append(["comparison", "adjusted_difference_b_minus_a", "", c["adjusted"]["difference"], "share_points", ""])
        ci = c["uncertainty"]["adjusted_difference_ci"] or {}
        rows.append(["comparison", "ci_low", "", ci.get("low"), "share_points", c["uncertainty"].get("unavailable_reason") or c["uncertainty"]["cluster_unit"]])
        rows.append(["comparison", "ci_high", "", ci.get("high"), "share_points", ""])
        for st in c["adjusted"]["strata"]:
            rows.append(["stratum", "weight", st["stratum"], st["weight"], "share", ""])
            rows.append(["stratum", "mean", f"{st['stratum']}:{ea}", st["mean_a"], "share", f"n={st['n_a']}"])
            rows.append(["stratum", "mean", f"{st['stratum']}:{eb}", st["mean_b"], "share", f"n={st['n_b']}"])
        for r in c["reasons"]:
            rows.append(["comparison_reason", r["code"], r["severity"], "", "", r["message_ru"]])
    pl = s.get("plan")
    if pl:
        rows.append(["plan", "status", pl["preset"], pl["status"], "", ""])
        for ch in pl["changes"]:
            rows.append(["plan", "hours_before", ch["code"], ch["before"], "hours", ""])
            rows.append(["plan", "hours_after", ch["code"], ch["after"], "hours", f"delta={ch['delta']:+d}"])
        rows.append(["plan", "total", "", pl["total_after"], "hours", f"before={pl['total_before']}"])
    for src in s.get("sources", []):
        rows.append(["source", "citation", (src.get("edition") or {}).get("code", ""), src["source_id"], "",
                     f"{src['document_filename']} v{src['document_version']} {('p.' + src['page_printed']) if src['page_printed'] else src['anchor']}"])
    for fu in dec.get("follow_ups", []):
        r = fu["result"] or {}
        tg = r.get("target") or {}
        rows.append(["follow_up", "status", fu["id"], fu["status"], "", r.get("interpretation_level", "")])
        rows.append(["follow_up", "adjusted_change", "target", tg.get("adjusted_change"), "share_points", ""])
        if tg.get("ci"):
            rows.append(["follow_up", "ci_low", "target", tg["ci"]["low"], "share_points", ""])
            rows.append(["follow_up", "ci_high", "target", tg["ci"]["high"], "share_points", ""])
    for lim in s.get("limitations", []):
        rows.append(["limitation", "", "", "", "", lim])
    return rows


def to_csv(dec: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in rows_for_tables(dec):
        w.writerow([safe_cell("" if v is None else v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(dec: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    for i, row in enumerate(rows_for_tables(dec)):
        cells = []
        for v in row:
            v = safe_cell(v)
            cells.append(v)
        ws.append(cells)
        if i == 0:
            for c in ws[1]:
                c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, str):
                c.data_type = "s"  # force text type; never a formula
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 40
    ws.column_dimensions["F"].width = 80
    info = wb.create_sheet("about")
    info.append(["OquMap — экспорт решения"])
    info.append(["Синтетические данные" if dec["snapshot"]["dataset"]["is_synthetic"] else "Данные организации"])
    info.append(["Доли указаны от 0 до 1; разницы — в долях (×100 = п.п.)."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(dec: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    try:
        pdfmetrics.getFont("OquSans")
    except KeyError:
        pdfmetrics.registerFont(TTFont("OquSans", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("OquSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    s = dec["snapshot"]
    base = ParagraphStyle("base", fontName="OquSans", fontSize=9.5, leading=13, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=colors.HexColor("#4a5568"))
    h1 = ParagraphStyle("h1", parent=base, fontName="OquSans-Bold", fontSize=16, leading=20, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=base, fontName="OquSans-Bold", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#1a365d"))
    warn = ParagraphStyle("warn", parent=base, backColor=colors.HexColor("#fff4e5"), borderPadding=5,
                          textColor=colors.HexColor("#7b341e"))

    def P(text, style=base):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    def table(data, widths=None):
        t = Table([[P(c, small) if not isinstance(c, Paragraph) else c for c in row] for row in data], colWidths=widths,
                  repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    story = []
    story.append(P("Карточка методического решения", h1))
    story.append(P(f"Версия {dec['version']} · статус: {_status_ru(dec['status'])} · ID {dec['id']}", small))
    if s["dataset"]["is_synthetic"]:
        story.append(Spacer(1, 4))
        story.append(P("СИНТЕТИЧЕСКИЕ ДАННЫЕ. Демонстрационный набор: ученики, классы, школы и пособия вымышлены; "
                       "показатели не описывают реальные школы и не являются результатом пилота.", warn))
    story.append(Spacer(1, 6))
    story.append(table([
        ["Набор данных", s["dataset"]["name_ru"]],
        ["Версия данных", str(s["dataset"]["version"])],
        ["Целевая группа", dec["target_group"]],
        ["Фильтры", _filters_text(s["filters"])],
        ["Ответственный", dec["responsible"]],
        ["Повторная проверка", (dec["follow_up_date"] or "—") + (f" · критерий: {dec['follow_up_criterion']}" if dec["follow_up_criterion"] else "")],
        ["Утверждение", (f"{dec['approved_by']} · {dec['approved_at'][:16].replace('T', ' ')} UTC" if dec["approved_at"] else "не утверждено")],
    ], [42 * mm, 128 * mm]))

    story.append(P("Проблема", h2))
    story.append(P(dec["problem"]))
    t = s.get("topic")
    if t:
        sm = t.get("summary") or {}
        story.append(P("Показатели темы", h2))
        ci = f"{pct(sm.get('ci_low'))} – {pct(sm.get('ci_high'))}" if sm.get("ci_low") is not None else (sm.get("ci_unavailable_reason") or "—")
        story.append(table([
            ["Тема", "Средняя доля баллов", "95% интервал", "Учеников", "Классов", "Школ"],
            [f"{t['code']} {t['title_ru']}", pct(sm.get("mean")), ci, sm.get("n_learners"), sm.get("n_classes"), sm.get("n_schools")],
        ], [52 * mm, 26 * mm, 30 * mm, 22 * mm, 20 * mm, 20 * mm]))
        story.append(Spacer(1, 4))
        story.append(table([["Цель", "Формулировка", "Доля баллов", "Статус"]] +
                           [[o["code"], o["text_ru"], pct(o["mean"]), _objective_status(o["status"])] for o in t["objectives"]],
                           [28 * mm, 92 * mm, 24 * mm, 26 * mm]))
        if t["misconceptions"]:
            story.append(Spacer(1, 4))
            story.append(table([["Возможная ошибка (гипотеза)", "Учеников (≥1 выбор)", "Доля учеников", "Задания"]] +
                               [[mc["label_ru"], mc["n_learners"], pct(mc["share_of_learners"]), ", ".join(mc["items"])]
                                for mc in t["misconceptions"]], [96 * mm, 20 * mm, 20 * mm, 34 * mm]))
        ex = t["exclusions"]
        story.append(P(f"Исключения: отсутствовали на проверке — {ex['absent_sittings']}; пропущенных ответов по теме — "
                       f"{ex['omitted_responses']}; учеников с повторными попытками — {ex['learners_with_repeat_attempts']}; "
                       f"отклонённых строк импорта — {ex['rejected_import_rows']}. Правило попыток: {t['rules']['attempt_rule']}; "
                       f"пропуск: {t['rules']['omitted_policy']}; агрегация: {t['rules']['aggregation']}.", small))
    c = s.get("comparison")
    if c:
        ea, eb = c["editions"]["a"], c["editions"]["b"]
        story.append(P("Сравнение изданий на сопоставимых группах", h2))
        story.append(P(f"Статус: {COMPARABILITY[c['status']][0]}. Уровень вывода: {INFERENCE[c['inference_level']][0]}. "
                       f"Метод: стандартизация по входному уровню ({c['adjusted']['strata_scheme']}, веса: {c['adjusted']['weight_mode']}); "
                       f"интервал — кластерный бутстрэп по единице «{c['uncertainty']['cluster_unit']}».", base))
        ci = c["uncertainty"]["adjusted_difference_ci"]
        story.append(table([
            ["", ea["code"], eb["code"], f"Разница {eb['code']} − {ea['code']}"],
            ["Исходная доля баллов", pct(c["raw"]["a"]["mean"]), pct(c["raw"]["b"]["mean"]), pp(c["raw"]["difference"])],
            ["Скорректированная", pct(c["adjusted"]["a"]), pct(c["adjusted"]["b"]), pp(c["adjusted"]["difference"])],
            ["95% интервал разницы", "", "", f"{pp(ci['low'])} … {pp(ci['high'])}" if ci else (c["uncertainty"].get("unavailable_reason") or "—")],
            ["Учеников / классов / школ", f"{c['raw']['a']['n_learners']} / {c['raw']['a']['n_classes']} / {c['raw']['a']['n_schools']}",
             f"{c['raw']['b']['n_learners']} / {c['raw']['b']['n_classes']} / {c['raw']['b']['n_schools']}", ""],
        ], [52 * mm, 34 * mm, 34 * mm, 50 * mm]))
        story.append(Spacer(1, 4))
        story.append(table([["Входной уровень", "Вес", f"{ea['code']}: n / доля", f"{eb['code']}: n / доля"]] +
                           [[st["stratum"], pct(st["weight"], 0) if st["weight"] is not None else "—",
                             f"{st['n_a']} / {pct(st['mean_a'])}", f"{st['n_b']} / {pct(st['mean_b'])}"] for st in c["adjusted"]["strata"]],
                           [44 * mm, 24 * mm, 51 * mm, 51 * mm]))
    pl = s.get("plan")
    if pl:
        story.append(P("Изменение часов (план по темам, не календарное расписание)", h2))
        story.append(P(f"Статус решателя: {pl['status_message_ru']}. Сценарий: {pl['preset']}. Сумма часов: "
                       f"{pl['total_before']} → {pl['total_after']} (бюджет {pl['budget']}). Независимая проверка ограничений: "
                       f"{'пройдена' if pl['validation']['valid'] else 'НЕ пройдена'}.", base))
        story.append(table([["Тема", "Было", "Стало", "Изменение", "Приоритет"]] +
                           [[f"{ch['code']} {ch['title']}".strip(), ch["before"], ch["after"], f"{ch['delta']:+d}", f"{ch['priority']:.2f}"]
                            for ch in pl["changes"]], [80 * mm, 20 * mm, 20 * mm, 25 * mm, 25 * mm]))
        story.append(P(f"Целевая функция: {pl['objective']['formula']}; λ = {pl['objective']['change_penalty']}, r = "
                       f"{pl['objective']['diminishing_rate']}. Это распределение педагогического приоритета, не прогноз баллов.", small))
    story.append(P("Гипотеза", h2))
    story.append(P(dec["hypothesis"]))
    story.append(P("Действие", h2))
    story.append(P(dec["action"]))
    if s.get("sources"):
        story.append(P("Источники", h2))
        story.append(table([["Издание / документ", "Место", "Фрагмент"]] +
                           [[((src.get("edition") or {}).get("title") or src["document_filename"]) + f" (v{src['document_version']})",
                             (f"с. {src['page_printed']} (физ. {src['page_physical']})" if src["page_printed"] else
                              (f"физ. с. {src['page_physical']}" if src["page_physical"] else f"якорь {src['anchor']}")),
                             src["text"][:400]] for src in s["sources"]], [48 * mm, 30 * mm, 92 * mm]))
    if dec.get("follow_ups"):
        story.append(P("Повторная проверка", h2))
        for fu in dec["follow_ups"]:
            r = fu["result"] or {}
            tg = r.get("target") or {}
            ci = tg.get("ci")
            story.append(P(f"Статус: {fu['status_label_ru']}. До: {pct((tg.get('before') or {}).get('adjusted'))}, после: "
                           f"{pct((tg.get('after') or {}).get('adjusted'))} (стандартизовано); изменение {pp(tg.get('adjusted_change'))}"
                           + (f", 95% интервал {pp(ci['low'])} … {pp(ci['high'])}" if ci else "") + ".", base))
            if r.get("comparison_group"):
                cg = r["comparison_group"]
                story.append(P(f"Группа сравнения: изменение {pp(cg.get('adjusted_change'))}. Разница изменений "
                               f"{pp(r.get('difference_in_changes'))} — описательно.", small))
            story.append(P(r.get("note_ru", ""), small))
    story.append(P("Ограничения вывода", h2))
    for lim in dict.fromkeys(s.get("limitations", [])):
        story.append(P("• " + lim, base))
    story.append(Spacer(1, 6))
    story.append(P("Анализы: " + "; ".join(f"{a['kind']} {a['analysis_id'][:8]} (данные v{a['dataset_version']}, {a['method_version']})"
                                           for a in s["analyses"]), small))

    def on_page(canvas, doc):
        canvas.setFont("OquSans", 7.5)
        canvas.setFillColor(colors.HexColor("#718096"))
        canvas.drawString(18 * mm, 10 * mm, "OquMap · отчёт сформирован из снимка анализа" +
                          (" · СИНТЕТИЧЕСКИЕ ДАННЫЕ" if s["dataset"]["is_synthetic"] else ""))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"стр. {doc.page}")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title="OquMap — карточка решения", author="OquMap")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _status_ru(s):
    return {"draft": "черновик", "approved": "утверждено", "superseded": "заменено новой версией"}.get(s, s)


def _objective_status(s):
    return {"measured": "измерено", "unverified_mapping": "разметка не подтверждена", "not_measured": "не измерялось"}.get(s, s)


def _filters_text(f: dict) -> str:
    parts = [f"попытка: {f['attempt_rule']}", f"пропуск: {f['omitted_policy']}", f"агрегация: {f['aggregation']}",
             f"разметка: {f['mapping_status']}", f"этап: {f['outcome_stage']}"]
    for k in ("school_ids", "cohort_ids", "edition_ids"):
        if f.get(k):
            parts.append(f"{k}: {len(f[k])}")
    if f.get("language"):
        parts.append(f"язык: {f['language']}")
    return "; ".join(parts)
