import json
import pytest
import sqlite3
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from pipeline.code_extractor import (
    CodeAnalyzer,
    flatten_repository_rendergit,
    extract_and_store_code_units,
    init_code_db,
    _looks_binary,
    _ignored_extension,
)

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "rendergit_mini"
FIXTURE_RENDERED = ["bom.py", "crlf.py", "dup_a.py", "dup_b.py", "big.py", "nested/deep/x.py"]
FIXTURE_SKIPPED = {"fake.gguf": "ext", "weights.dat": "sniff"}
from api_server import app

SAMPLE_PYTHON_CODE = '''
import math

class Calculator:
    """
    A simple mathematical calculator class.
    """
    def __init__(self, precision: int = 2):
        self.precision = precision

    def add(self, a: float, b: float) -> float:
        """Returns the sum of a and b."""
        return round(a + b, self.precision)

    async def compute_async(self, values: list) -> float:
        total = 0
        for val in values:
            if val > 0:
                total += math.sqrt(val)
        return total
'''

def test_code_analyzer_ast():
    import ast
    tree = ast.parse(SAMPLE_PYTHON_CODE)
    analyzer = CodeAnalyzer(SAMPLE_PYTHON_CODE, "sample.py")
    analyzer.visit(tree)

    units = analyzer.items
    unit_types = [u["unit_type"] for u in units]
    names = [u["name"] for u in units]

    assert "class" in unit_types
    assert "function" in unit_types
    assert "loop" in unit_types

    assert "Calculator" in names
    assert "add" in names
    assert "compute_async" in names

    add_func = next(u for u in units if u["name"] == "add")
    assert "def add" in add_func["signature"]
    assert "Returns the sum of a and b." in add_func["docstring"]


def test_flatten_repository_rendergit():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "main.py").write_text("print('hello world')", encoding="utf-8")
        sub_dir = tmp_path / "pkg"
        sub_dir.mkdir()
        (sub_dir / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

        out_file = tmp_path / "output_rendergit.md"
        text, parsed_files = flatten_repository_rendergit(tmp_path, output_file=out_file)

        assert "main.py" in text
        assert "pkg" in text
        assert "utils.py" in text
        assert len(parsed_files) == 2
        assert out_file.exists()


def test_extract_and_store_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        py_file = tmp_path / "math_utils.py"
        py_file.write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")

        db_path = tmp_path / "test_code.db"
        units = extract_and_store_code_units(
            parsed_files=[py_file],
            repo_dir=tmp_path,
            db_path=db_path,
            project_id="test_proj"
        )

        assert len(units) >= 3

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM code_units WHERE project_id = 'test_proj'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == len(units)


@pytest.mark.asyncio
async def test_api_code_endpoints():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            py_file = tmp_path / "app.py"
            py_file.write_text("def sample_func(x):\n    return x * 2\n", encoding="utf-8")

            payload = {
                "repo_url": str(tmp_path),
                "project_id": "api_test_project",
                "extract_ast": True
            }

            response = await client.post("/api/code/clone-and-extract", json=payload)
            assert response.status_code == 200
            res_data = response.json()
            assert res_data["status"] == "success"
            assert res_data["project_id"] == "api_test_project"
            assert res_data["extracted_code_units_count"] >= 1

            # Test GET /api/code/units
            response_units = await client.get("/api/code/units?project_id=api_test_project")
            assert response_units.status_code == 200
            units_data = response_units.json()
            assert units_data["total"] >= 1
            assert units_data["units"][0]["name"] == "sample_func"


def test_clean_persona_intros():
    from pipeline.dataset_builder import DatasetBuilder
    sample_text = (
        "As a Senior Principal Software Architect and Static Analyzer, here is the analysis:\n"
        "--- \n"
        "### Purpose\nThe class is a data container.\n"
    )
    cleaned = DatasetBuilder.clean_persona_intros(sample_text)
    assert not cleaned.startswith("As a Senior Principal Software Architect")
    assert cleaned.startswith("### Purpose")

    tr_sample = (
        "İşte LineNumbers sınıfının kapsamlı mimari analizini sunan belge:\n"
        "### Özet\nLineNumbers sınıfı özel bir widget'tır.\n"
    )
    tr_cleaned = DatasetBuilder.clean_persona_intros(tr_sample)
    assert not tr_cleaned.startswith("İşte LineNumbers")
    assert tr_cleaned.startswith("### Özet")





# ---------------------------------------------------------------------------
# S1 — ikili dosya kör noktası (fixture: tests/fixtures/rendergit_mini)
# ---------------------------------------------------------------------------

def _run_fixture(tmp_path: Path, name: str = "exports/mini_rendergit.md"):
    out = tmp_path / name
    text, parsed = flatten_repository_rendergit(FIXTURE_REPO, output_file=out, v2=True)
    return out, text, parsed


def test_v2_fixture_skipped_jsonl(tmp_path):
    out, text, _ = _run_fixture(tmp_path)
    skipped_file = out.parent / "mini_skipped.jsonl"
    assert skipped_file.exists()
    lines = [json.loads(line) for line in skipped_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2

    reasons = {Path(entry["path"]).as_posix(): entry["reason"] for entry in lines}
    assert reasons == FIXTURE_SKIPPED
    for entry in lines:
        assert set(entry) == {"path", "reason", "bytes"}
        assert entry["bytes"] == (FIXTURE_REPO / entry["path"]).stat().st_size

    # atlanan dosyanın içeriği ve adı çıktıya sızmıyor
    assert "fake.gguf" not in text
    assert "weights.dat" not in text
    assert "GGUF" not in text


def test_v2_fixture_coverage_counts(tmp_path):
    out, _, _ = _run_fixture(tmp_path)
    coverage = json.loads((out.parent / "mini_coverage.json").read_text(encoding="utf-8"))

    assert coverage["files_skipped"] == 2
    assert coverage["files_rendered"] == 6
    assert coverage["files_total"] == coverage["files_rendered"] + coverage["files_skipped"] == 8
    assert coverage["by_reason"] == {"ext": 1, "sniff": 1, "unreadable": 0}
    assert coverage["by_ext"] == {".gguf": 1, ".dat": 1}

    expected_skipped_bytes = sum((FIXTURE_REPO / p).stat().st_size for p in FIXTURE_SKIPPED)
    expected_rendered_bytes = sum((FIXTURE_REPO / p).stat().st_size for p in FIXTURE_RENDERED)
    assert coverage["bytes_skipped"] == expected_skipped_bytes
    assert coverage["bytes_rendered"] == expected_rendered_bytes


def test_v2_fixture_renders_expected_files(tmp_path):
    out, text, parsed = _run_fixture(tmp_path)
    rendered = {p.relative_to(FIXTURE_REPO).as_posix() for p in parsed}
    assert rendered == set(FIXTURE_RENDERED)

    for rel in FIXTURE_RENDERED:
        assert rel in text
    # yoksayılan dizinler ağaca da içeriğe de girmiyor
    assert "node_modules" not in text
    assert "junk.js" not in text
    assert ".hidden" not in text


def test_looks_binary_sniff():
    assert _looks_binary(FIXTURE_REPO / "weights.dat") is True        # NUL yoğun
    assert _looks_binary(FIXTURE_REPO / "fake.gguf") is True          # çözülemeyen UTF-8
    assert _looks_binary(FIXTURE_REPO / "bom.py") is False            # BOM'lu ama metin
    assert _looks_binary(FIXTURE_REPO / "big.py") is False            # 600 KB metin

    with tempfile.TemporaryDirectory() as tmpdir:
        empty = Path(tmpdir) / "empty.txt"
        empty.write_bytes(b"")
        assert _looks_binary(empty) is False


def test_ignored_extension_covers_long_suffix_and_new_list():
    assert _ignored_extension(Path("model.gguf")) is True
    assert _ignored_extension(Path("weights.safetensors")) is True
    assert _ignored_extension(Path("audio.ogg")) is True
    assert _ignored_extension(Path("libfoo.so.1")) is True            # çok ekli giriş
    assert _ignored_extension(Path("app.wasm")) is True
    assert _ignored_extension(Path("mod.py")) is False
    assert _ignored_extension(Path("README.md")) is False


def test_v2_parity_on_text_only_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "utils.py").write_text("def h(): pass\n", encoding="utf-8")

        legacy_text, legacy_files = flatten_repository_rendergit(tmp_path)
        v2_text, v2_files = flatten_repository_rendergit(tmp_path, v2=True)

        assert v2_text == legacy_text
        assert [p.name for p in v2_files] == [p.name for p in legacy_files]


def test_legacy_path_keeps_extension_gate_without_sniff(tmp_path):
    # Uzantı listesi ortak hızlı yol; sniff + yan dosyalar yalnız v2'de
    out = tmp_path / "legacy_rendergit.md"
    text, parsed = flatten_repository_rendergit(FIXTURE_REPO, output_file=out)

    rendered = {p.relative_to(FIXTURE_REPO).as_posix() for p in parsed}
    assert "fake.gguf" not in rendered
    assert "weights.dat" in rendered          # sniff v2'ye özgü
    assert "fake.gguf" not in text
    assert not (tmp_path / "legacy_skipped.jsonl").exists()
    assert not (tmp_path / "legacy_coverage.json").exists()


def test_v2_sidecar_project_id_from_output_file(tmp_path):
    out, _, _ = _run_fixture(tmp_path, name="exports/projem-1_rendergit.md")
    assert (tmp_path / "exports" / "projem-1_skipped.jsonl").exists()
    assert (tmp_path / "exports" / "projem-1_coverage.json").exists()
    assert out.name == "projem-1_rendergit.md"


def test_v2_sidecar_fallback_without_output_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text, parsed = flatten_repository_rendergit(FIXTURE_REPO, v2=True)

    assert "fake.gguf" not in text
    assert (tmp_path / "exports" / "rendergit_mini_skipped.jsonl").exists()
    assert (tmp_path / "exports" / "rendergit_mini_coverage.json").exists()
