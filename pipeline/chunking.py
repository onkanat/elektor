"""
pipeline/chunking.py - Smart Structure-Aware Text Chunker

Implements SmartTextChunker and TextChunk dataclass for high-precision RAG navigation.
Preserves Markdown structures (code blocks, tables, lists, section headers), indentation,
and sentence/word boundaries. Filters out Table of Contents dot trails and empty fragments.
"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    """Represents a structured text chunk with positional and token metadata."""
    text: str
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    token_estimate: int

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return (
            f"TextChunk(index={self.chunk_index}/{self.total_chunks}, "
            f"chars={self.start_char}:{self.end_char}, tokens~{self.token_estimate})"
        )


class SmartTextChunker:
    """
    Structure-aware chunker that divides documents along semantic boundaries:
    1. Code blocks (```...```, ~~~...~~~) are preserved intact with all newlines and indentation.
    2. Markdown tables and lists are preserved without flattening.
    3. Sentence and word boundaries are respected (no mid-sentence or mid-word severing).
    4. Table of Contents dot trails (e.g. '. . . . . . . 373') and empty fragments are pruned.
    5. Capped at configurable max_chunks_per_doc (default 500).
    """

    TOC_DOT_TRAIL_RE = re.compile(r"(?:\.\s*){3,}\s*\d+\s*$", re.MULTILINE)
    TOC_LONG_DOTS_RE = re.compile(r"(?:\.\s*){4,}", re.MULTILINE)
    TOC_PURE_DOTS_RE = re.compile(r"^\s*(?:\.\s*){3,}\s*$", re.MULTILINE)
    CODE_FENCE_RE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")
    SENTENCE_SPLIT_RE = re.compile(
        r"(?<=[.!?])\s+(?=[A-Z0-9ÇĞİÖŞÜ\(\[\"\'\u00c0-\u017e])"
    )

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        max_chunks_per_doc: int = 500,
    ):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks_per_doc = max_chunks_per_doc

    @classmethod
    def is_toc_line(cls, line: str) -> bool:
        """Determines whether a line is a Table of Contents dot trail or leader."""
        cleaned = line.replace("\xa0", " ").strip()
        if not cleaned:
            return False
        if cls.TOC_DOT_TRAIL_RE.search(cleaned):
            return True
        if cls.TOC_LONG_DOTS_RE.search(cleaned):
            return True
        if cls.TOC_PURE_DOTS_RE.search(cleaned):
            return True
        return False

    def chunk_text(self, text: str, max_chunks: int | None = None) -> list[TextChunk]:
        """
        Splits text into a list of TextChunk objects according to interface contract.
        """
        if not text or not text.strip():
            return []

        effective_max = max_chunks if max_chunks is not None else self.max_chunks_per_doc

        # Step 1: Segregate code blocks from general text to protect code formatting
        raw_segments = self.CODE_FENCE_RE.split(text)

        blocks: list[tuple[str, str]] = []  # (block_type, content)
        for segment in raw_segments:
            if not segment:
                continue
            if segment.startswith("```") or segment.startswith("~~~"):
                # Code blocks are preserved exactly as-is
                blocks.append(("code", segment))
            else:
                # Filter out TOC lines outside code blocks
                lines = segment.split("\n")
                filtered_lines = [l for l in lines if not self.is_toc_line(l)]
                cleaned_segment = "\n".join(filtered_lines)

                # Split non-code text by paragraph breaks (double newlines)
                paragraphs = re.split(r"\n\s*\n", cleaned_segment)
                for para in paragraphs:
                    p_str = para.strip()
                    if not p_str:
                        continue

                    # Classify paragraph structure
                    p_lines = [l.strip() for l in p_str.split("\n") if l.strip()]
                    if len(p_lines) >= 2 and all(l.startswith("|") and l.endswith("|") for l in p_lines):
                        blocks.append(("table", p_str))
                    elif p_str.startswith("#"):
                        blocks.append(("header", p_str))
                    elif any(re.match(r"^\s*([-*+]|\d+\.)\s+", l) for l in p_lines):
                        blocks.append(("list", p_str))
                    else:
                        blocks.append(("paragraph", p_str))

        # Step 2: Decompose structural blocks into atomic units
        atomic_units: list[tuple[str, str]] = []  # (unit_text, joining_separator)

        for btype, bcontent in blocks:
            if btype == "code":
                if len(bcontent) <= self.chunk_size:
                    atomic_units.append((bcontent, "\n\n"))
                else:
                    # Oversized code block: split by line breaks to preserve indentation
                    lines = bcontent.split("\n")
                    for line in lines:
                        atomic_units.append((line, "\n"))
            elif btype == "table":
                if len(bcontent) <= self.chunk_size:
                    atomic_units.append((bcontent, "\n\n"))
                else:
                    # Oversized table: split by rows
                    for row in bcontent.split("\n"):
                        if row.strip():
                            atomic_units.append((row, "\n"))
            elif btype == "header":
                atomic_units.append((bcontent, "\n\n"))
            elif btype == "list":
                if len(bcontent) <= self.chunk_size:
                    atomic_units.append((bcontent, "\n\n"))
                else:
                    # Oversized list: split by list items
                    for item in bcontent.split("\n"):
                        if item.strip():
                            atomic_units.append((item, "\n"))
            else:  # General paragraph
                if len(bcontent) <= self.chunk_size:
                    atomic_units.append((bcontent, "\n\n"))
                else:
                    # Oversized paragraph: split along sentence boundaries
                    sentences = self.SENTENCE_SPLIT_RE.split(bcontent)
                    for sentence in sentences:
                        s_clean = sentence.strip()
                        if not s_clean:
                            continue
                        if len(s_clean) <= self.chunk_size:
                            atomic_units.append((s_clean, " "))
                        else:
                            # Oversized sentence: split along word boundaries
                            words = s_clean.split(" ")
                            for word in words:
                                if not word:
                                    continue
                                if len(word) <= self.chunk_size:
                                    atomic_units.append((word, " "))
                                else:
                                    # Monolithic token exceeding chunk_size: slice directly
                                    for i in range(0, len(word), self.chunk_size):
                                        atomic_units.append((word[i : i + self.chunk_size], ""))

        if not atomic_units:
            return []

        # Step 3: Greedily pack atomic units into chunks with overlap
        raw_chunks: list[str] = []
        current_units: list[tuple[str, str]] = []
        current_len = 0

        for unit_text, unit_sep in atomic_units:
            sep = unit_sep if current_units else ""
            added_len = len(sep) + len(unit_text)

            if current_units and (current_len + added_len > self.chunk_size):
                # Emit current chunk
                chunk_str = self._join_units(current_units)
                if chunk_str.strip():
                    raw_chunks.append(chunk_str)

                # Select overlap units from the trailing end of current chunk
                overlap_units: list[tuple[str, str]] = []
                overlap_len = 0
                for u_text, u_sep in reversed(current_units):
                    u_add = len(u_text) + (len(u_sep) if overlap_units else 0)
                    if overlap_len + u_add > self.chunk_overlap and overlap_units:
                        break
                    overlap_units.insert(0, (u_text, u_sep))
                    overlap_len += u_add

                # Guarantee forward progress: overlap cannot contain all units
                if len(overlap_units) >= len(current_units):
                    overlap_units = overlap_units[1:]

                current_units = list(overlap_units)
                current_len = sum(
                    len(u[0]) + (len(u[1]) if i > 0 else 0)
                    for i, u in enumerate(current_units)
                )

                sep = unit_sep if current_units else ""
                current_units.append((unit_text, unit_sep))
                current_len += len(sep) + len(unit_text)
            else:
                current_units.append((unit_text, unit_sep))
                current_len += added_len

        # Emit the trailing chunk
        if current_units:
            chunk_str = self._join_units(current_units)
            if chunk_str.strip():
                raw_chunks.append(chunk_str)

        # Step 4: Enforce max_chunks_per_doc cap
        if len(raw_chunks) > effective_max:
            logger.warning(
                f"Document produced {len(raw_chunks)} chunks, exceeding max_chunks limit of {effective_max}. "
                f"Truncating to {effective_max} chunks."
            )
            raw_chunks = raw_chunks[:effective_max]

        # Step 5: Convert strings to TextChunk dataclasses with positional tracking
        chunks: list[TextChunk] = []
        total_chunks = len(raw_chunks)
        cursor = 0

        for idx, c_str in enumerate(raw_chunks):
            token_estimate = max(1, len(c_str) // 4)
            # Find char position in original text
            probe = c_str[: min(60, len(c_str))]
            found_pos = text.find(probe, cursor)
            if found_pos != -1:
                start_char = found_pos
                end_char = found_pos + len(c_str)
                cursor = start_char + 1
            else:
                start_char = max(0, cursor)
                end_char = start_char + len(c_str)
                cursor = end_char

            chunks.append(
                TextChunk(
                    text=c_str,
                    chunk_index=idx,
                    total_chunks=total_chunks,
                    start_char=start_char,
                    end_char=end_char,
                    token_estimate=token_estimate,
                )
            )

        return chunks

    @staticmethod
    def _join_units(units: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        for i, (u_text, u_sep) in enumerate(units):
            if i > 0:
                parts.append(u_sep)
            parts.append(u_text)
        return "".join(parts).strip()
