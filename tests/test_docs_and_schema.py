import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC_MARKDOWN_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "USER_GUIDE.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "ROADMAP.md",
    REPO_ROOT / "tools" / "README.md",
    REPO_ROOT / "templates" / "USER_GUIDE.md",
] + sorted(list((REPO_ROOT / "tools" / "docs").glob("*.md")))

CONFIG_FILES = [
    REPO_ROOT / "config.json",
    REPO_ROOT / "gemini.json",
    REPO_ROOT / "ollama_cloud.json",
    REPO_ROOT / "templates" / "gemini.json",
    REPO_ROOT / "templates" / "ollama_cloud.json",
]


class TestDocsAndSchema:
    """Milestone M5: Documentation cleansing, link verification, schema synchronization, and pytest.ini verification."""

    def test_no_macos_user_paths_in_documentation(self):
        """Assert zero occurrences of 'file:///Users/' across all documentation markdown files."""
        assert len(DOC_MARKDOWN_FILES) >= 10, f"Expected at least 10 doc files, found {len(DOC_MARKDOWN_FILES)}"
        violations = []
        for doc_path in DOC_MARKDOWN_FILES:
            assert doc_path.exists(), f"Doc file {doc_path} does not exist"
            content = doc_path.read_text(encoding="utf-8")
            if "file:///Users/" in content:
                violations.append(str(doc_path.relative_to(REPO_ROOT)))

        assert not violations, f"Found hardcoded macOS file:///Users/ links in: {violations}"

    def test_user_guide_images_paths(self):
        """USER_GUIDE.md image links point to frontend/public/guide_images/ rather than root /guide_images/."""
        ug_path = REPO_ROOT / "USER_GUIDE.md"
        assert ug_path.exists()
        content = ug_path.read_text(encoding="utf-8")
        assert "(/guide_images/" not in content, "USER_GUIDE.md still contains root /guide_images/ links"
        assert "frontend/public/guide_images/" in content, "USER_GUIDE.md should reference frontend/public/guide_images/"

    def test_readme_pipeline_command_and_single_unit_tests_section(self):
        """README.md contains pipeline subcommand for template executions and has no duplicate unit tests section."""
        readme_path = REPO_ROOT / "README.md"
        assert readme_path.exists()
        content = readme_path.read_text(encoding="utf-8")

        # Verify pipeline subcommand in templates invocation
        assert "python run.py --config templates/gemini.json pipeline" in content
        assert "python run.py --config templates/ollama_cloud.json pipeline" in content

        # Verify duplicate unit test section removed (should appear exactly once)
        occurrences = content.count("## 🔬 Unit Tests & Verification")
        assert occurrences == 1, f"Expected '## 🔬 Unit Tests & Verification' to appear once, found {occurrences}"

    def test_config_files_parse_and_contain_required_flags(self):
        """All configuration files parse as valid JSON and contain clean_alpaca_input, filter_boilerplate, and platform-independent tesseract_cmd."""
        for cfg_path in CONFIG_FILES:
            assert cfg_path.exists(), f"Config file {cfg_path} does not exist"
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            rel_name = cfg_path.relative_to(REPO_ROOT)
            assert data.get("clean_alpaca_input") is True, f"{rel_name} missing or invalid clean_alpaca_input"
            assert data.get("filter_boilerplate") is True, f"{rel_name} missing or invalid filter_boilerplate"

            tesseract = data.get("tesseract_cmd")
            assert tesseract is not None, f"{rel_name} missing tesseract_cmd"
            assert "/opt/homebrew" not in tesseract, f"{rel_name} contains macOS specific tesseract path: {tesseract}"
            assert tesseract == "tesseract", f"{rel_name} expected platform-independent 'tesseract', got '{tesseract}'"

    def test_pytest_ini_exists_and_configured(self):
        """pytest.ini exists at repo root and specifies pythonpath, testpaths, and asyncio_mode."""
        ini_path = REPO_ROOT / "pytest.ini"
        assert ini_path.exists(), "pytest.ini must exist at root"
        content = ini_path.read_text(encoding="utf-8")

        assert "pythonpath" in content and "." in content
        assert "testpaths" in content and "tests" in content
        assert "asyncio_mode" in content and "strict" in content

    def test_bare_pytest_succeeds_without_pythonpath(self):
        """Running pytest without PYTHONPATH environment variable succeeds cleanly."""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        cmd = [sys.executable, "-m", "pytest", "tests/test_docs_and_schema.py::TestDocsAndSchema::test_pytest_ini_exists_and_configured", "-q"]
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        assert res.returncode == 0, f"Bare pytest failed without PYTHONPATH: {res.stderr or res.stdout}"
