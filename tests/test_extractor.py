import os
import sqlite3
import json
import unittest
import tempfile
from pathlib import Path
from pipeline.extractor import ArchiveExtractor

class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmpdir.name)
        self.db_file = tmp_path / "test_universal.db"
        usb_dir = tmp_path / "mock_usb"
        articles_dir = usb_dir / "articles"
        articles_dir.mkdir(parents=True)
        
        # Create a mock zoom_pageinfo.csv
        lib_dir = usb_dir / "lib"
        lib_dir.mkdir(parents=True)
        self.csv_file = lib_dir / "zoom_pageinfo.csv"
        with open(self.csv_file, "w", encoding="utf-8") as f:
            f.write('"./2022/test1.pdf","test1.pdf","project Mock Title By Test Author","",""\n')
            
        config = {
            "usb_path": str(usb_dir),
            "db_path": str(self.db_file),
            "qdrant_db_path": str(tmp_path / "qdrant_db"),
            "ollama_url": "http://localhost:11434",
            "model_embedding": "nomic-embed-text:latest",
            "model_analyzer": "qwen3.5:2b",
            "chunk_size": 100,
            "chunk_overlap": 20,
            "ocr_threshold_chars": 10
        }
        
        self.config_file = tmp_path / "config.json"
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extractor_initialization(self):
        extractor = ArchiveExtractor(config_path=str(self.config_file))
        
        self.assertTrue(os.path.exists(self.db_file))
        # Check that tables are created
        conn = sqlite3.connect(str(self.db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()
        extractor.close()

    def test_load_zoom_metadata(self):
        extractor = ArchiveExtractor(config_path=str(self.config_file))
        
        metadata = extractor.load_zoom_metadata()
        self.assertIn("test1.pdf", metadata)
        self.assertIn("project Mock Title By Test Author", metadata["test1.pdf"])
        extractor.close()

    def test_book_mode_segmentation(self):
        tmp_path = Path(self.tmpdir.name)
        book_file = tmp_path / "mock_book.pdf"
        with open(book_file, "w") as f:
            f.write("mock pdf content")
            
        config = {
            "input_mode": "book",
            "input_path": str(book_file),
            "db_path": str(self.db_file),
            "qdrant_db_path": str(tmp_path / "qdrant_db"),
            "ollama_url": "http://localhost:11434",
            "model_embedding": "nomic-embed-text:latest",
            "model_analyzer": "qwen3.5:2b",
            "chunk_size": 100,
            "chunk_overlap": 20,
            "ocr_threshold_chars": 10
        }
        
        book_config_file = tmp_path / "book_config.json"
        with open(book_config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)
            
        extractor = ArchiveExtractor(config_path=str(book_config_file))
        
        from unittest.mock import MagicMock, patch
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is some mock chapter text."
        mock_reader.pages = [mock_page, mock_page, mock_page, mock_page, mock_page]
        
        mock_dest1 = MagicMock()
        mock_dest1.get.return_value = "Chapter 1"
        mock_dest2 = MagicMock()
        mock_dest2.get.return_value = "Chapter 2"
        mock_reader.outline = [mock_dest1, mock_dest2]
        
        mock_reader.get_destination_page_number.side_effect = [0, 3]
        
        with patch('pypdf.PdfReader', return_value=mock_reader):
            extractor.process_all_articles()
            
        conn = sqlite3.connect(str(self.db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, title, extracted_text FROM articles")
        rows = cursor.fetchall()
        conn.close()
        extractor.close()
        
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "mock_book.pdf::range::0_2")
        self.assertEqual(rows[0][1], "Chapter 1")
        self.assertEqual(rows[1][0], "mock_book.pdf::range::3_4")
        self.assertEqual(rows[1][1], "Chapter 2")

if __name__ == "__main__":
    unittest.main()
