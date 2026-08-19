import unittest
import os
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from pipeline.extractor import ArchiveExtractor
from pipeline.kiwix_extractor import KiwixZimExtractor
from pipeline.judge_engine import JudgeEngine
from pipeline.visual_dataset_builder import VisualDatasetBuilder
from pipeline.cloud_gpu_offloader import CloudGPUOffloader
from pipeline.hf_deployer import HFDeployer

class TestRealDataPipelines(unittest.TestCase):
    """
    Integration tests running directly on real datasets in downloads/:
    - downloads/Exercisesheet1.pdf
    - downloads/U070262.pdf
    - downloads/ham.stackexchange.com_en_all_2026-02.zim
    """

    @classmethod
    def setUpClass(cls):
        cls.downloads_dir = Path("downloads")
        cls.pdf1 = cls.downloads_dir / "Exercisesheet1.pdf"
        cls.pdf2 = cls.downloads_dir / "U070262.pdf"
        cls.zim_file = cls.downloads_dir / "ham.stackexchange.com_en_all_2026-02.zim"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = Path(self.temp_dir.name) / "test_real.db"
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config = {
            "project_id": "test_real_data",
            "db_path": str(self.temp_db_path),
            "input_path": str(self.downloads_dir),
            "input_mode": "folder",
            "judge_model": "gemini-3.6-flash",
            "judge_threshold": 7.0,
            "enable_langextract": False
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_real_pdf_extraction(self):
        """Test text and metadata extraction from real PDF files in downloads/."""
        if not self.pdf1.exists() and not self.pdf2.exists():
            self.skipTest("Gerçek PDF dosyaları downloads/ altında bulunamadı.")

        extractor = ArchiveExtractor(config_path=str(self.config_path))
        try:
            extractor.process_all_articles(limit=2)
        finally:
            extractor.close()

        # Verify SQLite DB
        self.assertTrue(self.temp_db_path.exists())
        conn = sqlite3.connect(str(self.temp_db_path))
        cur = conn.cursor()
        cur.execute("SELECT count(*), title, length(extracted_text) FROM articles")
        count, sample_title, text_len = cur.fetchone()
        conn.close()

        self.assertGreater(count, 0, "En az 1 makale/sayfa çıkarılmış olmalı.")
        self.assertGreater(text_len, 50, "Ham metin içeriği dolu olmalı.")
        print(f"\n[Real PDF Extract] Toplam Çıkarılan Kayıt: {count}, Örnek Başlık: {sample_title} ({text_len} karakter)")

    def test_02_real_kiwix_zim_extraction(self):
        """Test extraction of real StackExchange articles from .zim archive."""
        if not self.zim_file.exists():
            self.skipTest("Gerçek ZIM dosyası downloads/ altında bulunamadı.")

        zim_extractor = KiwixZimExtractor(config_path=str(self.config_path))
        try:
            processed = zim_extractor.extract_from_zim(zim_path=str(self.zim_file), limit=3)
        finally:
            zim_extractor.close()

        # Verify SQLite DB articles
        conn = sqlite3.connect(str(self.temp_db_path))
        cur = conn.cursor()
        cur.execute("SELECT count(*), title FROM articles WHERE file_path LIKE 'zim://%'")
        count, title = cur.fetchone()
        conn.close()

        self.assertGreater(count, 0, "Kiwix ZIM arşivinden en az 1 makale çıkarılmış olmalı.")
        print(f"\n[Real Kiwix Extract] ZIM'den Çıkarılan Makale: {count}, Örnek Başlık: {title}")

    @patch("pipeline.vision_ocr.VisionOCRManager.check_health", return_value=True)
    @patch("pipeline.vision_ocr.VisionOCRManager.describe_cropped_image")
    def test_03_real_multimodal_markdown_export(self, mock_describe, mock_health):
        """Test building multimodal visual dataset and catalog from real extracted images."""
        images_dir = self.downloads_dir / "extracted_images"
        if not images_dir.exists():
            self.skipTest("extracted_images dizini bulunamadı.")

        mock_describe.return_value = (
            "### Schematic Analysis\n"
            "- **Component**: RF Mixer LO Filter Circuit\n"
            "- **Parameters**: Cutoff frequency = 144 MHz, Characteristic Impedance Z_0 = 50 Ohm\n"
            "- **Function**: Bandpass filter attenuates spurious signals at intermediate stage."
        )

        builder = VisualDatasetBuilder(config_path=str(self.config_path))
        result = builder.export_visual_dataset()

        self.assertEqual(result["status"], "success")
        catalog_path = Path("exports") / "test_real_data" / "multimodal_catalog.md"
        self.assertTrue(catalog_path.exists())
        content = catalog_path.read_text(encoding="utf-8")
        self.assertIn("Multimodal Technical Catalog & Diagram Breakdown", content)
        self.assertIn("Figure 1:", content)
        print(f"\n[Real Multimodal Catalog] {catalog_path.name} başarıyla üretildi ({len(content)} bayt).")

    def test_04_cloud_training_payload_real_generation(self):
        """Test generation of Unsloth + Vertex AI Gemini Fine-Tuning recipes."""
        offloader = CloudGPUOffloader(exports_dir=self.temp_dir.name)
        payload = offloader.generate_payload(
            project_id="test_real_data",
            base_model="Qwen/Qwen2.5-Coder-7B-Instruct",
            hf_dataset="onkanat/test-real-dataset"
        )
        self.assertEqual(payload["status"], "success")
        self.assertIn("vertex_ai_tuning.json", payload["generated_files"])
        print(f"\n[Real Cloud Kit] Üretilen eğitim reçeteleri: {payload['generated_files']}")

if __name__ == "__main__":
    unittest.main()
