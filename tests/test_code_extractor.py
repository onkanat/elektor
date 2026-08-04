import pytest
import sqlite3
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from pipeline.code_extractor import CodeAnalyzer, flatten_repository_rendergit, extract_and_store_code_units, init_code_db
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



