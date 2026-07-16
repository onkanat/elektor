import os
import sqlite3
import pytest
import json
import tempfile
from pathlib import Path
from pipeline.extractor import ArchiveExtractor

@pytest.fixture
def temp_config_and_db():
    # Setup a temporary directory for DB and mock files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_file = tmp_path / "test_elektor.db"
        usb_dir = tmp_path / "mock_usb"
        articles_dir = usb_dir / "articles"
        articles_dir.mkdir(parents=True)
        
        # Create a mock zoom_pageinfo.csv
        lib_dir = usb_dir / "lib"
        lib_dir.mkdir(parents=True)
        csv_file = lib_dir / "zoom_pageinfo.csv"
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write('"./2022/test1.pdf","test1.pdf","project Mock Title By Test Author","",""\n')
            
        config = {
            "usb_path": str(usb_dir),
            "db_path": str(db_file),
            "qdrant_db_path": str(tmp_path / "qdrant_db"),
            "ollama_url": "http://localhost:11434",
            "model_embedding": "nomic-embed-text:latest",
            "model_analyzer": "qwen3.5:2b",
            "chunk_size": 100,
            "chunk_overlap": 20,
            "ocr_threshold_chars": 10
        }
        
        config_file = tmp_path / "config.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)
            
        yield config_file, db_file, csv_file, articles_dir

def test_extractor_initialization(temp_config_and_db):
    config_file, db_file, _, _ = temp_config_and_db
    extractor = ArchiveExtractor(config_path=str(config_file))
    
    assert os.path.exists(db_file)
    # Check that tables are created
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
    assert cursor.fetchone() is not None
    conn.close()
    extractor.close()

def test_load_zoom_metadata(temp_config_and_db):
    config_file, _, _, _ = temp_config_and_db
    extractor = ArchiveExtractor(config_path=str(config_file))
    
    metadata = extractor.load_zoom_metadata()
    assert "test1.pdf" in metadata
    assert "project Mock Title By Test Author" in metadata["test1.pdf"]
    extractor.close()
