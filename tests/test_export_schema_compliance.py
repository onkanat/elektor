import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.dataset_builder import DatasetBuilder


class TestExportSchemaCompliance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.db_path = self.tmp_path / "test_compliance.db"
        self.config_path = self.tmp_path / "config.json"

        # Explicitly configure clean_alpaca_input=False to verify that even when False,
        # strict schema enforcement guarantees input: "" with zero static metadata leakage.
        self.cfg = {
            "db_path": str(self.db_path),
            "dataset_name": "Elektor Embedded RP",
            "dataset_name_tr": "Elektor Gömülü RP",
            "generation_language": "bilingual",
            "clean_alpaca_input": False,
            "filter_boilerplate": True
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)

        self._init_database()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                filename TEXT,
                title TEXT,
                year INTEGER,
                zoom_snippet TEXT,
                extracted_text TEXT,
                is_ocr INTEGER DEFAULT 0,
                source_type TEXT DEFAULT 'pdf',
                tags TEXT,
                vote_score INTEGER,
                is_accepted INTEGER DEFAULT 0,
                is_vetoed INTEGER DEFAULT 0,
                metadata_json TEXT,
                processed_at TEXT
            )
        """)

        c.execute("""
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
                is_excluded INTEGER DEFAULT 0,
                processed_at TEXT
            )
        """)

        c.execute("""
            CREATE TABLE synthetic_code_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instruction TEXT,
                input_code TEXT,
                output_response TEXT,
                tr_instruction TEXT,
                tr_output_response TEXT,
                category TEXT
            )
        """)

        conn.commit()
        conn.close()

    def test_standard_sft_and_dpo_schema_invariants(self):
        """Verifies 100% of standard SFT records have input: "" and DPO records match exact triplet keys."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            INSERT INTO articles (id, filename, title, year, extracted_text)
            VALUES (1, 'cortex_m0.pdf', 'ARM Cortex-M0+ Core Architecture', 2026, 'Hardware core architectural overview.')
        """)

        en_sft = [
            {"question": "What is the pipeline depth of Cortex-M0+?", "answer": "It features an ultra-low power 2-stage pipeline."},
            {"question": "How are interrupts handled?", "answer": "Interrupts are handled by the nested vectored interrupt controller (NVIC)."}
        ]
        en_dpo = [
            {
                "question": "Can Cortex-M0+ execute ARM 32-bit instructions?",
                "chosen": "No, it executes the Thumb and Thumb-2 instruction subset.",
                "rejected": "Yes, it supports the full ARM 32-bit instruction set."
            }
        ]
        tr_sft = [
            {"question": "Cortex-M0+ işlemcisinin boru hattı (pipeline) derinliği nedir?", "answer": "2 aşamalı bir boru hattına sahiptir."},
            {"question": "Kesmeler nasıl yönetilir?", "answer": "Kesmeler İç İçe Vektörlü Kesme Denetleyicisi (NVIC) ile yönetilir."}
        ]
        tr_dpo = [
            {
                "question": "Cortex-M0+ çekirdeği ARM 32-bit komut setini çalıştırabilir mi?",
                "chosen": "Hayır, sadece Thumb ve bazı Thumb-2 komutlarını destekler.",
                "rejected": "Evet, tüm ARM 32-bit komutlarını doğrudan çalıştırabilir."
            }
        ]

        c.execute("""
            INSERT INTO enrichments (
                article_id, summary, turkish_title, turkish_summary,
                sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs
            ) VALUES (
                1,
                'Detailed architecture of ARM Cortex-M0+ core with instruction set and NVIC.',
                'ARM Cortex-M0+ Çekirdek Mimarisi',
                'ARM Cortex-M0+ çekirdeğinin NVIC ve komut seti mimarisini inceleyen teknik kılavuz.',
                ?, ?, ?, ?
            )
        """, (
            json.dumps(en_sft, ensure_ascii=False),
            json.dumps(en_dpo, ensure_ascii=False),
            json.dumps(tr_sft, ensure_ascii=False),
            json.dumps(tr_dpo, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

        builder = DatasetBuilder(config_path=str(self.config_path))
        builder.export_dir = self.tmp_path / "exports"
        builder.export_dir.mkdir(exist_ok=True)
        builder.export_datasets()

        # Check English SFT
        en_sft_file = builder.export_dir / "sft_dataset.jsonl"
        self.assertTrue(en_sft_file.exists())
        with open(en_sft_file, "r", encoding="utf-8") as f:
            en_sft_records = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(en_sft_records), 0)
        for rec in en_sft_records:
            self.assertEqual(rec["input"], "", f"SFT record must have empty input: {rec}")
            self.assertIn("instruction", rec)
            self.assertIn("output", rec)
            self.assertNotIn("Context:", rec["input"])
            self.assertNotIn("Context:", rec["output"])
            self.assertNotIn("Bağlam:", rec["input"])
            self.assertNotIn("Bağlam:", rec["output"])

        # Check Turkish SFT
        tr_sft_file = builder.export_dir / "tr_sft_dataset.jsonl"
        self.assertTrue(tr_sft_file.exists())
        with open(tr_sft_file, "r", encoding="utf-8") as f:
            tr_sft_records = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(tr_sft_records), 0)
        for rec in tr_sft_records:
            self.assertEqual(rec["input"], "", f"Turkish SFT record must have empty input: {rec}")
            self.assertIn("instruction", rec)
            self.assertIn("output", rec)
            self.assertNotIn("Context:", rec["input"])
            self.assertNotIn("Context:", rec["output"])
            self.assertNotIn("Bağlam:", rec["input"])
            self.assertNotIn("Bağlam:", rec["output"])

        # Check English DPO
        en_dpo_file = builder.export_dir / "dpo_dataset.jsonl"
        self.assertTrue(en_dpo_file.exists())
        with open(en_dpo_file, "r", encoding="utf-8") as f:
            en_dpo_records = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(en_dpo_records), 0)
        for rec in en_dpo_records:
            self.assertEqual(set(rec.keys()), {"prompt", "chosen", "rejected"},
                             f"DPO record must match exact triplet schema: {rec.keys()}")
            self.assertNotIn("input", rec)
            self.assertNotIn("metadata", rec)

        # Check Turkish DPO
        tr_dpo_file = builder.export_dir / "tr_dpo_dataset.jsonl"
        self.assertTrue(tr_dpo_file.exists())
        with open(tr_dpo_file, "r", encoding="utf-8") as f:
            tr_dpo_records = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(tr_dpo_records), 0)
        for rec in tr_dpo_records:
            self.assertEqual(set(rec.keys()), {"prompt", "chosen", "rejected"},
                             f"Turkish DPO record must match exact triplet schema without metadata: {rec.keys()}")
            self.assertNotIn("input", rec)
            self.assertNotIn("metadata", rec)

    def test_kiwix_sft_and_dpo_schema_invariants(self):
        """Verifies Kiwix StackExchange export strictly enforces input: "" in SFT and exact triplet in DPO."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        kiwix_meta = {
            "tags": ["stm32", "i2c", "dma"],
            "question_body": "Why does STM32 I2C peripheral lock up during DMA transfers on busy bus?",
            "sft_qa": {
                "question": "STM32 I2C DMA lockup causes",
                "answer": "The I2C bus locks when the slave stretches clock while the master DMA is awaiting TXE."
            },
            "dpo_pairs": [
                {
                    "chosen": "Implement timeout logic and generate 9 clock pulses on SCL to clear hung bus.",
                    "rejected": "Restart the entire board using hardware reset whenever I2C locks.",
                    "chosen_score": 15,
                    "rejected_score": -2,
                    "chosen_is_accepted": True
                }
            ]
        }

        c.execute("""
            INSERT INTO articles (
                filename, title, year, source_type, tags, vote_score, is_accepted, metadata_json
            ) VALUES (
                'electronics.stackexchange.zim',
                'STM32 I2C Bus Lockup with DMA',
                2026,
                'stackexchange',
                'stm32, i2c, dma',
                15,
                1,
                ?
            )
        """, (json.dumps(kiwix_meta),))
        conn.commit()
        conn.close()

        builder = DatasetBuilder(config_path=str(self.config_path))
        builder.export_dir = self.tmp_path / "exports"
        builder.export_dir.mkdir(exist_ok=True)
        builder.export_datasets()

        # Check Kiwix SFT export
        sft_file = builder.export_dir / "sft_dataset.jsonl"
        self.assertTrue(sft_file.exists())
        with open(sft_file, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        kiwix_sft = [r for r in records if "STM32 I2C Bus Lockup" in r["instruction"]]
        self.assertEqual(len(kiwix_sft), 1)
        rec = kiwix_sft[0]
        self.assertEqual(rec["input"], "", "Kiwix SFT record must have empty input string")
        self.assertIn("Tags: [stm32, i2c, dma]", rec["instruction"])
        self.assertIn("Why does STM32 I2C peripheral lock up", rec["instruction"])
        self.assertIn("The I2C bus locks", rec["output"])

        # Check Kiwix DPO export
        dpo_file = builder.export_dir / "dpo_dataset.jsonl"
        self.assertTrue(dpo_file.exists())
        with open(dpo_file, "r", encoding="utf-8") as f:
            dpo_records = [json.loads(line) for line in f if line.strip()]

        kiwix_dpo = [r for r in dpo_records if "STM32 I2C" in r["prompt"]]
        self.assertEqual(len(kiwix_dpo), 1)
        d_rec = kiwix_dpo[0]
        self.assertEqual(set(d_rec.keys()), {"prompt", "chosen", "rejected"},
                         f"Kiwix DPO record must contain only triplet keys: {d_rec.keys()}")
        self.assertIn("Tags: [stm32, i2c, dma]", d_rec["prompt"])
        self.assertIn("Why does STM32 I2C peripheral lock up", d_rec["prompt"])
        self.assertNotIn("input", d_rec)
        self.assertNotIn("metadata", d_rec)

    def test_synthetic_code_sft_schema_invariants(self):
        """Verifies Synthetic Code export combines code into instruction and strictly enforces input: ""."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Row 1: with code input
        c.execute("""
            INSERT INTO synthetic_code_pairs (
                instruction, input_code, output_response, tr_instruction, tr_output_response, category
            ) VALUES (
                'Refactor this SPI driver to use hardware DMA buffers.',
                'def send_spi(data):\n    for b in data:\n        spi_write_byte(b)',
                'def send_spi_dma(data):\n    dma_channel.transfer(data)',
                'Bu SPI sürücüsünü donanımsal DMA tamponları kullanacak şekilde refaktör edin.',
                'def send_spi_dma(data):\n    dma_kanali.transfer(data)',
                'bug_fix'
            )
        """)

        # Row 2: without code input (pure instruction)
        c.execute("""
            INSERT INTO synthetic_code_pairs (
                instruction, input_code, output_response, tr_instruction, tr_output_response, category
            ) VALUES (
                'Explain how SPI clock polarity (CPOL) and phase (CPHA) determine sampling edges.',
                '',
                'CPOL sets idle state of SCLK, and CPHA defines whether data is captured on leading or trailing edge.',
                'SPI saat kutupluluğu (CPOL) ve fazının (CPHA) örnekleme kenarlarını nasıl belirlediğini açıklayın.',
                'CPOL boşta bekleme durumunu, CPHA ise verinin yükselen veya düşen kenarda yakalanacağını belirler.',
                'educational'
            )
        """)
        conn.commit()
        conn.close()

        builder = DatasetBuilder(config_path=str(self.config_path))
        builder.export_dir = self.tmp_path / "exports"
        builder.export_dir.mkdir(exist_ok=True)
        builder.export_datasets()

        # Check code_sft_dataset.jsonl and tr_code_sft_dataset.jsonl
        code_file = builder.export_dir / "code_sft_dataset.jsonl"
        tr_code_file = builder.export_dir / "tr_code_sft_dataset.jsonl"
        self.assertTrue(code_file.exists())
        self.assertTrue(tr_code_file.exists())

        with open(code_file, "r", encoding="utf-8") as f:
            code_records = [json.loads(line) for line in f if line.strip()]
        with open(tr_code_file, "r", encoding="utf-8") as f:
            tr_code_records = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(code_records), 2)
        self.assertEqual(len(tr_code_records), 2)

        # 100% of records must have input: ""
        for rec in code_records + tr_code_records:
            self.assertEqual(rec["input"], "", f"Code SFT record must have empty input: {rec}")

        # Record with code has markdown code block in instruction
        self.assertIn("```python\ndef send_spi(data):", code_records[0]["instruction"])
        self.assertIn("```python\ndef send_spi(data):", tr_code_records[0]["instruction"])

        # Record without code has clean instruction
        self.assertNotIn("```python", code_records[1]["instruction"])
        self.assertIn("CPOL", code_records[1]["instruction"])

    def test_targeted_boilerplate_filtering_preserves_synopsys_designware_ip(self):
        """Verifies Synopsys DesignWare hardware IP is preserved while copyright and colophon boilerplate is pruned."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Article 1: Legitimate hardware peripheral documentation mentioning Synopsys DesignWare IP
        c.execute("""
            INSERT INTO articles (id, filename, title, year, extracted_text)
            VALUES (1, 'i2c_controller.pdf', 'I2C Controller Peripheral Architecture', 2026,
                    'The RP2040 integrates two identical instances of the Synopsys DesignWare APB I2C controller IP.')
        """)
        hw_sft = [
            {
                "question": "Which peripheral IP is used for the I2C controllers in the RP2040?",
                "answer": "The RP2040 uses the Synopsys DesignWare APB I2C controller core for both I2C0 and I2C1."
            },
            {
                "question": "How does the flash boot stage initialize the Synopsys DesignWare SSI interface?",
                "answer": "The bootrom configures the Synopsys DesignWare Synchronous Serial Interface (SSI) for quad SPI memory execution."
            }
        ]
        hw_dpo = [
            {
                "question": "Can the Synopsys DesignWare I2C controller operate in high-speed mode?",
                "chosen": "Yes, the Synopsys DesignWare controller supports standard, fast, and high-speed I2C modes up to 3.4MHz.",
                "rejected": "No, it only supports standard 100kHz mode."
            }
        ]
        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (1, 1, 'Architecture and register map of the Synopsys DesignWare I2C peripheral.', ?, ?, 0)
        """, (json.dumps(hw_sft), json.dumps(hw_dpo)))

        # Article 2: Colophon / legal boilerplate with copyright notices
        c.execute("""
            INSERT INTO articles (id, filename, title, year, extracted_text)
            VALUES (2, 'colophon.pdf', 'Datasheet Colophon & Legal Disclaimers', 2026,
                    'Colophon: Portions copyright Synopsys Inc. All rights reserved. Licensed under Creative Commons CC BY-ND 4.0.')
        """)
        legal_sft = [
            {
                "question": "Who owns Synopsys copyright in the documentation?",
                "answer": "Portions copyright Synopsys Inc."
            },
            {
                "question": "What license applies to this datasheet?",
                "answer": "This document is published under Creative Commons CC BY-ND 4.0 license."
            }
        ]
        legal_dpo = [
            {
                "question": "Is the RP2040 warranted for high risk activities?",
                "chosen": "No, the legal disclaimer excludes warranty for high risk activities.",
                "rejected": "Yes, it is warranted for high risk activities."
            }
        ]
        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (2, 2, 'Colophon and legal terms.', ?, ?, 0)
        """, (json.dumps(legal_sft), json.dumps(legal_dpo)))

        conn.commit()
        conn.close()

        builder = DatasetBuilder(config_path=str(self.config_path))
        builder.export_dir = self.tmp_path / "exports"
        builder.export_dir.mkdir(exist_ok=True)

        # Run boilerplate cleaner
        clean_res = builder.clean_database_boilerplate()
        self.assertEqual(clean_res["status"], "success")

        # Verify Article 2 (colophon) is excluded while Article 1 (hardware IP) is NOT excluded
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT article_id, is_excluded FROM enrichments ORDER BY article_id")
        excluded_map = dict(c.fetchall())
        conn.close()

        self.assertEqual(excluded_map[1], 0, "Hardware IP article must NOT be excluded")
        self.assertEqual(excluded_map[2], 1, "Colophon legal article MUST be excluded")

        # Run dataset export
        builder.export_datasets()

        sft_file = builder.export_dir / "sft_dataset.jsonl"
        dpo_file = builder.export_dir / "dpo_dataset.jsonl"
        self.assertTrue(sft_file.exists())
        self.assertTrue(dpo_file.exists())

        with open(sft_file, "r", encoding="utf-8") as f:
            exported_sft = [json.loads(line) for line in f if line.strip()]
        with open(dpo_file, "r", encoding="utf-8") as f:
            exported_dpo = [json.loads(line) for line in f if line.strip()]

        # Verify hardware IP questions are fully preserved in exported datasets
        hw_sft_instructions = [r["instruction"] for r in exported_sft]
        self.assertTrue(any("Synopsys DesignWare" in inst for inst in hw_sft_instructions),
                        "Legitimate Synopsys DesignWare hardware Q&A must be preserved in SFT export")

        hw_dpo_prompts = [r["prompt"] for r in exported_dpo]
        self.assertTrue(any("Synopsys DesignWare" in p for p in hw_dpo_prompts),
                        "Legitimate Synopsys DesignWare hardware Q&A must be preserved in DPO export")

        # Verify legal/colophon items are NOT present in exported datasets
        all_sft_text = " ".join(r["instruction"] + " " + r["output"] for r in exported_sft).lower()
        self.assertNotIn("portions copyright", all_sft_text)
        self.assertNotIn("creative commons", all_sft_text)

        all_dpo_text = " ".join(r["prompt"] + " " + r["chosen"] for r in exported_dpo).lower()
        self.assertNotIn("high risk activities", all_dpo_text)

    def test_direct_boilerplate_text_classifier(self):
        """Direct unit test of is_boilerplate_text classifier patterns."""
        # Genuine technical sentences discussing Synopsys DesignWare hardware IP -> NOT boilerplate
        self.assertFalse(DatasetBuilder.is_boilerplate_text("The RP2040 uses a Synopsys DesignWare APB I2C controller."))
        self.assertFalse(DatasetBuilder.is_boilerplate_text("SSI is based on the Synopsys DesignWare Synchronous Serial Interface."))
        self.assertFalse(DatasetBuilder.is_boilerplate_text("Synopsys DW I2C registers configure SCL clock timing."))

        # True legal / copyright / disclaimer boilerplate -> IS boilerplate
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Portions copyright Synopsys Inc. All rights reserved."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Copyright Synopsys 2026."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Synopsys copyright notice applies to this segment."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Licensed under Creative Commons CC BY-ND 4.0."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("This product is not designed for high risk activities."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Table of Contents for Chapter 2."))
        self.assertTrue(DatasetBuilder.is_boilerplate_text("Fihrist ve İçindekiler bölümü."))


if __name__ == "__main__":
    unittest.main()
