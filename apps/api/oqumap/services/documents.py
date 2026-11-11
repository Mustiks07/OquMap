"""Source documents: safe storage, text extraction into citable fragments, OCR adapter.

* PDF: one or more fragments per physical page; ``page_physical`` is 1-based, ``page_printed`` is the
  page label defined in the PDF (if any). Pages without a text layer require OCR; when no OCR engine is
  configured they are reported, never filled with invented text.
* DOCX: fragments per paragraph with a stable anchor ``para-NNNN``; no page numbers are invented.
* Files are data: nothing inside a document is executed or followed as an instruction.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..errors import ApiError, not_found
from .common import audit, sha256_bytes
from .jobs import enqueue, handler

MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024
FRAGMENT_TARGET_CHARS = 700

PDF_MEDIA = "application/pdf"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sniff_media_type(data: bytes, filename: str) -> str:
    name = filename.lower()
    if data[:5] == b"%PDF-":
        return PDF_MEDIA
    if data[:4] == b"PK\x03\x04" and name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                if "word/document.xml" not in names:
                    raise ApiError("unsupported_file_type", "Это не документ DOCX", 415)
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    raise ApiError("macros_not_allowed", "Документы с макросами не принимаются", 415)
                total = sum(i.file_size for i in z.infolist())
                if total > MAX_DOCX_UNCOMPRESSED:
                    raise ApiError("file_too_large", "Распакованный документ слишком велик", 413)
        except zipfile.BadZipFile:
            raise ApiError("file_unreadable", "Файл повреждён", 422) from None
        return DOCX_MEDIA
    raise ApiError("unsupported_file_type", "Поддерживаются PDF и DOCX", 415, {"filename": filename})


def store_document(session: Session, org_id: str, user_id: str | None, data: bytes, filename: str,
                   edition_id: str | None = None, is_demo: bool = False) -> tuple[m.Document, bool]:
    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise ApiError("file_too_large", "Файл превышает допустимый размер", 413, {"max_bytes": settings.max_upload_bytes})
    media = sniff_media_type(data, filename)
    digest = sha256_bytes(data)
    existing = session.scalar(select(m.Document).where(m.Document.org_id == org_id, m.Document.sha256 == digest))
    if existing is not None:
        return existing, False
    if edition_id:
        ed = session.scalar(select(m.TextbookEdition).where(m.TextbookEdition.id == edition_id,
                                                            m.TextbookEdition.org_id == org_id))
        if ed is None:
            raise not_found("edition", edition_id)
    root = settings.storage_dir / "documents" / org_id
    root.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if media == PDF_MEDIA else ".docx"
    path = root / f"{digest}{ext}"
    path.write_bytes(data)
    version, lineage = 1, None
    if edition_id:
        prev = session.scalar(select(m.Document).where(m.Document.org_id == org_id, m.Document.edition_id == edition_id)
                              .order_by(m.Document.version.desc(), m.Document.created_at.desc()))
        if prev is not None:
            version, lineage = prev.version + 1, prev.lineage_id or prev.id
    doc = m.Document(org_id=org_id, edition_id=edition_id, filename=Path(filename).name[:300], media_type=media,
                     sha256=digest, storage_path=str(path), size_bytes=len(data), version=version, status="queued",
                     is_demo=is_demo, uploaded_by=user_id)
    session.add(doc)
    session.flush()
    doc.lineage_id = lineage or doc.id
    if edition_id:
        ed.document_id = doc.id  # the edition now points to its latest document version
    audit(session, org_id, user_id, "document.upload", "document", doc.id, sha256=digest, filename=doc.filename)
    session.commit()
    return doc, True


def enqueue_extraction(session: Session, doc: m.Document, user_id: str | None) -> m.Job:
    return enqueue(session, doc.org_id, "document_extract", {"document_id": doc.id},
                   idempotency_key=f"extract:{doc.id}:{doc.version}", user_id=user_id)


@handler("document_extract")
def _job_extract(session: Session, job: m.Job) -> dict:
    doc = session.scalar(select(m.Document).where(m.Document.id == job.payload["document_id"],
                                                  m.Document.org_id == job.org_id))
    if doc is None:
        raise not_found("document", job.payload["document_id"])
    return extract_document(session, doc)


def extract_document(session: Session, doc: m.Document) -> dict:
    doc.status = "processing"
    session.commit()
    data = Path(doc.storage_path).read_bytes()
    try:
        if doc.media_type == PDF_MEDIA:
            frags, report = _extract_pdf(data)
        else:
            frags, report = _extract_docx(data)
    except ApiError:
        doc.status = "failed"
        session.commit()
        raise
    except Exception as exc:  # corrupted file
        doc.status = "failed"
        doc.extraction_report = {"error": "file_unreadable", "type": type(exc).__name__}
        session.commit()
        raise ApiError("file_unreadable", "Не удалось извлечь текст: файл повреждён", 422) from None
    existing = {f.anchor for f in session.scalars(select(m.ContentFragment).where(
        m.ContentFragment.document_id == doc.id, m.ContentFragment.document_version == doc.version))}
    for i, f in enumerate(frags):
        if f["anchor"] in existing:
            continue
        session.add(m.ContentFragment(org_id=doc.org_id, document_id=doc.id, document_version=doc.version,
                                      anchor=f["anchor"], page_physical=f.get("page_physical"),
                                      page_printed=f.get("page_printed"), heading=f.get("heading"),
                                      text=f["text"], text_sha256=sha256_bytes(f["text"].encode()), order_index=i))
    doc.page_count = report.get("page_count")
    doc.ocr_status = report.get("ocr_status", "not_needed")
    doc.extraction_report = report
    doc.status = "ready"
    session.commit()
    return {"document_id": doc.id, "fragments": len(frags), **report}


def _chunks(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=(?:§|Пример|Упражнение|Задача|Правило|Модель|Обсуждение)\b)", text) if p.strip()]
    out: list[str] = []
    for p in paras:
        p = re.sub(r"\s*\n\s*", " ", p)
        while len(p) > FRAGMENT_TARGET_CHARS * 1.5:
            cut = p.rfind(". ", 0, FRAGMENT_TARGET_CHARS)
            cut = cut + 1 if cut > 200 else FRAGMENT_TARGET_CHARS
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def _extract_pdf(data: bytes) -> tuple[list[dict], dict]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ApiError("encrypted_document", "Зашифрованный PDF не поддерживается", 422)
    labels = list(reader.page_labels) if reader.page_labels else []
    frags, no_text_pages, ocr_pages = [], [], []
    ocr = OcrAdapter()
    for pi, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        label = labels[pi - 1] if pi - 1 < len(labels) else None
        printed = label if label and label != str(pi) else None
        if not text:
            if ocr.available:
                text = ocr.page_text(data, pi - 1)
                if text:
                    ocr_pages.append(pi)
            if not text:
                no_text_pages.append(pi)
                continue
        heading = _first_heading(text)
        for ci, chunk in enumerate(_chunks(text), start=1):
            frags.append({"anchor": f"p{pi:03d}-c{ci:02d}", "page_physical": pi, "page_printed": printed,
                          "heading": heading, "text": chunk})
    frags, removed = _drop_running_text(frags, len(reader.pages))
    if no_text_pages:
        ocr_status = "unavailable" if not ocr.available else "partial"
    elif ocr_pages:
        ocr_status = "applied"
    else:
        ocr_status = "not_needed"
    return frags, {"page_count": len(reader.pages), "pages_without_text": no_text_pages, "ocr_pages": ocr_pages,
                   "ocr_status": ocr_status, "ocr_engine": ocr.name, "has_page_labels": bool(labels),
                   "running_text_removed": removed}


def _drop_running_text(frags: list[dict], pages: int) -> tuple[list[dict], list[str]]:
    """Remove running headers/footers: identical text (ignoring digits) repeated on most pages."""
    if pages < 3:
        return frags, []
    norm = lambda t: re.sub(r"\d+", "#", t.strip().lower())  # noqa: E731
    pages_with: dict[str, set[int]] = {}
    for f in frags:
        pages_with.setdefault(norm(f["text"]), set()).add(f["page_physical"])
    running = {k for k, v in pages_with.items() if len(v) >= max(3, pages * 0.6) and len(k) < 200}
    kept = [f for f in frags if norm(f["text"]) not in running]
    # re-number chunk anchors per page to keep them dense and stable
    counters: dict[int, int] = {}
    for f in kept:
        counters[f["page_physical"]] = counters.get(f["page_physical"], 0) + 1
        f["anchor"] = f"p{f['page_physical']:03d}-c{counters[f['page_physical']]:02d}"
    first_by_page: dict[int, str] = {}
    for f in kept:
        first_by_page.setdefault(f["page_physical"], f["text"])
    for f in kept:
        first = first_by_page[f["page_physical"]]
        f["heading"] = first[:300] if len(first) <= 120 else None
    return kept, sorted(running)


def _first_heading(text: str) -> str | None:
    first = text.strip().split("\n", 1)[0].strip()
    return first[:300] if 0 < len(first) <= 120 else None


def _extract_docx(data: bytes) -> tuple[list[dict], dict]:
    import docx

    d = docx.Document(io.BytesIO(data))
    frags = []
    heading = None
    for i, p in enumerate(d.paragraphs):
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name if p.style is not None else "") or ""
        if style.lower().startswith(("heading", "заголовок", "title")):
            heading = text[:300]
        frags.append({"anchor": f"para-{i:04d}", "page_physical": None, "page_printed": None, "heading": heading,
                      "text": text})
    for ti, table in enumerate(d.tables):
        cells = " | ".join(c.text.strip() for row in table.rows for c in row.cells if c.text.strip())
        if cells:
            frags.append({"anchor": f"table-{ti:03d}", "page_physical": None, "page_printed": None,
                          "heading": heading, "text": cells})
    return frags, {"page_count": None, "ocr_status": "not_needed", "paragraphs": len(d.paragraphs),
                   "page_numbers": "not_available_for_docx"}


class OcrAdapter:
    """OCR through an external engine. Only 'tesseract' is supported; absent engine => unavailable."""

    def __init__(self):
        engine = get_settings().ocr_engine
        self.name = engine
        self.binary = shutil.which("tesseract") if engine == "tesseract" else None
        self.available = self.binary is not None

    def page_text(self, pdf_bytes: bytes, page_index: int) -> str:
        if not self.available:
            return ""
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(pdf_bytes)
        img = pdf[page_index].render(scale=2).to_pil()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "page.png"
            img.save(p)
            try:
                out = subprocess.run([self.binary, str(p), "stdout", "-l", "rus+kaz+eng"], capture_output=True,
                                     timeout=60, check=False)
            except subprocess.TimeoutExpired:
                return ""
        return out.stdout.decode("utf-8", "ignore").strip()


def source_payload(session: Session, org_id: str, fragment_id: str) -> dict:
    """Resolve a citation. Only fragments of the caller's organisation are returned."""
    frag = session.scalar(select(m.ContentFragment).where(m.ContentFragment.id == fragment_id,
                                                          m.ContentFragment.org_id == org_id))
    if frag is None:
        raise not_found("source", fragment_id)
    doc = session.get(m.Document, frag.document_id)
    edition = session.get(m.TextbookEdition, doc.edition_id) if doc.edition_id else None
    neighbours = list(session.scalars(select(m.ContentFragment).where(
        m.ContentFragment.document_id == doc.id, m.ContentFragment.document_version == frag.document_version,
        m.ContentFragment.order_index.between(frag.order_index - 1, frag.order_index + 1)).order_by(m.ContentFragment.order_index)))
    return {
        "source_id": frag.id,
        "document_id": doc.id,
        "document_filename": doc.filename,
        "document_version": frag.document_version,
        "document_sha256": doc.sha256,
        "media_type": doc.media_type,
        "is_demo": doc.is_demo,
        "edition": {"id": edition.id, "code": edition.code, "title": edition.title} if edition else None,
        "anchor": frag.anchor,
        "page_physical": frag.page_physical,
        "page_printed": frag.page_printed,
        "heading": frag.heading,
        "text": frag.text,
        "text_sha256": frag.text_sha256,
        "context": [{"source_id": n.id, "anchor": n.anchor, "text": n.text} for n in neighbours if n.id != frag.id],
    }
