"""Generated demo artefacts must be byte-identical across runs (and platforms): tracked files stay clean."""

import hashlib
import time

from oqumap.demo import example_project, materials
from oqumap.demo.seed import FONT_DIR


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_docx_generation_is_byte_identical():
    a = materials.build_docx()
    time.sleep(1.1)
    b = materials.build_docx()
    assert sha(a) == sha(b)
    import io
    import zipfile

    for info in zipfile.ZipFile(io.BytesIO(a)).infolist():
        assert info.create_system == 3 and info.date_time == (2026, 1, 1, 0, 0, 0) and info.compress_type == zipfile.ZIP_STORED


def test_pdf_generation_is_byte_identical():
    f, bold = str(FONT_DIR / "DejaVuSans.ttf"), str(FONT_DIR / "DejaVuSans-Bold.ttf")
    a = materials.build_pdf(f, bold)
    time.sleep(1.1)
    assert sha(a) == sha(materials.build_pdf(f, bold))


def test_example_project_is_deterministic():
    assert example_project.build() == example_project.build()


def test_tracked_artefacts_match_generators():
    from oqumap.config import REPO_ROOT

    d = REPO_ROOT / "data" / "demo" / "materials"
    assert (d / "demo_posobie_B.docx").read_bytes() == materials.build_docx()
    f, bold = str(FONT_DIR / "DejaVuSans.ttf"), str(FONT_DIR / "DejaVuSans-Bold.ttf")
    assert (d / "demo_posobie_A.pdf").read_bytes() == materials.build_pdf(f, bold)
    ex = REPO_ROOT / "data" / "templates" / "example_project"
    for name, text in example_project.build().items():
        assert (ex / name).read_bytes() == text.encode("utf-8"), name
