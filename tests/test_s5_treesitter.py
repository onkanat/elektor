"""
S5 — tree-sitter ile C++/CUDA/Metal/TS birim çıkarımı (opt-in).

Kapsam: paket yokken zarif geri düşüş, C++ function/class/loop, namespace/macro
opt-in, bayt kapsamı ölçümü ve varsayılan (python) davranışın değişmediği kanıtı.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pipeline import code_extractor as ce
from pipeline.code_extractor import (
    TreeSitterAnalyzer,
    ast_byte_coverage,
    extract_and_store_code_units,
    _normalize_ast_lang,
)

CPP_SOURCE = """#define MAXN 128
#define SQR(x) ((x) * (x))

// Basit nokta
struct Point {
    float x;
    float y;
};

class Shape {
public:
    virtual float area() const { return 0.0f; }
};

template <typename T>
T clampv(T v, T lo, T hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

static int total(const int* values, int n) {
    int sum = 0;
    for (int i = 0; i < n; i++) {
        sum += values[i];
    }
    for (auto& item : values) {
        sum += item;
    }
    return sum;
}

namespace engine {
namespace detail {
int helper(int v) {
    return v * 2;
}
}
}
"""

PY_SOURCE = '''def add(a, b):
    return a + b


class Box:
    def size(self):
        return 1
'''

CUDA_SOURCE = """__global__ void saxpy(float* y, const float* x, float a, int n) {
    for (int i = 0; i < n; i++) {
        y[i] = a * x[i] + y[i];
    }
}
"""

METAL_SOURCE = """kernel void add_arrays(device float* a, device const float* b, uint i) {
    for (uint k = 0; k < 4; k++) {
        a[i] = a[i] + b[i] * k;
    }
}
"""

TS_SOURCE = """export class Greeter {
    greet(name: string): string {
        return `hi ${name}`;
    }
}

export function loopOver(items: number[]): number {
    let total = 0;
    for (const item of items) {
        total += item;
    }
    return total;
}
"""

needs_ts = pytest.mark.skipif(
    not ce.treesitter_available(), reason="tree-sitter kurulu değil"
)


def _repo(tmp_path: Path, **files: str) -> tuple[Path, list[Path]]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = repo / name.replace("__", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    paths = sorted(p for p in repo.rglob("*") if p.is_file())
    return repo, paths


def _units(repo: Path, paths: list[Path], db: Path, project: str, **kwargs):
    return extract_and_store_code_units(
        paths,
        repo,
        db,
        project,
        repo_url="fixture",
        ast_errors_path=db.parent / f"{project}_errors.json",
        **kwargs,
    )


def _rows(db: Path, project: str):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT file_path, unit_type, name, lineno, sha1 FROM code_units "
            "WHERE project_id = ? ORDER BY file_path, lineno, unit_type, name",
            (project,),
        ).fetchall()
    finally:
        conn.close()


# (a) paket yokken zarif geri düşüş -----------------------------------------
def test_s5_missing_package_falls_back_to_python(tmp_path, monkeypatch):
    """tree-sitter yoksa --ast-lang python,cpp patlamaz; python birimleri kalır."""
    repo, paths = _repo(tmp_path, **{"a.py": PY_SOURCE, "b.cpp": CPP_SOURCE})
    monkeypatch.setattr(ce, "_TS_CORE", False)
    monkeypatch.setattr(ce, "_ts", None)

    units = _units(repo, paths, tmp_path / "fallback.db", "fallback", ast_lang="python,cpp")

    assert all(u["file_path"].endswith(".py") for u in units)
    assert {u["unit_type"] for u in units} <= {"function", "class", "loop"}
    stats = (tmp_path / "fallback_errors.json").read_text(encoding="utf-8")
    assert '"ast_lang_unavailable": [' in stats
    assert "cpp" in stats
    assert ce.treesitter_available() is False


# (b) C++ function/class/loop ------------------------------------------------
@needs_ts
def test_s5_cpp_extracts_function_class_loop(tmp_path):
    repo, paths = _repo(tmp_path, **{"main.cpp": CPP_SOURCE})
    units = _units(repo, paths, tmp_path / "cpp.db", "cpp", ast_lang="cpp")

    names = {u["name"] for u in units}
    types = {u["unit_type"] for u in units}
    assert {"Point", "Shape", "clampv", "total"} <= names
    assert {"function", "class", "loop"} <= types
    assert types <= {"function", "class", "loop", "namespace", "macro"}
    source_lines = CPP_SOURCE.splitlines()
    for unit in units:
        expected = "\n".join(source_lines[unit["lineno"] - 1 : unit["end_lineno"]])
        assert unit["code"] == expected

    loops = [u for u in units if u["unit_type"] == "loop"]
    assert len(loops) >= 2  # klasik for + range-based for
    assert all(u["name"].endswith(f"_L{u['lineno']}") for u in loops)


# (c) namespace opt-in -------------------------------------------------------
@needs_ts
def test_s5_namespace_only_when_opted_in(tmp_path):
    repo, paths = _repo(tmp_path, **{"main.cpp": CPP_SOURCE, "a.py": PY_SOURCE})

    default_units = _units(repo, paths, tmp_path / "ns_off.db", "ns_off")
    assert not [u for u in default_units if u["unit_type"] == "namespace"]

    with_ns = _units(repo, paths, tmp_path / "ns_on.db", "ns_on", ast_lang="python,cpp")
    namespaces = [u["name"] for u in with_ns if u["unit_type"] == "namespace"]
    assert namespaces == ["engine", "detail"]

    filtered = _units(
        repo, paths, tmp_path / "ns_filter.db", "ns_filter",
        ast_lang="cpp", units="function,class,loop",
    )
    assert not [u for u in filtered if u["unit_type"] == "namespace"]


# (d) macro opt-in -----------------------------------------------------------
@needs_ts
def test_s5_macro_only_when_opted_in(tmp_path):
    repo, paths = _repo(tmp_path, **{"main.cpp": CPP_SOURCE})

    default_units = _units(repo, paths, tmp_path / "macro_off.db", "macro_off")
    assert not [u for u in default_units if u["unit_type"] == "macro"]

    opt_in = _units(repo, paths, tmp_path / "macro_on.db", "macro_on", ast_lang="cpp")
    macros = sorted(u["name"] for u in opt_in if u["unit_type"] == "macro")
    assert macros == ["MAXN", "SQR"]


# (e) kapsam oranı ölçümü ----------------------------------------------------
@needs_ts
def test_s5_byte_coverage_rises_with_languages(tmp_path):
    repo, paths = _repo(
        tmp_path,
        **{
            "main.cpp": CPP_SOURCE,
            "a.py": PY_SOURCE,
            "k.cu": CUDA_SOURCE,
            "s.metal": METAL_SOURCE,
            "m.ts": TS_SOURCE,
        },
    )
    before = _units(repo, paths, tmp_path / "cov_before.db", "cov_before")
    after = _units(
        repo, paths, tmp_path / "cov_after.db", "cov_after",
        ast_lang="python,cpp,cuda,metal,typescript",
    )

    cov_before = ast_byte_coverage(before, repo, paths)
    cov_after = ast_byte_coverage(after, repo, paths)

    assert cov_before["ratio"] < 0.20, cov_before
    assert cov_after["ratio"] >= 0.50, cov_after
    assert cov_after["ratio"] > cov_before["ratio"]
    # her dil gerçekten birim üretmeli
    langs = {Path(u["file_path"]).suffix for u in after}
    assert {".py", ".cpp", ".cu", ".metal", ".ts"} <= langs


# (f) varsayılan davranış değişmedi -----------------------------------------
def test_s5_default_run_is_python_only_and_stable(tmp_path):
    repo, paths = _repo(
        tmp_path,
        **{"a.py": PY_SOURCE, "main.cpp": CPP_SOURCE, "m.ts": TS_SOURCE},
    )
    first = _units(repo, paths, tmp_path / "default1.db", "default")
    second = _units(repo, paths, tmp_path / "default2.db", "default")

    assert _rows(tmp_path / "default1.db", "default") == _rows(tmp_path / "default2.db", "default")
    assert len(first) == len(second) == 3
    assert {Path(u["file_path"]).suffix for u in first} == {".py"}

    manifest_settings = __import__("json").loads(
        (tmp_path / "default_manifest.json").read_text(encoding="utf-8")
    ) if (tmp_path / "default_manifest.json").exists() else None
    if manifest_settings is not None:  # manifest yolu verilmedi → yazılmaz
        assert "ast_lang" not in manifest_settings["settings"]


def test_s5_default_settings_signature_unchanged(tmp_path):
    """Manifest imzası S5 öncesiyle aynı: dil seti varsayılanda anahtar eklemez."""
    repo, paths = _repo(tmp_path, **{"a.py": PY_SOURCE, "main.cpp": CPP_SOURCE})
    db = tmp_path / "sig.db"
    manifest = tmp_path / "sig_manifest.json"
    _units(repo, paths, db, "sig", manifest_path=manifest)
    settings = __import__("json").loads(manifest.read_text(encoding="utf-8"))["settings"]
    assert settings == {"units": ["class", "function", "loop"], "store_code": True}

    manifest2 = tmp_path / "sig2_manifest.json"
    _units(repo, paths, tmp_path / "sig2.db", "sig", ast_lang="python,cpp",
           manifest_path=manifest2)
    settings2 = __import__("json").loads(manifest2.read_text(encoding="utf-8"))["settings"]
    assert settings2["ast_lang"] == ["python", "cpp"]


# (g) dil normalizasyonu / hatalı bayrak -------------------------------------
def test_s5_ast_lang_normalization_and_validation():
    assert _normalize_ast_lang(None) == ("python",)
    assert _normalize_ast_lang("") == ("python",)
    assert _normalize_ast_lang("python, cpp ,cuda") == ("python", "cpp", "cuda")
    assert _normalize_ast_lang("ts") == ("typescript",)
    assert _normalize_ast_lang(["py", "python"]) == ("python",)
    with pytest.raises(ValueError):
        _normalize_ast_lang("rust")


# (h) analyzer sözleşmesi ----------------------------------------------------
@needs_ts
def test_s5_analyzer_contract_fields():
    analyzer = TreeSitterAnalyzer(CPP_SOURCE, "main.cpp", "cpp", extended=True)
    units = analyzer.analyze()
    assert units
    required = {"unit_type", "name", "signature", "docstring", "code", "line_count",
                "lineno", "end_lineno"}
    for unit in units:
        assert required <= set(unit)
        assert unit["line_count"] == unit["end_lineno"] - unit["lineno"] + 1
        assert unit["code"].strip()
    point = next(u for u in units if u["name"] == "Point")
    assert point["unit_type"] == "class"
    assert point["docstring"] == "Basit nokta"
