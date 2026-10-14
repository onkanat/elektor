"""
tests/test_vector_store.py - Unit and Integration Tests for SmartTextChunker and ArchiveVectorStore

Covers:
1. SmartTextChunker:
   - Markdown code block formatting and indentation preservation
   - Sentence boundary & word boundary preservation (English and Turkish)
   - Markdown tables, headers, and list structure preservation
   - Overlap mechanics and forward progress guarantee
   - Table of Contents dot trail and empty fragment filtering
   - max_chunks_per_doc cap enforcement
   - TextChunk dataclass field validation
2. ArchiveVectorStore:
   - Dual storage mode (in-memory & remote configuration)
   - Elimination of silent :memory: fallback upon lock collision (raises QdrantLockError)
   - Cached embedding dimension
   - Payload index creation for article_id
   - Batched embedding upsert in load_to_vector_db
   - Search with top_k and score_threshold filtering
   - Complete payload field structure in search results
   - Clean client teardown and context manager support
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.chunking import SmartTextChunker, TextChunk
from pipeline.vector_store import ArchiveVectorStore, QdrantLockError


class TestSmartTextChunker(unittest.TestCase):
    """Test suite for the layout-preserving SmartTextChunker."""

    def setUp(self):
        self.chunker = SmartTextChunker(chunk_size=300, chunk_overlap=60, max_chunks_per_doc=10)

    def test_markdown_code_block_preservation(self):
        """Code block indentation, spaces, and newlines must never be flattened or stripped."""
        text = (
            "# Code Example\n"
            "Here is the initialization routine:\n\n"
            "```python\n"
            "def setup_hardware():\n"
            "    # 4 spaces indentation\n"
            "    gpio = Pin(25, Pin.OUT)\n"
            "    for i in range(3):\n"
            "        gpio.high()\n"
            "        time.sleep(0.1)\n"
            "```\n\n"
            "End of setup."
        )
        chunks = self.chunker.chunk_text(text)
        self.assertGreaterEqual(len(chunks), 1)

        code_chunk = None
        for c in chunks:
            if "def setup_hardware():" in c.text:
                code_chunk = c
                break

        self.assertIsNotNone(code_chunk, "Code block was not found in any chunk.")
        # Verify newlines are preserved inside code block
        self.assertIn("\n", code_chunk.text)
        self.assertIn("    # 4 spaces indentation\n", code_chunk.text)
        self.assertIn("        gpio.high()\n", code_chunk.text)
        self.assertIn("```python", code_chunk.text)
        self.assertTrue(code_chunk.text.endswith("End of setup.") or "```" in code_chunk.text)

    def test_markdown_table_and_header_preservation(self):
        """Markdown tables and section headers must retain their structural delimiters."""
        text = (
            "# Pin Configuration\n\n"
            "| Pin | Function | Voltage |\n"
            "|-----|----------|---------|\n"
            "| GP0 | UART0 TX | 3.3V    |\n"
            "| GP1 | UART0 RX | 3.3V    |\n\n"
            "## Summary\n"
            "UART operates at standard baud rates."
        )
        chunks = self.chunker.chunk_text(text)
        self.assertGreaterEqual(len(chunks), 1)

        combined = " ".join(c.text for c in chunks)
        self.assertIn("| Pin | Function | Voltage |", combined)
        self.assertIn("# Pin Configuration", combined)
        self.assertIn("## Summary", combined)

    def test_sentence_and_word_boundaries_english(self):
        """Sentences must not be sliced mid-phrase, and decimal numbers must not trigger splits."""
        chunker = SmartTextChunker(chunk_size=120, chunk_overlap=30)
        text = (
            "The RP2040 chip has dual ARM cores. "
            "The system clock runs at 133.5 MHz! "
            "Internal core voltage is 1.1V for stability. "
            "Memory consists of 264KB SRAM."
        )
        chunks = chunker.chunk_text(text)
        self.assertGreater(len(chunks), 1)

        for c in chunks:
            # No sentence should end with a severed abbreviation or number
            self.assertFalse(c.text.endswith("133."), "Decimal number was mistakenly severed.")
            self.assertFalse(c.text.endswith("1."), "Decimal voltage was mistakenly severed.")
            # Chunks must not end with trailing severed words
            self.assertFalse(c.text.endswith(" ARM"), "Sentence was chopped mid-phrase.")

    def test_sentence_boundaries_turkish(self):
        """Turkish capital letters and syntax must trigger clean sentence boundaries."""
        chunker = SmartTextChunker(chunk_size=110, chunk_overlap=25)
        text = (
            "RP2040 mikrodenetleyicisi çift çekirdekli mimariye sahiptir. "
            "İşlemci saat frekansı 133 MHz değerindedir! "
            "Üretici Raspberry Pi Vakfı olarak bilinir. "
            "Şematik çizimler açık kaynaklıdır."
        )
        chunks = chunker.chunk_text(text)
        self.assertGreater(len(chunks), 1)

        for c in chunks:
            self.assertNotIn("çift çekirdekli mimariye ", [c.text[-25:]])

    def test_chunk_overlap_and_progress(self):
        """Consecutive chunks must share overlap without infinite loops or duplicate chunks."""
        chunker = SmartTextChunker(chunk_size=150, chunk_overlap=40)
        text = (
            "First section contains general introduction to embedded microcontrollers. "
            "Second section elaborates on GPIO registers and pin multiplexing logic. "
            "Third section describes DMA channels and circular ring buffers."
        )
        chunks = chunker.chunk_text(text)
        self.assertGreater(len(chunks), 1)

        # Verify forward progress: chunk texts must be distinct
        for i in range(len(chunks) - 1):
            self.assertNotEqual(chunks[i].text, chunks[i + 1].text)
            self.assertEqual(chunks[i].chunk_index, i)
            self.assertEqual(chunks[i].total_chunks, len(chunks))

    def test_table_of_contents_dot_trail_filtering(self):
        """TOC lines with repeated dot leaders and page numbers must be pruned."""
        text = (
            "# Main Architecture\n"
            "Colophon . . . . . . . . . . . . . . . . . . . . . . . . . . . \xa01\n"
            "5.2.8. BOOTSEL (USB/UART) boot . . . . . . . 373\n"
            ". . . . . . . 45\n"
            "Chapter 1 ................ 12\n"
            "The real content begins here and describes core hardware registers.\n"
            "Registers are mapped to standard memory space."
        )
        chunks = self.chunker.chunk_text(text)
        self.assertGreaterEqual(len(chunks), 1)

        for c in chunks:
            self.assertNotIn("BOOTSEL (USB/UART) boot . . . . . . . 373", c.text)
            self.assertNotIn(". . . . . . . 45", c.text)
            self.assertNotIn("Colophon . . . .", c.text)
            self.assertNotIn("Chapter 1 .....", c.text)
            self.assertIn("The real content begins here", c.text)

    def test_empty_fragment_filtering(self):
        """Empty fragments or text consisting entirely of TOC dots must produce no chunks."""
        text = "\n\n   \n. . . . . . . 12\n\n  . . . . . . . . . . . .   \n\n"
        chunks = self.chunker.chunk_text(text)
        self.assertEqual(chunks, [])

    def test_max_chunks_per_doc_limit(self):
        """Chunks exceeding max_chunks limit must be capped cleanly."""
        chunker = SmartTextChunker(chunk_size=50, chunk_overlap=10, max_chunks_per_doc=3)
        long_text = "Sentence number one. Sentence number two. Sentence number three. Sentence number four. Sentence number five. Sentence number six."
        chunks = chunker.chunk_text(long_text)
        self.assertEqual(len(chunks), 3)
        for c in chunks:
            self.assertEqual(c.total_chunks, 3)

    def test_text_chunk_dataclass_properties(self):
        """TextChunk dataclass fields must conform to interface contracts."""
        chunk = TextChunk(
            text="Sample chunk content.",
            chunk_index=0,
            total_chunks=1,
            start_char=0,
            end_char=21,
            token_estimate=5,
        )
        self.assertEqual(str(chunk), "Sample chunk content.")
        self.assertIn("TextChunk(index=0/1", repr(chunk))
        self.assertEqual(chunk.token_estimate, 5)


class TestArchiveVectorStore(unittest.TestCase):
    """Test suite for the hardened ArchiveVectorStore."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.db_path = self.temp_path / "test_articles.db"

        # Create mock articles SQLite database
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                title TEXT,
                year TEXT,
                filename TEXT,
                extracted_text TEXT,
                is_embedded INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

        self.base_config = {
            "location": ":memory:",
            "db_path": str(self.db_path),
            "model_embedding": "mock-embed",
            "embedding_dim": 4,
            "qdrant_collection_name": "test_elektor_articles",
            "chunk_size": 200,
            "chunk_overlap": 50,
            "max_chunks_per_doc": 10,
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialization_in_memory_and_caching(self):
        """Vector store initializes hermetically in memory and caches embedding dimension."""
        store = ArchiveVectorStore(config=self.base_config)
        try:
            self.assertIsNotNone(store.qdrant_client)
            self.assertEqual(store.embedding_dim, 4)
            # Dimension should be present in class cache
            self.assertEqual(ArchiveVectorStore._dimension_cache.get("mock-embed"), 4)
        finally:
            store.close()

    def test_remote_mode_configuration(self):
        """Vector store recognizes remote qdrant_url and qdrant_api_key."""
        remote_config = dict(self.base_config)
        remote_config["qdrant_url"] = "http://localhost:6333"
        remote_config["qdrant_api_key"] = "secret-token"
        del remote_config["location"]

        with patch("pipeline.vector_store.QdrantClient") as mock_qdrant_cls:
            mock_client_instance = MagicMock()
            mock_client_instance.get_collections.return_value = MagicMock(collections=[])
            mock_qdrant_cls.return_value = mock_client_instance

            store = ArchiveVectorStore(config=remote_config)
            mock_qdrant_cls.assert_called_with(
                url="http://localhost:6333",
                api_key="secret-token"
            )
            store.close()

    def test_lock_collision_raises_qdrant_lock_error(self):
        """Lock collisions on embedded disk storage must raise QdrantLockError, never silently fall back to :memory:."""
        disk_config = dict(self.base_config)
        del disk_config["location"]
        disk_config["qdrant_db_path"] = str(self.temp_path / "locked_qdrant")

        with patch("pipeline.vector_store.QdrantClient", side_effect=RuntimeError("Storage folder is already accessed")):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(QdrantLockError) as cm:
                    ArchiveVectorStore(config=disk_config)
                self.assertIn("already accessed", str(cm.exception))

    @patch("pipeline.vector_store.get_embedding_client")
    def test_batch_load_to_vector_db(self, mock_get_client):
        """load_to_vector_db must embed in batches of batch_size and mark is_embedded=1."""
        # Insert 2 test articles
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO articles (id, title, year, filename, extracted_text, is_embedded) VALUES (?, ?, ?, ?, ?, ?)",
            (101, "Timer Architecture", "2024", "doc_timer.pdf", "Timer 0 operates with 16-bit prescaler. Timer 1 is high precision.", 0)
        )
        cur.execute(
            "INSERT INTO articles (id, title, year, filename, extracted_text, is_embedded) VALUES (?, ?, ?, ?, ?, ?)",
            (102, "SPI Bus Details", "2024", "doc_spi.pdf", "SPI master supports full duplex transfers at 25 MHz.", 0)
        )
        conn.commit()
        conn.close()

        # Mock embedding client returns 4-dim vectors
        mock_client = MagicMock()
        def mock_embeddings_create(model, input):
            data = []
            for _ in input:
                item = MagicMock()
                item.embedding = [0.1, 0.2, 0.3, 0.4]
                data.append(item)
            res = MagicMock()
            res.data = data
            return res

        mock_client.embeddings.create.side_effect = mock_embeddings_create
        mock_get_client.return_value = mock_client

        store = ArchiveVectorStore(config=self.base_config)
        try:
            embedded_count = store.load_to_vector_db(batch_size=2)
            self.assertEqual(embedded_count, 2)

            # Check SQLite flag updated
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            cur.execute("SELECT id, is_embedded FROM articles ORDER BY id")
            rows = cur.fetchall()
            conn.close()

            self.assertEqual(rows, [(101, 1), (102, 1)])
        finally:
            store.close()

    @patch("pipeline.vector_store.get_embedding_client")
    def test_search_with_top_k_and_score_threshold(self, mock_get_client):
        """Search must apply score_threshold and top_k, returning complete payload dicts."""
        mock_client = MagicMock()
        # Query embedding
        res_query = MagicMock()
        item_q = MagicMock()
        item_q.embedding = [1.0, 0.0, 0.0, 0.0]
        res_query.data = [item_q]
        mock_client.embeddings.create.return_value = res_query
        mock_get_client.return_value = mock_client

        store = ArchiveVectorStore(config=self.base_config)
        try:
            from qdrant_client.models import PointStruct
            # Seed Qdrant with high-similarity point and low-similarity point
            store.qdrant_client.upsert(
                collection_name=store.collection_name,
                points=[
                    PointStruct(
                        id=1,
                        vector=[1.0, 0.0, 0.0, 0.0],  # Cosine sim = 1.0
                        payload={
                            "article_id": 101,
                            "chunk_index": 0,
                            "title": "Exact Match Document",
                            "year": "2024",
                            "filename": "exact.pdf",
                            "text": "This is exact match text."
                        }
                    ),
                    PointStruct(
                        id=2,
                        vector=[0.6, 0.8, 0.0, 0.0],  # Cosine sim = 0.6
                        payload={
                            "article_id": 102,
                            "chunk_index": 0,
                            "title": "Moderate Match Document",
                            "year": "2023",
                            "filename": "moderate.pdf",
                            "text": "Partially relevant content."
                        }
                    ),
                ]
            )

            # Test high threshold (0.80): only exact match should be returned
            results_filtered = store.search("exact match query", top_k=5, score_threshold=0.80)
            self.assertEqual(len(results_filtered), 1)
            hit = results_filtered[0]

            # Verify complete payload fields
            expected_keys = {"score", "article_id", "chunk_index", "point_id", "title", "year", "filename", "text"}
            self.assertTrue(expected_keys.issubset(hit.keys()))
            self.assertEqual(hit["article_id"], 101)
            self.assertEqual(hit["title"], "Exact Match Document")
            self.assertAlmostEqual(hit["score"], 1.0, places=2)

            # Test lower threshold (0.40): both points returned
            results_all = store.search("query", top_k=5, score_threshold=0.40)
            self.assertEqual(len(results_all), 2)

            # Test None threshold: both points returned
            results_none = store.search("query", top_k=5, score_threshold=None)
            self.assertEqual(len(results_none), 2)

            # Test empty query returns empty list
            self.assertEqual(store.search(""), [])
            self.assertEqual(store.search("   "), [])
        finally:
            store.close()

    def test_client_close_and_context_manager(self):
        """Client close must be clean, idempotent, and support context manager protocol."""
        with ArchiveVectorStore(config=self.base_config) as store:
            self.assertIsNotNone(store.qdrant_client)
        # Exited context manager, client should be closed
        self.assertIsNone(store.qdrant_client)

        # Idempotent close
        store.close()
        self.assertIsNone(store.qdrant_client)

    def test_chunk_text_backward_compatibility(self):
        """store.chunk_text returns list[str] preserving newlines, and chunk_text_objects returns TextChunks."""
        store = ArchiveVectorStore(config=self.base_config)
        try:
            sample = "# Title\n\n```python\nimport sys\nprint(1)\n```\n- Item 1\n- Item 2"
            chunks_str = store.chunk_text(sample)
            self.assertIsInstance(chunks_str, list)
            self.assertIsInstance(chunks_str[0], str)
            self.assertIn("\n", chunks_str[0])

            chunks_obj = store.chunk_text_objects(sample)
            self.assertIsInstance(chunks_obj, list)
            self.assertIsInstance(chunks_obj[0], TextChunk)
            self.assertEqual(chunks_obj[0].text, chunks_str[0])
        finally:
            store.close()

    def test_invalid_chunk_size_or_overlap_raises(self):
        """Invalid chunk_size or chunk_overlap >= chunk_size must raise ValueError."""
        with self.assertRaises(ValueError):
            SmartTextChunker(chunk_size=-10)
        with self.assertRaises(ValueError):
            SmartTextChunker(chunk_size=100, chunk_overlap=150)
        with self.assertRaises(ValueError):
            SmartTextChunker(chunk_size=100, chunk_overlap=-1)

    def test_oversized_code_block_splitting(self):
        """Oversized code block splits across line breaks without destroying indentation."""
        chunker = SmartTextChunker(chunk_size=60, chunk_overlap=15)
        code = "```python\ndef calculate(x):\n    step1 = x * 2\n    step2 = step1 + 5\n    return step2\n```"
        chunks = chunker.chunk_text(code)
        self.assertGreater(len(chunks), 1)
        combined = "\n".join(c.text for c in chunks)
        self.assertIn("    step1 = x * 2", combined)
        self.assertIn("    step2 = step1 + 5", combined)

    def test_oversized_table_and_list_splitting(self):
        """Oversized tables and lists split along row/item boundaries."""
        chunker = SmartTextChunker(chunk_size=50, chunk_overlap=10)
        table = "| Col A | Col B |\n|---|---|\n| Val 1 | Val 2 |\n| Val 3 | Val 4 |\n| Val 5 | Val 6 |"
        chunks = chunker.chunk_text(table)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertTrue(any(l.startswith("|") for l in c.text.splitlines()))

    def test_range_limit_and_empty_articles_in_load(self):
        """load_to_vector_db handles range slicing and empty rows cleanly."""
        store = ArchiveVectorStore(config=self.base_config)
        try:
            # Empty database returns 0
            self.assertEqual(store.load_to_vector_db(), 0)
            self.assertEqual(store.load_to_vector_db(limit=(0, 5)), 0)
        finally:
            store.close()

    @patch("pipeline.vector_store.get_embedding_client")
    def test_search_exception_handling(self, mock_get_client):
        """Search failures must log error and return an empty list gracefully."""
        mock_get_client.side_effect = RuntimeError("Embedding service unavailable")
        store = ArchiveVectorStore(config=self.base_config)
        try:
            res = store.search("microcontroller")
            self.assertEqual(res, [])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()

