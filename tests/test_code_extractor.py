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

        rendered = out_file.read_text(encoding="utf-8")
        # legacy (v2=False) yolu metni hem döndürür hem dosyaya yazar
        assert text == rendered
        assert "main.py" in rendered
        assert "pkg" in rendered
        assert "utils.py" in rendered
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
    _text, parsed = flatten_repository_rendergit(FIXTURE_REPO, output_file=out, v2=True)
    # S2: dosya modunda metin dosyada; testler dosyadan okur
    return out, out.read_text(encoding="utf-8"), parsed


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


# ---------------------------------------------------------------------------
# S2 — streaming, determinizm, gitignore/exclude/include-ext, by_lang
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "skipdir").mkdir()
    (repo / "vendor").mkdir()
    (repo / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (repo / "src" / "b.log").write_text("log satiri\n", encoding="utf-8")
    (repo / "skipdir" / "c.py").write_text("print('c')\n", encoding="utf-8")
    (repo / "vendor" / "v.py").write_text("print('v')\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\nskipdir/\n", encoding="utf-8")
    return repo


def _skipped_reasons(path: Path) -> dict:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {entry["path"]: entry["reason"] for entry in lines}


def test_streaming_file_equals_stringio_text(tmp_path):
    """Akışlı dosya çıktısı, bellekte toplanan metinle bayt bayt aynı olmalı."""
    out = tmp_path / "exports/akis_rendergit.md"
    streamed, streamed_files = flatten_repository_rendergit(FIXTURE_REPO, output_file=out, v2=True)
    in_memory, memory_files = flatten_repository_rendergit(FIXTURE_REPO, v2=True)

    assert streamed == ""                      # dosya modunda metin tutulmaz
    assert [p.relative_to(FIXTURE_REPO).as_posix() for p in streamed_files] == \
           [p.relative_to(FIXTURE_REPO).as_posix() for p in memory_files]
    assert out.read_text(encoding="utf-8") == in_memory


def test_two_runs_byte_identical(tmp_path):
    import hashlib

    digests = []
    for index in range(2):
        out = tmp_path / f"run{index}" / "mini_rendergit.md"
        flatten_repository_rendergit(FIXTURE_REPO, output_file=out, v2=True)
        digests.append(hashlib.md5(out.read_bytes()).hexdigest())

    assert digests[0] == digests[1]


def test_gitignore_skips_and_records(tmp_path):
    repo = _make_repo(tmp_path)
    out = tmp_path / "gi_rendergit.md"
    _, parsed = flatten_repository_rendergit(repo, output_file=out, v2=True)

    rendered = {p.relative_to(repo).as_posix() for p in parsed}
    assert "src/a.py" in rendered
    assert "vendor/v.py" in rendered            # exclude verilmedi
    assert "src/b.log" not in rendered
    assert "skipdir/c.py" not in rendered

    body = out.read_text(encoding="utf-8")
    assert "b.log" not in body
    assert "skipdir" not in body

    reasons = _skipped_reasons(tmp_path / "gi_skipped.jsonl")
    assert reasons["src/b.log"] == "gitignore"
    # dizin deseni yürüyüşte budanır: içindeki dosya ayrıca kaydedilmez
    assert "skipdir/c.py" not in reasons


def test_exclude_patterns(tmp_path):
    repo = _make_repo(tmp_path)
    out = tmp_path / "ex_rendergit.md"
    _, parsed = flatten_repository_rendergit(
        repo, output_file=out, v2=True, exclude=["vendor", "src/b.log"]
    )

    rendered = {p.relative_to(repo).as_posix() for p in parsed}
    assert rendered == {"src/a.py"}              # skipdir/ zaten .gitignore'da

    body = out.read_text(encoding="utf-8")
    assert "vendor" not in body

    reasons = _skipped_reasons(tmp_path / "ex_skipped.jsonl")
    assert reasons["src/b.log"] == "exclude"     # dosya düzeyi desen


def test_include_ext_narrows(tmp_path):
    repo = _make_repo(tmp_path)
    out = tmp_path / "inc_rendergit.md"
    _, parsed = flatten_repository_rendergit(
        repo, output_file=out, v2=True, include_ext="py"
    )

    rendered = {p.relative_to(repo).as_posix() for p in parsed}
    assert rendered == {"src/a.py", "vendor/v.py"}

    coverage = json.loads((tmp_path / "inc_coverage.json").read_text(encoding="utf-8"))
    assert coverage["by_reason"]["include_ext"] == 1        # src/b.log
    assert coverage["files_total"] == coverage["files_rendered"] + coverage["files_skipped"]


def test_coverage_by_lang(tmp_path):
    repo = _make_repo(tmp_path)
    out = tmp_path / "lang_rendergit.md"
    _, parsed = flatten_repository_rendergit(repo, output_file=out, v2=True)

    coverage = json.loads((tmp_path / "lang_coverage.json").read_text(encoding="utf-8"))
    by_lang = coverage["by_lang"]
    assert set(by_lang) == {".py"}
    expected = sum(p.stat().st_size for p in parsed)
    assert by_lang[".py"] == expected
    assert sum(by_lang.values()) == coverage["bytes_rendered"]



def test_skipped_dirs_are_recorded(tmp_path):
    """Budanan dizinler (exclude/gitignore) coverage'da adıyla görünmeli."""
    repo = _make_repo(tmp_path)
    out = tmp_path / "dirs_rendergit.md"
    flatten_repository_rendergit(repo, output_file=out, v2=True, exclude=["vendor"])

    coverage = json.loads((tmp_path / "dirs_coverage.json").read_text(encoding="utf-8"))
    assert {"path": "vendor/", "reason": "exclude"} in coverage["dirs_skipped"]
    assert {"path": "skipdir/", "reason": "gitignore"} in coverage["dirs_skipped"]


# ---------------------------------------------------------------------------
# S3 — BOM/CRLF normalizasyonu, hash dedupe, --units filtresi, DB inceltme
# ---------------------------------------------------------------------------

BOM_CHAR = "\ufeff"

UNITS_SOURCE = (
    "def one(a):\n"
    "    return a + 1\n"
    "\n"
    "class Box:\n"
    "    def size(self):\n"
    "        return 1\n"
    "\n"
    "def two():\n"
    "    total = 0\n"
    "    for i in range(3):\n"
    "        total += i\n"
    "        total += 1\n"
    "    return total\n"
)


def _units_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "units_repo"
    repo.mkdir()
    (repo / "m.py").write_text(UNITS_SOURCE, encoding="utf-8")
    return repo


def test_s3_bom_stripped_and_crlf_normalized(tmp_path):
    out, text, _ = _run_fixture(tmp_path)
    assert BOM_CHAR not in text                      # BOM'lu dosya BOM taşımaz
    assert "\r" not in text                          # CRLF → LF
    assert "def bom_func():" in text
    assert "def crlf_func():" in text


def test_s3_duplicate_content_written_once(tmp_path):
    out, text, _ = _run_fixture(tmp_path)
    coverage = json.loads((out.parent / "mini_coverage.json").read_text(encoding="utf-8"))

    assert coverage["files_deduplicated"] == 1
    dup = coverage["duplicates"][0]
    assert dup["path"] == "dup_b.py"
    assert dup["duplicate_of"] == "dup_a.py"
    assert dup["bytes"] == (FIXTURE_REPO / "dup_b.py").stat().st_size

    # içerik yalnız bir kez yazılır
    assert text.count("def dup_func()") == 1
    dup_block = text.split("FILE: dup_b.py", 1)[1].split("FILE: ", 1)[0]
    assert "duplicate_of: dup_a.py" in dup_block
    assert "def dup_func()" not in dup_block


def test_s3_bom_file_parses_for_ast(tmp_path):
    errs = tmp_path / "bom_ast.json"
    units = extract_and_store_code_units(
        [FIXTURE_REPO / "bom.py"], FIXTURE_REPO, tmp_path / "bom.db", "pb", ast_errors_path=errs
    )
    assert [u["name"] for u in units] == ["bom_func"]      # BOM AST'yi bozmuyor
    assert json.loads(errs.read_text(encoding="utf-8"))["files_with_errors"] == 0


def test_s3_db_columns_indexes_and_offsets(tmp_path):
    repo = _units_repo(tmp_path)
    db = tmp_path / "u.db"
    errs = tmp_path / "ast_errors.json"

    units = extract_and_store_code_units([repo / "m.py"], repo, db, "p1", ast_errors_path=errs)
    assert {u["unit_type"] for u in units} == {"function", "class", "loop"}

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT sha1, byte_offset, end_offset, code FROM code_units WHERE name = 'one'"
    ).fetchone()
    source_bytes = (repo / "m.py").read_text(encoding="utf-8").encode("utf-8")
    assert len(row[0]) == 40
    assert row[1] == 0
    assert source_bytes[row[1]:row[2]].decode("utf-8").startswith(row[3])
    index_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "idx_code_units_project_file",
        "idx_code_units_project_type",
        "idx_code_units_project_name",
    } <= index_names
    like_plan = [r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM code_units WHERE project_id = ? AND name LIKE ?",
        ("p1", "one%"),
    )]
    assert any("idx_code_units_project_name" in line for line in like_plan), like_plan
    conn.close()

    payload = json.loads(errs.read_text(encoding="utf-8"))
    assert payload["files_parsed"] == 1
    assert payload["files_with_errors"] == 0
    assert payload["units_stored"] == len(units)
    assert payload["store_code"] is True
    assert payload["units_filter"] == ["class", "function", "loop"]


def test_s3_units_filter_drops_loops_only_when_asked(tmp_path):
    repo = _units_repo(tmp_path)

    default_db = tmp_path / "default.db"
    default_units = extract_and_store_code_units(
        [repo / "m.py"], repo, default_db, "p1", ast_errors_path=tmp_path / "d.json"
    )
    assert any(u["unit_type"] == "loop" for u in default_units)         # varsayılan korunur

    filtered_db = tmp_path / "filtered.db"
    filtered = extract_and_store_code_units(
        [repo / "m.py"], repo, filtered_db, "p1", units="function,class",
        ast_errors_path=tmp_path / "f.json",
    )
    assert {u["unit_type"] for u in filtered} == {"function", "class"}
    assert len(filtered) == len(default_units) - sum(
        1 for u in default_units if u["unit_type"] == "loop"
    )

    conn = sqlite3.connect(filtered_db)
    assert conn.execute("SELECT COUNT(*) FROM code_units WHERE unit_type = 'loop'").fetchone()[0] == 0
    conn.close()
    assert json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))["units_filter"] == ["class", "function"]


def test_s3_store_code_zero_nulls_code_column(tmp_path):
    repo = _units_repo(tmp_path)
    full_db = tmp_path / "full.db"
    full = extract_and_store_code_units(
        [repo / "m.py"], repo, full_db, "p1", ast_errors_path=tmp_path / "full.json"
    )

    thin_db = tmp_path / "thin.db"
    thin = extract_and_store_code_units(
        [repo / "m.py"], repo, thin_db, "p1", store_code="0", ast_errors_path=tmp_path / "thin.json"
    )
    assert len(thin) == len(full)

    conn = sqlite3.connect(thin_db)
    assert conn.execute("SELECT COUNT(*) FROM code_units").fetchone()[0] == len(full)
    assert conn.execute("SELECT COUNT(*) FROM code_units WHERE code IS NOT NULL").fetchone()[0] == 0
    # sha1 / offset kolonları code kapatılsa da dolu
    assert conn.execute("SELECT COUNT(*) FROM code_units WHERE sha1 IS NULL OR byte_offset IS NULL").fetchone()[0] == 0
    conn.close()
    assert json.loads((tmp_path / "thin.json").read_text(encoding="utf-8"))["store_code"] is False


def test_s3_invalid_unit_type_raises(tmp_path):
    repo = _units_repo(tmp_path)
    with pytest.raises(ValueError):
        extract_and_store_code_units(
            [repo / "m.py"], repo, tmp_path / "x.db", "p1", units="function,loops"
        )


def test_s3_ast_errors_counted(tmp_path):
    repo = tmp_path / "bad_repo"
    repo.mkdir()
    (repo / "ok.py").write_text("def ok_fn():\n    return 1\n", encoding="utf-8")
    (repo / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    errs = tmp_path / "ast.json"
    units = extract_and_store_code_units(
        [repo / "ok.py", repo / "bad.py"], repo, tmp_path / "b.db", "p1", ast_errors_path=errs
    )
    payload = json.loads(errs.read_text(encoding="utf-8"))
    assert payload["files_considered"] == 2
    assert payload["files_parsed"] == 1
    assert payload["files_with_errors"] == 1
    assert payload["errors"][0]["file_path"] == "bad.py"
    assert [u["name"] for u in units] == ["ok_fn"]
