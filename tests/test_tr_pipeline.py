import os
import sqlite3
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.analyzer import ArchiveAnalyzer
from pipeline.dataset_builder import DatasetBuilder
from pipeline.cloud_gpu_offloader import CloudGPUOffloader

class TestTRPipeline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmpdir.name)
        self.db_file = tmp_path / "test_universal_tr.db"
        
        self.config = {
            "usb_path": str(tmp_path / "usb"),
            "db_path": str(self.db_file),
            "qdrant_db_path": str(tmp_path / "qdrant_db"),
            "ollama_url": "http://localhost:11434",
            "model_embedding": "nomic-embed-text:latest",
            "model_analyzer": "qwen3.6:35b",
            "model_translator": "translategemma:12b-it-q4_K_M",
            "qa_count_per_article": 10,
            "chunk_size": 800,
            "chunk_overlap": 150
        }
        
        self.config_file = tmp_path / "config.json"
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f)
            
    def tearDown(self):
        self.tmpdir.cleanup()

    def test_analyzer_tr_schema_and_qa_count(self):
        analyzer = ArchiveAnalyzer(config_path=str(self.config_file))
        
        self.assertEqual(analyzer.qa_count, 10)
        
        # Check sqlite table schema
        conn = sqlite3.connect(str(self.db_file))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(enrichments)")
        cols = [c[1] for c in cursor.fetchall()]
        self.assertIn("tr_sft_qa", cols)
        self.assertIn("tr_dpo_pairs", cols)
        conn.close()
        analyzer.close()

    def test_dataset_builder_tr_exports(self):
        tmp_path = Path(self.tmpdir.name)
        
        # Populate mock sqlite database with article and 10 Turkish Q&As
        conn = sqlite3.connect(str(self.db_file))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                filename TEXT,
                title TEXT,
                year INTEGER,
                extracted_text TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER UNIQUE,
                summary TEXT,
                topics TEXT,
                turkish_title TEXT,
                turkish_summary TEXT,
                sft_qa TEXT,
                dpo_pairs TEXT,
                tr_sft_qa TEXT,
                tr_dpo_pairs TEXT,
                processed_at TEXT
            )
        """)
        
        cursor.execute("INSERT INTO articles (id, filename, title, year, extracted_text) VALUES (1, 'mock.pdf', 'ESP32 Wi-Fi Analyzer', 2023, 'Content')")
        
        tr_qa_10 = [{"question": f"ESP32 ile ilgili soru {i+1}?", "answer": f"ESP32 mikrokontrolcü detayı cevabı {i+1}."} for i in range(10)]
        tr_dpo_1 = [{"question": "ESP32 SPI pin seçimi nasıl olmalıdır?", "chosen": "SPI pinleri doğrudan ESP32 GPIO matrisi üzerinden konfigüre edilebilir.", "rejected": "SPI pinleri rastgele seçilip pull-up direnci olmadan kullanılmalıdır."}]
        
        cursor.execute("""
            INSERT INTO enrichments (
                article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs, processed_at
            ) VALUES (1, 'Summary EN', '[]', 'ESP32 Wi-Fi Analizörü', 'ESP32 ile Wi-Fi spektrum analizörü tasarımı.', '[]', '[]', ?, ?, '2026-07-20')
        """, (json.dumps(tr_qa_10, ensure_ascii=False), json.dumps(tr_dpo_1, ensure_ascii=False)))
        
        conn.commit()
        conn.close()
        
        # Run DatasetBuilder with mock config
        builder = DatasetBuilder(config_path=str(self.config_file))
        builder.export_dir = tmp_path / "exports"
        builder.export_dir.mkdir(exist_ok=True)
        builder.export_datasets()
        
        tr_sft_file = builder.export_dir / "tr_sft_dataset.jsonl"
        tr_chat_file = builder.export_dir / "tr_chat_dataset.jsonl"
        tr_dpo_file = builder.export_dir / "tr_dpo_dataset.jsonl"
        
        self.assertTrue(tr_sft_file.exists())
        self.assertTrue(tr_chat_file.exists())
        self.assertTrue(tr_dpo_file.exists())
        
        # Read SFT records
        with open(tr_sft_file, "r", encoding="utf-8") as f:
            sft_lines = f.readlines()
        # 10 Q&As + 1 Summary Q&A = 11 records
        self.assertEqual(len(sft_lines), 11)
        
        # Read Chat records
        with open(tr_chat_file, "r", encoding="utf-8") as f:
            chat_lines = f.readlines()
        self.assertEqual(len(chat_lines), 10)
        
        # Read DPO records
        with open(tr_dpo_file, "r", encoding="utf-8") as f:
            dpo_lines = f.readlines()
        self.assertEqual(len(dpo_lines), 1)
        
        # Verify technical terms in JSONL output
        first_chat = json.loads(chat_lines[0])
        self.assertIn("ESP32", first_chat["messages"][0]["content"])

    def test_bilingual_chat_dataset_isolation(self):
        tmp_path = Path(self.tmpdir.name)
        bilingual_config = dict(self.config)
        bilingual_config["generation_language"] = "bilingual"
        bilingual_config["direct_tr_generation"] = True
        
        bilingual_cfg_file = tmp_path / "bilingual_config.json"
        with open(bilingual_cfg_file, "w", encoding="utf-8") as f:
            json.dump(bilingual_config, f)

        conn = sqlite3.connect(str(self.db_file))
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS articles")
        cursor.execute("DROP TABLE IF EXISTS enrichments")
        cursor.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                filename TEXT,
                title TEXT,
                year INTEGER,
                extracted_text TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER UNIQUE,
                summary TEXT,
                topics TEXT,
                turkish_title TEXT,
                turkish_summary TEXT,
                sft_qa TEXT,
                dpo_pairs TEXT,
                tr_sft_qa TEXT,
                tr_dpo_pairs TEXT,
                multi_turn_chat TEXT,
                tr_multi_turn_chat TEXT,
                processed_at TEXT
            )
        """)
        cursor.execute("INSERT INTO articles (id, filename, title, year, extracted_text) VALUES (1, 'mock.pdf', 'SDR Receiver Design', 2024, 'Content')")
        
        en_chat = [
            {"role": "user", "content": "I want to build a software defined radio receiver."},
            {"role": "assistant", "content": "You will need a sound card and an I-Q mixer."},
            {"role": "user", "content": "How should the mixer pins be connected?"},
            {"role": "assistant", "content": "Pay close attention to the voltage levels."}
        ]
        tr_chat = [
            {"role": "user", "content": "Yazılım tanımlı radyo alıcısı yapmak istiyorum."},
            {"role": "assistant", "content": "Bir ses kartına ve I-Q karıştırıcıya ihtiyacınız olacak."},
            {"role": "user", "content": "Karıştırıcı pinleri nasıl bağlanmalıdır?"},
            {"role": "assistant", "content": "Gerilim seviyelerine dikkat etmelisiniz."}
        ]
        en_qa = [{"question": "What is SDR?", "answer": "Software Defined Radio is a radio communication system."}]
        tr_qa = [{"question": "SDR nedir?", "answer": "Yazılım tanımlı radyo bir haberleşme sistemidir."}]

        cursor.execute("""
            INSERT INTO enrichments (
                article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs, multi_turn_chat, tr_multi_turn_chat, processed_at
            ) VALUES (1, 'Summary in English', '[]', 'SDR Alıcı Tasarımı', 'Türkçe özet metni.', ?, '[]', ?, '[]', ?, ?, '2026-08-21')
        """, (
            json.dumps(en_qa, ensure_ascii=False),
            json.dumps(tr_qa, ensure_ascii=False),
            json.dumps(en_chat, ensure_ascii=False),
            json.dumps(tr_chat, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

        builder = DatasetBuilder(config_path=str(bilingual_cfg_file))
        builder.export_dir = tmp_path / "exports_bilingual"
        builder.export_dir.mkdir(exist_ok=True)
        builder.export_datasets()

        chat_file = builder.export_dir / "chat_dataset.jsonl"
        tr_chat_file = builder.export_dir / "tr_chat_dataset.jsonl"
        sft_file = builder.export_dir / "sft_dataset.jsonl"
        tr_sft_file = builder.export_dir / "tr_sft_dataset.jsonl"

        self.assertTrue(chat_file.exists())
        self.assertTrue(tr_chat_file.exists())
        self.assertTrue(sft_file.exists())
        self.assertTrue(tr_sft_file.exists())

        with open(chat_file, "r", encoding="utf-8") as f:
            en_chat_lines = f.readlines()
        with open(tr_chat_file, "r", encoding="utf-8") as f:
            tr_chat_lines = f.readlines()

        self.assertEqual(len(en_chat_lines), 1)
        self.assertEqual(len(tr_chat_lines), 1)

        en_chat_rec = json.loads(en_chat_lines[0])
        tr_chat_rec = json.loads(tr_chat_lines[0])

        # English chat MUST contain English content and NOT Turkish content
        self.assertIn("software defined radio", en_chat_rec["messages"][0]["content"].lower())
        self.assertNotIn("yazılım tanımlı radyo", en_chat_rec["messages"][0]["content"].lower())

        # Turkish chat MUST contain Turkish content
        self.assertIn("yazılım tanımlı radyo", tr_chat_rec["messages"][0]["content"].lower())
        self.assertNotIn("software defined radio", tr_chat_rec["messages"][0]["content"].lower())

        # SFT datasets isolation
        with open(sft_file, "r", encoding="utf-8") as f:
            en_sft_data = f.read()
        with open(tr_sft_file, "r", encoding="utf-8") as f:
            tr_sft_data = f.read()

        self.assertIn("What is SDR?", en_sft_data)
        self.assertIn("SDR nedir?", tr_sft_data)

    def test_parse_json_robust_clean_and_malformed(self):
        """Tests that parse_json_robust recovers unescaped quotes, LaTeX commands, think tags, and trailing commas without corruption."""
        raw_llm_latex = """<think>
Internal chain of thought reasoning here...
</think>
```json
{
  "title": "ESP32 "ADC" Calibration & Filter",
  "cutoff_formula": "\\(f_c = \\frac{1}{2\\pi R C}\\)",
  "gain": "\\beta = 100",
  "phase": "\\theta = 45^\\circ",
  "time_constant": "\\tau = R \\cdot C",
  "resistance": "R = 10\\ \\text{k}\\Omega",
  "flux": "\\nabla \\times \\mathbf{B} = \\mu_0 \\mathbf{J}",
  "resistivity": "\\rho = 1.68 \\times 10^{-8}",
  "registers": ["GPIO_OE", "SIO_BASE", "FIFO",],
}
```"""
        parsed = ArchiveAnalyzer.parse_json_robust(raw_llm_latex)
        self.assertIsNotNone(parsed)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["title"], 'ESP32 "ADC" Calibration & Filter')
        self.assertIn(r"\frac", parsed["cutoff_formula"])
        self.assertIn(r"\pi", parsed["cutoff_formula"])
        self.assertIn(r"\beta", parsed["gain"])
        self.assertNotIn("\x08", parsed["gain"], "LaTeX \\beta must not be corrupted to ASCII backspace")
        self.assertNotIn("\x0c", parsed["cutoff_formula"], "LaTeX \\frac must not be corrupted to ASCII formfeed")
        self.assertIn(r"\theta", parsed["phase"])
        self.assertIn(r"\tau", parsed["time_constant"])
        self.assertIn(r"\Omega", parsed["resistance"])
        self.assertIn(r"\nabla", parsed["flux"])
        self.assertIn(r"\times", parsed["flux"])
        self.assertIn(r"\rho", parsed["resistivity"])
        self.assertEqual(parsed["registers"], ["GPIO_OE", "SIO_BASE", "FIFO"])

    def test_direct_turkish_prompt_preservation_rules(self):
        """Verifies direct Turkish generation prompt explicitly instructs preservation of registers, protocols, and LaTeX."""
        analyzer = ArchiveAnalyzer(config_path=str(self.config_file))
        
        captured_calls = []
        def mock_call(system_prompt, user_prompt, model=None, keep_alive=None, num_predict=8192):
            captured_calls.append({"system": system_prompt, "user": user_prompt})
            return {
                "turkish_title": "RP2040 GPIO Mimarisi",
                "turkish_summary": "RP2040 GPIO yazmaçları ve SIO yapısı.",
                "topics": ["GPIO", "SIO", "RP2040"],
                "tr_sft_qa": [{"question": "GPIO_OE yazmacı nedir?", "answer": "GPIO_OE çıkış etkinleştirme yazmacıdır."}],
                "tr_dpo_pair": {"question": "I2C pull-up seçimi?", "chosen": "Doğru direnç değeri seçilmelidir.", "rejected": "Pull-up gerekmez."},
                "multi_turn_chat": []
            }
            
        analyzer.call_ollama_json = mock_call
        res = analyzer.analyze_article_direct_turkish(1, "RP2040 Hardware", "SIO_BASE and GPIO_OE registers in RP2040")
        
        self.assertEqual(len(captured_calls), 1)
        sys_p = captured_calls[0]["system"]
        usr_p = captured_calls[0]["user"]
        
        # Verify hardware registers, protocols, and LaTeX math notation are strictly instructed to be preserved
        self.assertIn("GPIO_OE", sys_p)
        self.assertIn("SIO_BASE", sys_p)
        self.assertIn("I2C", sys_p)
        self.assertIn("SPI", sys_p)
        self.assertIn("MOSFET", sys_p)
        self.assertIn("Op-Amp", sys_p)
        self.assertIn(r"LaTeX", sys_p)
        self.assertIn(r"LaTeX", usr_p)
        self.assertIn("KESİN NEGATİF KURAL", usr_p)
        analyzer.close()

    def test_translate_enrichments_to_turkish_preservation_rules(self):
        """Verifies translate_enrichments_to_turkish system prompt enforces strict register, protocol, and LaTeX preservation."""
        analyzer = ArchiveAnalyzer(config_path=str(self.config_file))
        
        captured_messages = []
        def mock_chat(model, messages, options=None, keep_alive=None):
            captured_messages.extend(messages)
            return {
                "message": {
                    "content": "Title: SPI Veri Yolu\nSummary: SPI mimarisi.\nQ1: SPI frekansı nedir?\nA1: 10 MHz.\nDPO_Q: I2C seçimi?\nDPO_Chosen: Doğru pull-up.\nDPO_Rejected: Yanlış."
                }
            }
            
        analyzer.call_ollama_chat_with_retry = mock_chat
        analyzer.translate_enrichments_to_turkish(
            title="SPI Bus Architecture",
            summary="SPI details and registers",
            sft_qa_raw='[{"question": "What is SPI frequency?", "answer": "10 MHz."}]',
            dpo_pairs_raw='[{"question": "I2C selection?", "chosen": "Proper pull-up.", "rejected": "Wrong."}]'
        )
        
        self.assertTrue(len(captured_messages) >= 2)
        sys_msg = [m["content"] for m in captured_messages if m["role"] == "system"][0]
        
        self.assertIn("HARDWARE REGISTERS & BITFIELDS", sys_msg)
        self.assertIn("GPIO_OE", sys_msg)
        self.assertIn("BUS PROTOCOLS & INTERFACES", sys_msg)
        self.assertIn("I2C, SPI, UART", sys_msg)
        self.assertIn("ELECTRICAL COMPONENTS & UNITS", sys_msg)
        self.assertIn("MOSFET, Op-Amp", sys_msg)
        self.assertIn("LATEX MATHEMATICAL NOTATION", sys_msg)
        analyzer.close()

    def test_colab_ide_notebook_context_prefix_exclusion(self):
        """Verifies Colab IDE notebook generation strips Context: and Bağlam: prefixes in SFT and properly formats DPO."""
        offloader = CloudGPUOffloader(exports_dir=str(self.tmpdir.name))
        
        # Test SFT notebook
        sft_nb = offloader.generate_colab_ide_notebook(project_id="test_m3", base_model="unsloth/Qwen3.5-2B", dataset_type="sft")
        cell5_sft = "".join(sft_nb["cells"][5]["source"])
        self.assertIn("not user_input.startswith('Context:')", cell5_sft)
        self.assertIn("not user_input.startswith('Bağlam:')", cell5_sft)
        
        # Test DPO notebook
        dpo_nb = offloader.generate_colab_ide_notebook(project_id="test_m3", base_model="unsloth/Qwen3.5-2B", dataset_type="dpo")
        cell5_dpo = "".join(dpo_nb["cells"][5]["source"])
        self.assertIn("remove_columns=dataset.column_names", cell5_dpo)
        self.assertIn("not user_input.startswith('Context:')", cell5_dpo)

if __name__ == "__main__":
    unittest.main()
