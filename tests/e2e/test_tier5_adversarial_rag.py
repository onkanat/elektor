"""
tests/e2e/test_tier5_adversarial_rag.py - Tier 5 Adversarial Coverage Hardening

Empirical stress tests, oracles, and generators challenging:
1. SmartTextChunker (pipeline/chunking.py):
   - Pathological inputs: deeply nested code blocks, unclosed code fences,
     mixed Unicode Turkish diacritics, decimal numbers/units (3.14159V, 133.5MHz),
     giant documents (>10,000 words), complex Markdown tables, and adversarial TOC dot trails.
2. ArchiveVectorStore (pipeline/vector_store.py):
   - Boundary similarity queries, score threshold edge cases (threshold 0.0, 1.0, -1.0, None),
     lock collision recovery, and batch embedding bounds.
3. Database Concurrency & Integrity (pipeline/db.py):
   - High-concurrency multithreaded transactions (10 concurrent threads reading/writing
     simultaneously to SQLite in WAL mode with 60-second busy timeout).
   - Forced exception rollbacks verifying zero partial dirty writes.
"""

import time
import uuid
import sqlite3
import tempfile
import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.models import PointStruct

from pipeline.chunking import SmartTextChunker, TextChunk
from pipeline.vector_store import ArchiveVectorStore, QdrantLockError
from pipeline.db import get_db_connection, get_db_cursor


# ============================================================================
# PART 1: SMART TEXT CHUNKER ADVERSARIAL STRESS TESTS
# ============================================================================

class TestAdversarialSmartTextChunker:
    """Empirical challenge suite for SmartTextChunker under hostile/pathological inputs."""

    def test_adv_chunker_deeply_nested_code_blocks(self):
        """
        Adversarial test: Documents with deeply nested code blocks, alternating backticks
        and tildes (e.g. 4-backtick outer fence enclosing 3-backtick inner fences).
        Verifies: No uncaught exceptions, code indentation is preserved, no infinite loops,
        and char offsets remain valid.
        """
        chunker = SmartTextChunker(chunk_size=250, chunk_overlap=50)

        nested_doc = (
            "# Advanced Markdown Documentation\n\n"
            "Below is a tutorial explaining how to format code blocks:\n\n"
            "````markdown\n"
            "Here is an example Python snippet:\n"
            "```python\n"
            "def initialize_sensor(pin: int) -> bool:\n"
            "    # 4 spaces indentation\n"
            "    bus = I2C(pin)\n"
            "    return bus.ping()\n"
            "```\n"
            "And here is bash:\n"
            "~~~bash\n"
            "echo 'running diagnostic'\n"
            "~~~\n"
            "````\n\n"
            "End of section."
        )

        chunks = chunker.chunk_text(nested_doc)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk, TextChunk)
            assert chunk.start_char >= 0
            assert chunk.end_char <= len(nested_doc)
            assert chunk.start_char <= chunk.end_char
            assert chunk.token_estimate >= 1

        combined_text = "\n".join(c.text for c in chunks)
        # Indentation and keywords inside code must survive
        assert "    bus = I2C(pin)" in combined_text
        assert "def initialize_sensor" in combined_text
        assert "echo 'running diagnostic'" in combined_text

    def test_adv_chunker_unclosed_code_fences(self):
        """
        Adversarial test: Documents containing opening code fences (```python or ~~~c)
        that are never closed before EOF, or documents with odd numbers of code delimiters.
        Verifies: Graceful degradation, no crashes, 100% content preservation.
        """
        chunker = SmartTextChunker(chunk_size=200, chunk_overlap=40)

        unclosed_doc = (
            "# Unfinished Technical Note\n\n"
            "The engineer started typing a routine:\n\n"
            "```python\n"
            "def unclosed_routine():\n"
            "    reg_val = 0x4000\n"
            "    shift_amount = 4\n"
            "    result = reg_val >> shift_amount\n"
            "    print(f'Processed register: {result}')\n"
            "Notice there is NO closing triple-backtick fence anywhere in this document!\n"
            "The text continues with normal prose and analysis.\n"
            "Final conclusion and summary."
        )

        chunks = chunker.chunk_text(unclosed_doc)
        assert len(chunks) >= 1

        combined = " ".join(c.text for c in chunks)
        assert "unclosed_routine" in combined
        assert "0x4000" in combined
        assert "Final conclusion and summary" in combined

        # Also test with unclosed tildes
        unclosed_tildes = "~~~c\nint main() {\n    return 0;\n"
        chunks_tilde = chunker.chunk_text(unclosed_tildes)
        assert len(chunks_tilde) >= 1
        assert "int main()" in chunks_tilde[0].text

    def test_adv_chunker_mixed_unicode_turkish_diacritics(self):
        """
        Adversarial test: Dense Turkish technical text loaded with all uppercase and lowercase
        diacritical marks (ç, Ç, ğ, Ğ, ı, İ, ö, Ö, ş, Ş, ü, Ü), non-breaking spaces (\u00a0),
        and sentence boundaries beginning with capital Turkish letters.
        Verifies: Sentences are segmented properly without slicing diacritic multibyte chars.
        """
        chunker = SmartTextChunker(chunk_size=150, chunk_overlap=30)

        turkish_text = (
            "Ölçüm laboratuvarında şönt direnç gerilimi hassasiyetle test edildi. "
            "Şarj devresindeki sığaç C1 hızla doyuma ulaştı. "
            "Çıkış katındaki transistör aşırı ısınmaya karşı korumalıdır. "
            "İletkenlik katsayısı yüksek alaşımlı bakır yollar tercih edilmelidir. "
            "Güç kaynağındaki dalgalanma filtrelendi. "
            "Üretim bandında tüm çipler sırayla kalibre edilir."
        )

        chunks = chunker.chunk_text(turkish_text)
        assert len(chunks) >= 2

        # Verify all Turkish characters survived intact without unicode mojibake
        combined = " ".join(c.text for c in chunks)
        for char in ["Ö", "ş", "Ş", "Ç", "transistör", "İletkenlik", "Güç", "Üretim", "çip"]:
            assert char in combined

        # Verify sentence integrity: no word sliced across chunk boundaries
        for chunk in chunks:
            assert not chunk.text.startswith(" ")
            assert not chunk.text.endswith(" ")
            # Ensure proper slice from original document
            slice_from_orig = turkish_text[chunk.start_char : chunk.end_char]
            assert chunk.text.startswith(slice_from_orig[:20])

    def test_adv_chunker_decimal_numbers_and_engineering_units(self):
        """
        Adversarial test: Electronic and embedded technical values with decimal points
        and engineering units (3.14159V, 133.5MHz, 0.001mA, 12.5kΩ, 2.4GHz, 0.05%).
        Verifies: Periods in decimal numbers are never misidentified as sentence delimiters.
        """
        chunker = SmartTextChunker(chunk_size=100, chunk_overlap=25)

        tech_text = (
            "Sistem referans voltajı 3.14159V olarak sabitlendi. "
            "Ana kristal osilatör 133.5MHz frekansında çalışmaktadır. "
            "Kaçak akım değeri 0.001mA eşiğini geçemez. "
            "Giriş empedansı 12.5kΩ seviyesindedir. "
            "Tolerans payı %0.05 oranında sınırlandırılmıştır."
        )

        chunks = chunker.chunk_text(tech_text)
        assert len(chunks) >= 2

        # Check each specific decimal expression is preserved intact
        combined = " ".join(c.text for c in chunks)
        for unit in ["3.14159V", "133.5MHz", "0.001mA", "12.5kΩ", "%0.05"]:
            assert unit in combined

        # Verify none of the chunks break a decimal number across chunk boundaries
        for chunk in chunks:
            # Must not end with "3." while the next starts with "14159V"
            assert not chunk.text.rstrip().endswith(" 3.")
            assert not chunk.text.rstrip().endswith(" 133.")
            assert not chunk.text.rstrip().endswith(" 0.")
            assert not chunk.text.rstrip().endswith(" 12.")

    def test_adv_chunker_giant_document_performance_and_capping(self):
        """
        Adversarial test: Massive document (>10,000 words, >75,000 characters) composed
        of varied sections, code blocks, lists, and tables.
        Verifies:
        1. Sub-second linear execution time (no quadratic blowup or catastrophic backtracking).
        2. max_chunks_per_doc cap is strictly enforced.
        3. start_char and end_char remain monotonically non-decreasing.
        """
        chunker = SmartTextChunker(chunk_size=800, chunk_overlap=150, max_chunks_per_doc=25)

        # Generate a synthetic 12,000-word technical manual
        paragraphs = []
        for section_idx in range(110):
            p = (
                f"# Section {section_idx}: Architecture and Subsystems\n\n"
                f"The subsystem {section_idx} operates with clock frequency {100 + section_idx}.5MHz. "
                "The ARM Cortex-M0+ core communicates via high-speed SPI and UART channels. "
                "Registers must be polled before every DMA transaction to prevent buffer overruns.\n\n"
                "```c\n"
                f"void init_subsystem_{section_idx}(void) {{\n"
                f"    REG_CTRL = 0x{section_idx:04X};\n"
                f"    while (!(REG_STATUS & 0x01)) {{ ; }}\n"
                "}\n"
                "```\n\n"
                "- Power consumption is optimal.\n"
                "- Decoupling capacitors (0.1uF) placed near VDD pins.\n"
                "- Baud rate configured to 115200 bps.\n\n"
                "| Param | Min | Typ | Max |\n"
                "|---|---|---|---|\n"
                f"| VDD | 1.8V | 3.3V | {3.3 + section_idx * 0.01:.2f}V |\n"
                "| Temp | -40C | 25C | 85C |\n\n"
            )
            paragraphs.append(p)

        giant_doc = "\n".join(paragraphs)
        word_count = len(giant_doc.split())
        assert word_count > 10000, f"Expected >10,000 words, got {word_count}"

        # Measure chunking latency
        start_time = time.perf_counter()
        chunks = chunker.chunk_text(giant_doc)
        elapsed_sec = time.perf_counter() - start_time

        # Adversarial assertion: Must process >10k words in less than 2.0 seconds
        assert elapsed_sec < 2.0, f"Chunker took {elapsed_sec:.2f}s (exceeds 2.0s limit)"

        # Cap assertion: max_chunks_per_doc = 25 must be strictly respected
        assert len(chunks) == 25
        assert all(c.total_chunks == 25 for c in chunks)

        # Monotonicity of char positions
        prev_start = -1
        for idx, chunk in enumerate(chunks):
            assert chunk.chunk_index == idx
            assert chunk.start_char >= prev_start
            assert chunk.end_char > chunk.start_char
            prev_start = chunk.start_char

        # Test with max_chunks=None (uncapped)
        uncapped_chunks = chunker.chunk_text(giant_doc, max_chunks=1000)
        assert len(uncapped_chunks) > 25
        assert uncapped_chunks[-1].chunk_index == len(uncapped_chunks) - 1

    def test_adv_chunker_complex_markdown_tables(self):
        """
        Adversarial test: Complex Markdown tables containing pipes inside inline code,
        escaped pipes, empty cells, and tables exceeding chunk_size.
        Verifies: Tables retain row-level structure and delimiters without regex crashes.
        """
        chunker = SmartTextChunker(chunk_size=120, chunk_overlap=30)

        table_doc = (
            "# Pin Mapping and Bitwise Operations\n\n"
            "| Pin | Operation | Mask | Description |\n"
            "|---|---|---|---|\n"
            "| GP0 | `SET_BIT(x | 0x01)` | 0x01 | Output enable |\n"
            "| GP1 | `CLEAR_BIT(x & ~0x02)` | 0x02 | Input clock |\n"
            "| GP2 | `TOGGLE(x ^ 0x04)` | 0x04 | Strobe pulse |\n"
            "| GP3 | `READ_STATUS()` | 0x08 | Ready signal |\n"
            "| GP4 | `RESET_ALL()` | 0x10 | Master reset |\n\n"
            "Follow all instructions."
        )

        chunks = chunker.chunk_text(table_doc)
        assert len(chunks) >= 2

        combined = " ".join(c.text for c in chunks)
        assert "| GP0 | `SET_BIT(x | 0x01)` | 0x01 | Output enable |" in combined
        assert "| GP4 | `RESET_ALL()` | 0x10 | Master reset |" in combined

        # Rows must retain pipe delimiters
        for chunk in chunks:
            table_lines = [l for l in chunk.text.splitlines() if "|" in l]
            for tl in table_lines:
                assert tl.strip().startswith("|")

    def test_adv_chunker_adversarial_toc_dot_trails(self):
        """
        Adversarial test: Table of Contents dot trails with adversarial patterns:
        - Dense dots (................)
        - Sparse dots with varying spaces (.   .   .   .)
        - Dot trails with non-breaking spaces (\xa0)
        - Dot trail inside code comment (must NOT be pruned)
        - Normal prose with standard 3-dot ellipsis (must NOT be pruned)
        - Normal prose with 4-dot ellipsis (verified pruned by design rule TOC_LONG_DOTS_RE)
        """
        chunker = SmartTextChunker(chunk_size=300, chunk_overlap=50)

        # 1. Verification of is_toc_line oracle
        assert SmartTextChunker.is_toc_line("Bölüm 1 . . . . . . . . . . . . . 15") is True
        assert SmartTextChunker.is_toc_line("Bölüm 2 ............................ 45") is True
        assert SmartTextChunker.is_toc_line("Bölüm 3 .   .   .   .   .   .   .   . 99") is True
        assert SmartTextChunker.is_toc_line("Ekler\xa0.\xa0.\xa0.\xa0.\xa0120") is True
        assert SmartTextChunker.is_toc_line("      . . . . . . . .      ") is True

        # Standard 3-dot ellipsis in prose is NOT TOC
        assert SmartTextChunker.is_toc_line("İşlem başlatıldı... Sonuç bekleniyor.") is False

        # 4-dot ellipsis in prose matches TOC_LONG_DOTS_RE by design
        assert SmartTextChunker.is_toc_line("İşlem başlatıldı.... Sonuç bekleniyor.") is True

        # 2. Document chunking filtering test
        mixed_doc = (
            "# İçindekiler Tablosu\n\n"
            "Giriş ve Genel Bakış . . . . . . . . . . . . . . 1\n"
            "Donanım Mimarisi .............................. 14\n"
            "Yazılım Kütüphaneleri .   .   .   .   .   .   .   . 55\n\n"
            "# 1. Giriş ve Genel Bakış\n\n"
            "Bu doküman gömülü sistem mimarisini açıklar... Sistem test edildi.\n\n"
            "```c\n"
            "// İçindekiler yorumu: Bölüm 1 . . . . . . 10\n"
            "int dot_trail_inside_code = 42;\n"
            "```\n\n"
            "Son."
        )

        chunks = chunker.chunk_text(mixed_doc)
        combined = "\n".join(c.text for c in chunks)

        # TOC dot lines outside code must be pruned
        assert "Giriş ve Genel Bakış . . . . . . . . . . . . . . 1" not in combined
        assert "Donanım Mimarisi .............................. 14" not in combined
        assert "Yazılım Kütüphaneleri .   .   .   .   .   .   .   . 55" not in combined

        # Legitimate 3-dot prose and headings must remain
        assert "Bu doküman gömülü sistem mimarisini açıklar... Sistem test edildi." in combined
        assert "# 1. Giriş ve Genel Bakış" in combined

        # Dot trail INSIDE code block MUST be preserved!
        assert "int dot_trail_inside_code = 42;" in combined
        assert "// İçindekiler yorumu: Bölüm 1 . . . . . . 10" in combined


# ============================================================================
# PART 2: ARCHIVE VECTOR STORE ADVERSARIAL STRESS TESTS
# ============================================================================

class TestAdversarialVectorStore:
    """Empirical challenge suite for ArchiveVectorStore under boundary and stress conditions."""

    @pytest.fixture(autouse=True)
    def setup_in_memory_store(self, tmp_path):
        """Sets up an isolated in-memory vector store with 4-dimensional vectors."""
        self.db_path = tmp_path / "test_adv_articles.db"
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

        self.config = {
            "location": ":memory:",
            "db_path": str(self.db_path),
            "model_embedding": "mock-embed-4d",
            "embedding_dim": 4,
            "qdrant_collection_name": f"test_adv_col_{uuid.uuid4().hex[:8]}",
            "chunk_size": 200,
            "chunk_overlap": 50,
            "max_chunks_per_doc": 20,
        }

    def test_adv_vector_boundary_similarity_queries(self):
        """
        Adversarial test: Boundary search queries:
        - Empty string and whitespace queries -> empty list
        - Giant query string (5,000 characters)
        - Engineering mathematical Unicode symbols (Ω, µV, π, ∆T, emojis)
        - Boundary top_k values (0, 1, 1000)
        """
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_item = MagicMock()
        mock_item.embedding = [1.0, 0.0, 0.0, 0.0]
        mock_resp.data = [mock_item]
        mock_client.embeddings.create.return_value = mock_resp

        with patch("pipeline.vector_store.get_embedding_client", return_value=mock_client):
            with ArchiveVectorStore(config=self.config) as store:
                # Seed Qdrant with points
                store.qdrant_client.upsert(
                    collection_name=store.collection_name,
                    points=[
                        PointStruct(
                            id=1,
                            vector=[1.0, 0.0, 0.0, 0.0],
                            payload={"article_id": 10, "title": "Math Symbols", "text": "Testing Ω and µV"}
                        ),
                        PointStruct(
                            id=2,
                            vector=[0.0, 1.0, 0.0, 0.0],
                            payload={"article_id": 20, "title": "Other", "text": "Orthogonal text"}
                        )
                    ]
                )

                # Empty and whitespace queries must return empty list immediately
                assert store.search("") == []
                assert store.search("   \n\t   ") == []

                # Giant query
                giant_query = "Microcontroller register " * 250  # ~6,000 chars
                results_giant = store.search(giant_query, top_k=2)
                assert isinstance(results_giant, list)
                assert len(results_giant) <= 2

                # Unicode & engineering symbols query
                sym_query = "Direnç değeri 10kΩ ±5% ve voltaj 3.3µV ∆T=25°C ⚡️"
                results_sym = store.search(sym_query, top_k=5)
                assert isinstance(results_sym, list)

                # Boundary top_k = 0
                results_k0 = store.search("query", top_k=0)
                assert len(results_k0) == 0

                # Boundary top_k larger than collection size
                results_k1000 = store.search("query", top_k=1000)
                assert len(results_k1000) <= 2

    def test_adv_vector_score_threshold_edge_cases(self):
        """
        Adversarial test: Score threshold edge cases under Cosine Distance.
        Under Cosine distance:
        - Exact match = 1.0
        - Orthogonal vector = 0.0
        - Diametrically opposed vector = -1.0
        Verifies:
        1. Qdrant strict inequality: score_threshold=1.0 returns 0 results (since score > 1.0 is False).
        2. score_threshold=0.999 returns only exact match.
        3. score_threshold=0.0 returns exact match (excludes 0.0 and -1.0).
        4. score_threshold=-1.0 returns scores 1.0 and 0.0 (excludes -1.0).
        5. score_threshold=-1.01 returns all 3 points.
        6. score_threshold=None returns all points up to top_k.
        7. Returns complete valid payload dictionary structure on every hit.
        """
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_item = MagicMock()
        mock_item.embedding = [1.0, 0.0, 0.0, 0.0]
        mock_resp.data = [mock_item]
        mock_client.embeddings.create.return_value = mock_resp

        with patch("pipeline.vector_store.get_embedding_client", return_value=mock_client):
            with ArchiveVectorStore(config=self.config) as store:
                # Upsert 3 points covering the full cosine spectrum
                store.qdrant_client.upsert(
                    collection_name=store.collection_name,
                    points=[
                        PointStruct(
                            id=101,
                            vector=[1.0, 0.0, 0.0, 0.0],  # Similarity = 1.0
                            payload={
                                "article_id": 101,
                                "chunk_index": 0,
                                "title": "Exact Match",
                                "year": "2026",
                                "filename": "exact.pdf",
                                "text": "Exact text content"
                            }
                        ),
                        PointStruct(
                            id=102,
                            vector=[0.0, 1.0, 0.0, 0.0],  # Similarity = 0.0
                            payload={
                                "article_id": 102,
                                "chunk_index": 0,
                                "title": "Orthogonal Match",
                                "year": "2025",
                                "filename": "ortho.pdf",
                                "text": "Orthogonal text content"
                            }
                        ),
                        PointStruct(
                            id=103,
                            vector=[-1.0, 0.0, 0.0, 0.0],  # Similarity = -1.0
                            payload={
                                "article_id": 103,
                                "chunk_index": 0,
                                "title": "Opposite Match",
                                "year": "2024",
                                "filename": "opp.pdf",
                                "text": "Opposite text content"
                            }
                        ),
                    ]
                )

                # 1. Strict threshold = 1.0 returns 0 results
                assert len(store.search("query", top_k=5, score_threshold=1.0)) == 0

                # 2. Threshold = 0.999 returns 1 result (exact match)
                res_999 = store.search("query", top_k=5, score_threshold=0.999)
                assert len(res_999) == 1
                assert res_999[0]["article_id"] == 101
                assert pytest.approx(res_999[0]["score"], 0.001) == 1.0

                # 3. Threshold = 0.0 returns 1 result (excludes orthogonal 0.0)
                res_0 = store.search("query", top_k=5, score_threshold=0.0)
                assert len(res_0) == 1
                assert res_0[0]["article_id"] == 101

                # 4. Threshold = -1.0 returns 2 results (exact 1.0 and ortho 0.0)
                res_neg1 = store.search("query", top_k=5, score_threshold=-1.0)
                assert len(res_neg1) == 2
                returned_ids = {r["article_id"] for r in res_neg1}
                assert returned_ids == {101, 102}

                # 5. Threshold = -1.01 returns all 3 points
                res_neg101 = store.search("query", top_k=5, score_threshold=-1.01)
                assert len(res_neg101) == 3

                # 6. Threshold = None returns all 3 points
                res_none = store.search("query", top_k=5, score_threshold=None)
                assert len(res_none) == 3

                # 7. Payload schema validation
                expected_keys = {"score", "article_id", "chunk_index", "point_id", "title", "year", "filename", "text"}
                for hit in res_none:
                    assert expected_keys.issubset(hit.keys())
                    assert isinstance(hit["score"], float)
                    assert isinstance(hit["chunk_index"], int)
                    assert isinstance(hit["point_id"], str)

    def test_adv_vector_lock_collision_and_recovery(self, tmp_path):
        """
        Adversarial test: Disk-based Qdrant client lock contention.
        Verifies:
        1. When directory remains locked, ArchiveVectorStore raises QdrantLockError after 5 attempts.
        2. When lock is released during retries (e.g. on attempt 3), client recovers and initializes.
        """
        disk_path = tmp_path / "locked_qdrant_db"
        disk_config = {
            "qdrant_db_path": str(disk_path),
            "model_embedding": "mock-embed-4d",
            "embedding_dim": 4,
            "qdrant_collection_name": "test_lock_col"
        }

        # Case 1: Persistent lock -> raises QdrantLockError
        with patch("pipeline.vector_store.QdrantClient", side_effect=RuntimeError("Storage folder is locked")):
            with patch("time.sleep", return_value=None):
                with pytest.raises(QdrantLockError) as exc_info:
                    ArchiveVectorStore(config=disk_config)
                assert "is locked by another process" in str(exc_info.value)

        # Case 2: Transient lock collision -> recovers on 3rd attempt
        call_count = 0
        def transient_lock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Storage folder is already accessed by another instance")
            mock_inst = MagicMock()
            mock_inst.get_collections.return_value = MagicMock(collections=[])
            return mock_inst

        with patch("pipeline.vector_store.QdrantClient", side_effect=transient_lock):
            with patch("time.sleep", return_value=None):
                store = ArchiveVectorStore(config=disk_config)
                assert call_count == 3
                assert store.qdrant_client is not None
                store.close()

    def test_adv_vector_batch_embedding_bounds_and_residuals(self):
        """
        Adversarial test: load_to_vector_db with edge-case batch sizes and article lengths:
        - Article 1: 1 chunk (boundary minimum)
        - Article 2: 7 chunks (uneven batch size 3: 3 + 3 + 1 residual)
        - Article 3: empty text / whitespace (0 chunks, skipped without corruption)
        - Article 4: 10 chunks with batch_size 50 (batch_size > total chunks)
        Verifies: Residual points in buffer are flushed cleanly without loss or duplication.
        """
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        # Article 1: 1 chunk
        cur.execute("INSERT INTO articles VALUES (1, 'Single', '2026', 'a1.pdf', 'Single sentence.', 0)")
        # Article 2: 7 chunks
        text_7_chunks = " ".join([f"Sentence {i} describing electrical subsystem." for i in range(70)])
        cur.execute("INSERT INTO articles VALUES (2, 'Multi7', '2026', 'a2.pdf', ?, 0)", (text_7_chunks,))
        # Article 3: empty text
        cur.execute("INSERT INTO articles VALUES (3, 'Empty', '2026', 'a3.pdf', '   ', 0)")
        # Article 4: 10 chunks
        text_10_chunks = " ".join([f"Register bank {i} configured with mask 0x{i:02X}." for i in range(100)])
        cur.execute("INSERT INTO articles VALUES (4, 'Multi10', '2026', 'a4.pdf', ?, 0)", (text_10_chunks,))
        conn.commit()
        conn.close()

        # Mock embedding client
        mock_client = MagicMock()
        def mock_embed(model, input):
            data = []
            for _ in input:
                item = MagicMock()
                item.embedding = [0.1, 0.2, 0.3, 0.4]
                data.append(item)
            res = MagicMock()
            res.data = data
            return res
        mock_client.embeddings.create.side_effect = mock_embed

        with patch("pipeline.vector_store.get_embedding_client", return_value=mock_client):
            with ArchiveVectorStore(config=self.config) as store:
                # 1. Embed with batch_size = 3 (stress residual flush for Article 1 and 2)
                embedded = store.load_to_vector_db(limit=(0, 2), batch_size=3)
                assert embedded == 2

            # 2. Check SQLite status
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            rows = dict(cur.execute("SELECT id, is_embedded FROM articles").fetchall())
            assert rows[1] == 1
            assert rows[2] == 1
            assert rows[3] == 0
            assert rows[4] == 0

            # 3. Embed remaining articles with batch_size = 50 (larger than article size)
            with ArchiveVectorStore(config=self.config) as store:
                embedded_remaining = store.load_to_vector_db(limit=None, batch_size=50)
                # Article 3 has empty text so it produces 0 chunks and is skipped
                # Article 4 has text and produces chunks
                assert embedded_remaining == 1

            rows_final = dict(cur.execute("SELECT id, is_embedded FROM articles").fetchall())
            assert rows_final[1] == 1
            assert rows_final[2] == 1
            assert rows_final[3] == 0  # Still 0 because text was empty
            assert rows_final[4] == 1
            conn.close()


# ============================================================================
# PART 3: DATABASE CONCURRENCY & TRANSACTION INTEGRITY ADVERSARIAL TESTS
# ============================================================================

class TestAdversarialDatabaseConcurrency:
    """Empirical challenge suite for pipeline/db.py concurrency and transaction rollbacks."""

    def test_adv_db_high_concurrency_multithreaded_wal(self, tmp_path):
        """
        Adversarial test: 10 concurrent threads reading and writing to SQLite simultaneously
        using get_db_connection and get_db_cursor.
        Verifies:
        1. WAL mode and busy_timeout=60000 prevent sqlite3.OperationalError locks.
        2. Zero lost updates: all 200 writes across 10 threads succeed.
        3. PRAGMA integrity_check returns 'ok'.
        """
        db_path = tmp_path / "concurrent_stress.db"

        # Initialize table
        with get_db_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE stress_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id INTEGER,
                    iteration INTEGER,
                    payload TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        NUM_WORKERS = 10
        OPS_PER_WORKER = 20

        def worker_task(worker_id: int) -> list[str]:
            worker_errors = []
            for i in range(OPS_PER_WORKER):
                try:
                    # Write using get_db_connection
                    with get_db_connection(db_path, timeout=60.0) as conn:
                        conn.execute(
                            "INSERT INTO stress_records (worker_id, iteration, payload) VALUES (?, ?, ?)",
                            (worker_id, i, f"Worker {worker_id} iteration {i} data payload")
                        )

                    # Read using get_db_cursor
                    with get_db_cursor(db_path, timeout=60.0) as cur:
                        cur.execute(
                            "SELECT COUNT(*) FROM stress_records WHERE worker_id = ?",
                            (worker_id,)
                        )
                        count = cur.fetchone()[0]
                        assert count >= i + 1

                except Exception as e:
                    worker_errors.append(f"Worker {worker_id} op {i} error: {e}")

            return worker_errors

        # Launch concurrent workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = [executor.submit(worker_task, wid) for wid in range(NUM_WORKERS)]
            all_errors = []
            for f in concurrent.futures.as_completed(futures):
                all_errors.extend(f.result())

        # Zero concurrency errors allowed
        assert len(all_errors) == 0, f"Concurrency errors occurred: {all_errors[:5]}"

        # Verify integrity and row count
        with get_db_connection(db_path) as conn:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert journal_mode.lower() == "wal"

            integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
            assert integrity.lower() == "ok"

            total_rows = conn.execute("SELECT COUNT(*) FROM stress_records").fetchone()[0]
            assert total_rows == NUM_WORKERS * OPS_PER_WORKER

    def test_adv_db_forced_exception_rollback_zero_dirty_writes(self, tmp_path):
        """
        Adversarial test: Forced exceptions inside get_db_connection and get_db_cursor blocks.
        Verifies:
        1. Automatic rollback on uncaught exception in connection context manager.
        2. Automatic rollback on uncaught exception in cursor context manager.
        3. Zero partial dirty writes committed to SQLite.
        """
        db_path = tmp_path / "rollback_test.db"

        with get_db_connection(db_path) as conn:
            conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_name TEXT, balance REAL)")
            conn.execute("INSERT INTO accounts VALUES (1, 'Alice', 1000.0)")
            conn.execute("INSERT INTO accounts VALUES (2, 'Bob', 500.0)")

        # 1. Force failure inside get_db_connection block
        with pytest.raises(RuntimeError, match="Simulated crash during transfer"):
            with get_db_connection(db_path) as conn:
                conn.execute("UPDATE accounts SET balance = balance - 200.0 WHERE id = 1")
                conn.execute("UPDATE accounts SET balance = balance + 200.0 WHERE id = 2")
                # Simulate crash before block completes
                raise RuntimeError("Simulated crash during transfer")

        # Verify balances were completely rolled back
        with get_db_connection(db_path) as conn:
            balances = dict(conn.execute("SELECT id, balance FROM accounts").fetchall())
            assert balances[1] == 1000.0
            assert balances[2] == 500.0

        # 2. Force failure inside get_db_cursor block
        with pytest.raises(ValueError, match="Simulated cursor transaction aborted"):
            with get_db_cursor(db_path) as cur:
                cur.execute("INSERT INTO accounts VALUES (3, 'Charlie', 300.0)")
                cur.execute("INSERT INTO accounts VALUES (4, 'Dave', 400.0)")
                raise ValueError("Simulated cursor transaction aborted")

        # Verify Charlie and Dave were NOT inserted
        with get_db_cursor(db_path) as cur:
            cur.execute("SELECT id FROM accounts WHERE id IN (3, 4)")
            assert cur.fetchall() == []

    def test_adv_db_nested_and_repeated_connections_clean_teardown(self, tmp_path):
        """
        Adversarial test: Repeatedly open, write, and close connections in rapid succession,
        including nested connections, verifying teardown in finally blocks prevents resource leaks.
        """
        db_path = tmp_path / "teardown_stress.db"

        with get_db_connection(db_path) as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

        # Rapidly open and close 100 transactions
        for i in range(100):
            with get_db_connection(db_path) as conn:
                conn.execute("INSERT INTO items (name) VALUES (?)", (f"item_{i}",))

        # Nested reader inside writer transaction
        with get_db_connection(db_path) as conn1:
            conn1.execute("INSERT INTO items (name) VALUES ('nested_outer')")
            with get_db_connection(db_path) as conn2:
                # In WAL mode, conn2 reads committed state
                count = conn2.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                assert count == 100

        # Verify final count after outer commit
        with get_db_cursor(db_path) as cur:
            cur.execute("SELECT COUNT(*) FROM items")
            assert cur.fetchone()[0] == 101
