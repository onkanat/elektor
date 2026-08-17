import os
import json
import sqlite3
import pytest
from pathlib import Path
from pipeline.extractor import ArchiveExtractor
from pipeline.dataset_builder import DatasetBuilder

def test_extractor_langextract_sqlite_table(tmp_path):
    db_file = tmp_path / "test_pipeline.db"
    cfg = {
        "input_mode": "folder",
        "input_path": str(tmp_path),
        "db_path": str(db_file),
        "ollama_url": "http://localhost:11434",
        "langextract_provider": "ollama",
        "langextract_schema_preset": "technical_components"
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    
    extractor = ArchiveExtractor(config_path=str(cfg_file))
    
    # Verify langextract_extractions table exists
    cursor = extractor.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='langextract_extractions'")
    assert cursor.fetchone() is not None
    
    # Test inserting an article and running langextract on it
    cursor.execute("""
        INSERT INTO articles (file_path, filename, title, year, extracted_text, is_ocr, processed_at)
        VALUES ('test_doc.pdf', 'test_doc.pdf', 'Test Document', 2026, 'The ATmega328P operates at 5V.', 0, '2026-08-17T12:00:00')
    """)
    extractor.conn.commit()
    article_id = cursor.lastrowid
    
    extractor.run_langextract_on_article(article_id, "The ATmega328P operates at 5V.", "technical_components")
    
    cursor.execute("SELECT text_span, start_char, end_char, preset FROM langextract_extractions WHERE article_id = ?", (article_id,))
    rows = cursor.fetchall()
    assert len(rows) >= 1
    
    # Test DatasetBuilder export of langextract_grounded_dataset.jsonl
    builder = DatasetBuilder(config_path=str(cfg_file))
    builder.export_langextract_dataset(extractor.conn)
    
    export_dir = Path("exports") / "test_pipeline"
    jsonl_file = export_dir / "langextract_grounded_dataset.jsonl"
    assert jsonl_file.exists()
    
    lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    first_record = json.loads(lines[0])
    assert "start_char" in first_record
    assert "end_char" in first_record
    assert "text_span" in first_record
