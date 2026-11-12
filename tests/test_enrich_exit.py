import json
import pytest

from run import compute_enrich_exit, run_sharded_enrichment


def test_strict_fallback_exit_code():
    assert compute_enrich_exit({"enriched": 0, "fallback": 3, "failed": 0}, strict=True) == 2
    assert compute_enrich_exit({"enriched": 2, "fallback": 1, "failed": 0}, strict=True) == 2
    assert compute_enrich_exit({"enriched": 2, "fallback": 1, "failed": 0}, strict=False) == 0


def test_strict_failed_exit_code():
    assert compute_enrich_exit({"enriched": 1, "fallback": 0, "failed": 1}, strict=True) == 2


def test_strict_clean_run_exit_code():
    assert compute_enrich_exit({"enriched": 2, "fallback": 0, "failed": 0}, strict=True) == 0


def test_remote_analyzer_rejects_sharding_before_db(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "openai_base_url": "http://192.0.2.10:8080/v1",
        "db_path": str(tmp_path / "missing.db"),
    }), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_sharded_enrichment(str(cfg), None, 2, "11434", strict=True)
    assert exc.value.code == 2
