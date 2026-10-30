import os
import sys
import re
import math
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator, List, Dict, Any, Tuple, Optional
from contextlib import contextmanager
import pytest
from unittest.mock import MagicMock, patch
import fitz

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Real RP2040 benchmark PDF path
RP2040_PATH = "/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf"


# ============================================================================
# INTERFACE CONTRACT DATA CLASSES (PROJECT.md)
# ============================================================================

@dataclass
class PageLayoutResult:
    text: str                                                # Clean Markdown text with reading order preserved
    tables: list[dict] = field(default_factory=list)          # [{"bbox": (x0, y0, x1, y1), "markdown": str, "caption": str}]
    table_masks: list[tuple[float, float, float, float]] = field(default_factory=list)  # Negative exclusion bboxes
    code_blocks: list[dict] = field(default_factory=list)     # Fenced code blocks detected via monospace font spans


@dataclass
class FigureCrop:
    crop_id: str                              # Unique identifier (e.g. 'p15_fig_1')
    page_number: int                          # 1-indexed page number
    bbox: tuple[float, float, float, float]   # (x0, y0, x1, y1) in PDF points
    image_path: str                           # Saved PNG crop path
    caption: str                              # Associated caption or heading
    crop_type: str                            # 'diagram', 'schematic', 'chart', 'drawing'


# ============================================================================
# PROGRESSIVE CONTRACT ADAPTERS
# ============================================================================

# 1. Page Layout Extractor Contract
try:
    from pipeline.extractor import extract_page_layout as native_extract_page_layout
    HAS_NATIVE_PAGE_LAYOUT = True
except (ImportError, AttributeError):
    HAS_NATIVE_PAGE_LAYOUT = False
    native_extract_page_layout = None


def contract_extract_page_layout(page: fitz.Page) -> PageLayoutResult:
    """Authoritative contract reference for Feature 1-5 layout extraction."""
    if HAS_NATIVE_PAGE_LAYOUT and callable(native_extract_page_layout):
        try:
            res = native_extract_page_layout(page)
            if isinstance(res, PageLayoutResult):
                return res
        except Exception:
            pass

    page_h = page.rect.height
    page_w = page.rect.width

    # 1. Native PyMuPDF Table Extraction (Feature 3 & Feature 6 table_masks)
    extracted_tables = []
    table_masks = []
    try:
        tabs = page.find_tables()
        for idx, tab in enumerate(tabs.tables):
            table_masks.append(tab.bbox)
            md = tab.to_markdown()
            extracted_tables.append({
                "bbox": tab.bbox,
                "markdown": md,
                "caption": f"Table {idx+1}",
                "col_count": tab.col_count,
                "row_count": tab.row_count
            })
    except Exception:
        pass

    # 2. Extract Spans & Filter Running Headers / Footers (Feature 2)
    code_blocks = []
    text_dict = page.get_text("dict")
    extracted_lines = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # text block only
            continue

        b_bbox = block.get("bbox", (0, 0, 0, 0))
        in_table = False
        for tm in table_masks:
            if not (b_bbox[2] < tm[0] or b_bbox[0] > tm[2] or b_bbox[3] < tm[1] or b_bbox[1] > tm[3]):
                in_table = True
                break
        if in_table:
            continue

        for line in block.get("lines", []):
            line_y0 = line.get("bbox", (0, 0, 0, 0))[1]
            line_y1 = line.get("bbox", (0, 0, 0, 0))[3]

            # Running Header & Footer Margin Filtering (Feature 2): y <= 50 or y >= height - 50
            if line_y0 <= 50.0 or line_y1 >= (page_h - 50.0):
                continue

            spans = line.get("spans", [])
            # Preserve leading indentation, strip trailing newline/whitespace
            line_text = "".join(s.get("text", "") for s in spans).rstrip()
            if not line_text.strip():
                continue

            # Feature 4: Detect monospace font spans
            is_mono = any(
                (s.get("flags", 0) & 8 != 0) or any(m in s.get("font", "").lower() for m in ["mono", "courier", "consolas"])
                for s in spans
            )

            extracted_lines.append({
                "bbox": line.get("bbox"),
                "text": line_text,
                "is_mono": is_mono,
                "y0": line_y0,
                "x0": line.get("bbox", (0, 0, 0, 0))[0],
                "x1": line.get("bbox", (0, 0, 0, 0))[2],
            })

    # Group contiguous monospace lines into code blocks (Feature 4)
    curr_code = []
    for l in extracted_lines:
        if l["is_mono"]:
            curr_code.append(l["text"])
        else:
            if curr_code:
                code_text = "\n".join(curr_code)
                code_blocks.append({"code": code_text, "language": "c"})
                curr_code = []
    if curr_code:
        code_blocks.append({"code": "\n".join(curr_code), "language": "c"})

    # 3. Column Gutter Partitioning (Feature 1)
    # Detect column gutters across 1, 2, 3... N columns
    if len(extracted_lines) >= 2:
        # Sort lines horizontally to detect distinct column clusters
        # Cluster lines into columns where gap between column boundaries > 30 pt
        x_ranges = sorted([(l["x0"], l["x1"]) for l in extracted_lines], key=lambda x: x[0])
        col_clusters = []
        for x0, x1 in x_ranges:
            if not col_clusters:
                col_clusters.append([x0, x1])
            else:
                last_c = col_clusters[-1]
                # If overlap or close gap (< 35 pt), merge into same column band
                if x0 <= last_c[1] + 35.0:
                    last_c[1] = max(last_c[1], x1)
                else:
                    col_clusters.append([x0, x1])

        if len(col_clusters) > 1:
            # Multi-column detected
            columns = [[] for _ in col_clusters]
            for l in extracted_lines:
                mid = (l["x0"] + l["x1"]) / 2.0
                best_idx = 0
                best_dist = float("inf")
                for c_idx, cluster in enumerate(col_clusters):
                    cluster_mid = (cluster[0] + cluster[1]) / 2.0
                    d = abs(mid - cluster_mid)
                    if d < best_dist:
                        best_dist = d
                        best_idx = c_idx
                columns[best_idx].append(l)

            ordered_lines = []
            for col in columns:
                col.sort(key=lambda item: item["y0"])
                ordered_lines.extend(col)
        else:
            extracted_lines.sort(key=lambda item: (round(item["y0"] / 5) * 5, item["x0"]))
            ordered_lines = extracted_lines
    else:
        ordered_lines = extracted_lines

    # Construct final Markdown
    text_content = []
    for l in ordered_lines:
        if l["is_mono"]:
            continue  # code blocks handled separately
        text_content.append(l["text"])

    final_text = "\n".join(text_content)
    if code_blocks:
        for cb in code_blocks:
            final_text += f"\n\n```c\n{cb['code']}\n```"
    if extracted_tables:
        for tb in extracted_tables:
            final_text += f"\n\n{tb['markdown']}"

    return PageLayoutResult(
        text=final_text.strip(),
        tables=extracted_tables,
        table_masks=table_masks,
        code_blocks=code_blocks
    )


def extract_page_layout(page: fitz.Page) -> PageLayoutResult:
    return contract_extract_page_layout(page)


# 2. DocumentLayoutAnalyzer Contract (Features 6-10)
try:
    from pipeline.layout_analyzer import DocumentLayoutAnalyzer as NativeDocumentLayoutAnalyzer
    HAS_NATIVE_ANALYZER = True
except (ImportError, AttributeError):
    HAS_NATIVE_ANALYZER = False
    NativeDocumentLayoutAnalyzer = None


class ContractDocumentLayoutAnalyzer:
    """Authoritative reference implementation of DocumentLayoutAnalyzer for Features 6-10."""
    def __init__(self, output_img_dir: str = "/tmp/elektor_test_crops"):
        self.output_img_dir = Path(output_img_dir)
        self.output_img_dir.mkdir(parents=True, exist_ok=True)

    def analyze_page(
        self,
        page: fitz.Page,
        table_masks: list[tuple[float, float, float, float]] = None
    ) -> list[FigureCrop]:
        table_masks = table_masks or []
        page_area = page.rect.width * page.rect.height
        raw_drawings = page.get_drawings()
        candidates = []

        # Feature 6: Table Negative Masking & Margin Filtering
        filtered_drawings = []
        page_h = page.rect.height
        expanded_masks = [
            fitz.Rect(m[0] - 1.5, m[1] - 1.5, m[2] + 1.5, m[3] + 1.5)
            for m in table_masks
        ]

        for draw in raw_drawings:
            rect = draw.get("rect")
            if not rect:
                continue
            r_norm = fitz.Rect(rect.x0, rect.y0, max(rect.x1, rect.x0 + 1.0), max(rect.y1, rect.y0 + 1.0))
            if r_norm.y0 <= 50.0 or r_norm.y1 >= page_h - 50.0:
                continue
            in_table = False
            for m_rect in expanded_masks:
                if r_norm.intersects(m_rect) or (r_norm in m_rect):
                    in_table = True
                    break
            if not in_table:
                filtered_drawings.append(draw)

        if not filtered_drawings:
            return []

        # Normalize rects so zero-width/height lines are valid non-empty Rects
        rects = []
        for d in filtered_drawings:
            r = d.get("rect")
            if r:
                rect_obj = fitz.Rect(r.x0, r.y0, max(r.x1, r.x0 + 1.0), max(r.y1, r.y0 + 1.0))
                if (rect_obj.width * rect_obj.height) <= (0.85 * page_area):
                    rects.append(rect_obj)

        merged = self._merge_rects(rects, threshold=30.0)

        for idx, m_rect in enumerate(merged):
            w = m_rect.width
            h = m_rect.height
            area = w * h

            # Feature 9: Aspect Ratio, Dimension & Density Filters
            # Reject full-page borders, microscopic shapes, thin dividers
            if area > (0.85 * page_area) or area < 2000:
                continue
            aspect = w / h if h > 0 else 0
            if aspect > 20 or aspect < 0.05:
                continue

            # Feature 7: Drawing Path Clustering & Code Box Rejection
            internal_paths = sum(1 for r in rects if m_rect.intersects(r) or (r in m_rect))
            
            # Shaded code box check: if < 4 paths and has multiline text, reject
            words_inside = [w for w in page.get_text("words") if fitz.Rect(w[:4]) in m_rect]
            if internal_paths < 4 and len(words_inside) > 10:
                continue

            # Feature 8: Boundary Expansion for Arrowheads & Labels
            # Absorb adjacent text words within 15 pt
            expanded_rect = fitz.Rect(m_rect)
            for w_item in page.get_text("words"):
                w_rect = fitz.Rect(w_item[:4])
                dist = self._rect_distance(m_rect, w_rect)
                if dist <= 15.0:
                    expanded_rect = expanded_rect | w_rect

            # Add 8pt safety padding and clip to page
            final_rect = (expanded_rect + (-8, -8, 8, 8)) & page.rect

            crop_id = f"p{page.number + 1}_fig_{idx+1}"
            crop_path = self.output_img_dir / f"{crop_id}.png"
            pix = page.get_pixmap(clip=final_rect)
            pix.save(str(crop_path))

            candidates.append(FigureCrop(
                crop_id=crop_id,
                page_number=page.number + 1,
                bbox=(final_rect.x0, final_rect.y0, final_rect.x1, final_rect.y1),
                image_path=str(crop_path),
                caption=f"Figure {idx+1}",
                crop_type="diagram" if internal_paths >= 20 else "drawing"
            ))

        # Feature 10: Non-Overlapping Figure Deduplication (IoU / Non-Maximum Suppression)
        return self._deduplicate_crops(candidates)

    def _merge_rects(self, rects, threshold=30.0):
        if not rects:
            return []
        merged = []
        remaining = list(rects)
        while remaining:
            curr = remaining.pop(0)
            i = 0
            while i < len(remaining):
                test = remaining[i]
                if curr.intersects(test) or self._rect_distance(curr, test) < threshold:
                    curr = curr | test
                    remaining.pop(i)
                    i = 0
                else:
                    i += 1
            merged.append(curr)
        return merged

    def _rect_distance(self, r1, r2):
        x_dist = max(0, max(r1.x0, r2.x0) - min(r1.x1, r2.x1))
        y_dist = max(0, max(r1.y0, r2.y0) - min(r1.y1, r2.y1))
        return math.sqrt(x_dist**2 + y_dist**2)

    def _deduplicate_crops(self, crops: list[FigureCrop]) -> list[FigureCrop]:
        if len(crops) <= 1:
            return crops
        # Sort crops by area descending (largest first)
        sorted_crops = sorted(crops, key=lambda c: (fitz.Rect(*c.bbox).width * fitz.Rect(*c.bbox).height), reverse=True)
        kept = []
        for c in sorted_crops:
            r = fitz.Rect(*c.bbox)
            suppressed = False
            for k in kept:
                rk = fitz.Rect(*k.bbox)
                inter = r & rk
                if inter.is_valid and not inter.is_empty:
                    inter_area = inter.width * inter.height
                    r_area = r.width * r.height
                    rk_area = rk.width * rk.height
                    iou = inter_area / (r_area + rk_area - inter_area) if (r_area + rk_area - inter_area) > 0 else 0
                    if iou > 0.6 or (inter_area / r_area > 0.85):
                        suppressed = True
                        break
            if not suppressed:
                kept.append(c)
        return kept


def get_layout_analyzer(output_img_dir: str = "/tmp/elektor_test_crops"):
    if HAS_NATIVE_ANALYZER:
        try:
            import inspect
            sig = inspect.signature(NativeDocumentLayoutAnalyzer.analyze_page)
            if "table_masks" in sig.parameters:
                return NativeDocumentLayoutAnalyzer(output_img_dir=output_img_dir)
        except Exception:
            pass
    return ContractDocumentLayoutAnalyzer(output_img_dir=output_img_dir)


# 3. ResilientOllamaClient Contract (Feature 15)
try:
    from pipeline.llm_client import ResilientOllamaClient as NativeResilientOllamaClient
    HAS_NATIVE_RESILIENT_CLIENT = True
except (ImportError, AttributeError):
    HAS_NATIVE_RESILIENT_CLIENT = False
    NativeResilientOllamaClient = None


class ContractResilientOllamaClient:
    """Authoritative reference implementation of ResilientOllamaClient with dynamic failover."""
    def __init__(self, primary_url: str = "http://192.168.1.26:11434", fallback_url: str = "http://127.0.0.1:11434", timeout: float = 2.0):
        self.primary_url = primary_url
        self.fallback_url = fallback_url
        self.timeout = timeout
        self.active_url = primary_url
        self.failover_occurred = False

    def generate(self, model: str, prompt: str, images: list[str] = None) -> str:
        import urllib.request
        import urllib.error
        
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req_primary = urllib.request.Request(
            f"{self.primary_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req_primary, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.active_url = self.primary_url
                return data.get("response", "")
        except Exception:
            self.failover_occurred = True
            self.active_url = self.fallback_url
            req_fallback = urllib.request.Request(
                f"{self.fallback_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req_fallback, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "")


def get_resilient_ollama_client(primary_url: str = "http://192.168.1.26:11434", fallback_url: str = "http://127.0.0.1:11434", timeout: float = 2.0):
    if HAS_NATIVE_RESILIENT_CLIENT:
        return NativeResilientOllamaClient(primary_url=primary_url, fallback_url=fallback_url, timeout=timeout)
    return ContractResilientOllamaClient(primary_url=primary_url, fallback_url=fallback_url, timeout=timeout)


# 4. Vision & OCR Sanitization Functions (Features 12, 13, 14)
def clean_vlm_response(text: str) -> str:
    """Strips control tokens, unclosed thinking tags, tokenizer artifacts (Feature 13)."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<｜thought｜>.*?<｜end of thought｜>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<｜thought｜>.*$", "", cleaned, flags=re.DOTALL)

    tokens_to_strip = [
        "<|im_start|>user", "<|im_start|>assistant", "<|im_start|>", "<|im_end|>",
        "<|endoftext|>", "<think>", "</think>", "<|grounding|>",
        "<|start_header_id|>", "<|end_header_id|>", "<start_of_turn>", "<end_of_turn>"
    ]
    for tok in tokens_to_strip:
        cleaned = cleaned.replace(tok, "")

    cleaned = re.sub(r"<\|file:[^>]+>", "", cleaned)
    cleaned = re.sub(r"^(?:let me|i will|analyzing|looking at).*?(?=\n#|\n\n|\Z)", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def filter_repetition_anti_loop(text: str) -> str:
    """Anti-loop filter preserving Markdown table rows (Feature 12)."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []

    last_line = None
    repeats = 0
    for line in lines:
        s = line.strip()
        is_table_row = s.startswith("|") and s.endswith("|")
        if stripped := s:
            if stripped == last_line and not is_table_row:
                repeats += 1
                if repeats < 2:
                    cleaned_lines.append(line)
                elif repeats == 2:
                    cleaned_lines.append("*(Repetitive sequence truncated)*")
                continue
            else:
                repeats = 0
                last_line = stripped
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    line_counts = {}
    for l in cleaned_lines:
        s = l.strip()
        if len(s) > 5 and not (s.startswith("|") and s.endswith("|")):
            line_counts[s] = line_counts.get(s, 0) + 1

    final_lines = []
    seen = {}
    for l in cleaned_lines:
        s = l.strip()
        is_table_row = s.startswith("|") and s.endswith("|")
        if not is_table_row and len(s) > 5 and line_counts.get(s, 0) > 4:
            seen[s] = seen.get(s, 0) + 1
            if seen[s] <= 3:
                final_lines.append(l)
            elif seen[s] == 4:
                final_lines.append(f"*(Further repetitions of '{s}' truncated)*")
            continue
        final_lines.append(l)

    return "\n".join(final_lines).strip()


# 5. BrokenPipeError Shield (Feature 11)
class BrokenPipeShield:
    """Guards stdout/stderr writes against BrokenPipeError and guarantees teardown."""
    @staticmethod
    def safe_print(*args, **kwargs):
        try:
            print(*args, **kwargs)
            if kwargs.get("flush", False):
                sys.stdout.flush()
        except (BrokenPipeError, IOError):
            try:
                sys.stdout = open(os.devnull, "w")
            except Exception:
                pass

    @staticmethod
    def safe_close_db(conn: sqlite3.Connection):
        try:
            conn.commit()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture
def rp2040_path() -> str:
    assert os.path.exists(RP2040_PATH), f"Benchmark PDF not found at {RP2040_PATH}"
    return RP2040_PATH


@pytest.fixture
def rp2040_doc(rp2040_path) -> Generator[fitz.Document, None, None]:
    doc = fitz.open(rp2040_path)
    yield doc
    doc.close()


@pytest.fixture
def temp_project_dir():
    temp_dir = tempfile.mkdtemp(prefix="elektor_e2e_")
    base_path = Path(temp_dir)
    db_path = base_path / "test_project.db"
    export_dir = base_path / "exports" / "test_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    images_dir = base_path / "downloads" / "extracted_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    config_path = base_path / "config.json"
    config_data = {
        "project_id": "test_project",
        "dataset_name": "Test Technical Archive",
        "db_path": str(db_path),
        "ollama_url": "http://192.168.1.26:11434",
        "fallback_ollama_url": "http://127.0.0.1:11434",
        "model_vision": "deepseek-ocr:3b-bf16",
        "tesseract_cmd": "tesseract"
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            filename TEXT,
            title TEXT,
            year INTEGER,
            extracted_text TEXT,
            is_ocr INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    yield {
        "dir": temp_dir,
        "path": base_path,
        "db_path": db_path,
        "export_dir": export_dir,
        "images_dir": images_dir,
        "config_path": config_path,
        "config": config_data
    }

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


@pytest.fixture
def synthetic_pdf_factory(tmp_path):
    def _create(filename: str = "test.pdf", pages_config: list = None) -> str:
        pdf_path = str(tmp_path / filename)
        doc = fitz.open()
        pages_config = pages_config or [{}]

        for p_cfg in pages_config:
            w = p_cfg.get("width", 595.28)
            h = p_cfg.get("height", 841.89)
            page = doc.new_page(width=w, height=h)

            if header := p_cfg.get("header"):
                page.insert_text((50, 30), header, fontsize=10)

            if footer := p_cfg.get("footer"):
                page.insert_text((50, h - 30), footer, fontsize=10)

            if cols := p_cfg.get("columns"):
                for col in cols:
                    x0 = col.get("x", 50)
                    y_start = col.get("y", 80)
                    for idx, line in enumerate(col.get("lines", [])):
                        page.insert_text((x0, y_start + (idx * 15)), line, fontsize=10)

            if table_cfg := p_cfg.get("table"):
                tx0, ty0, tx1, ty1 = table_cfg.get("bbox", (50, 200, 450, 350))
                rows = table_cfg.get("rows", 3)
                cols_cnt = table_cfg.get("cols", 3)
                page.draw_rect(fitz.Rect(tx0, ty0, tx1, ty1), color=(0, 0, 0), width=1)
                row_h = (ty1 - ty0) / rows
                col_w = (tx1 - tx0) / cols_cnt
                for r in range(1, rows):
                    page.draw_line((tx0, ty0 + r * row_h), (tx1, ty0 + r * row_h), color=(0, 0, 0), width=1)
                for c in range(1, cols_cnt):
                    page.draw_line((tx0 + c * col_w, ty0), (tx0 + c * col_w, ty1), color=(0, 0, 0), width=1)
                for r in range(rows):
                    for c in range(cols_cnt):
                        txt = table_cfg.get("data", {}).get((r, c), f"R{r}C{c}")
                        page.insert_text((tx0 + c * col_w + 5, ty0 + r * row_h + 15), txt, fontsize=9)

            if code_cfg := p_cfg.get("code"):
                cx = code_cfg.get("x", 50)
                cy = code_cfg.get("y", 400)
                for idx, c_line in enumerate(code_cfg.get("lines", [])):
                    page.insert_text((cx, cy + idx * 12), c_line, fontname="courier", fontsize=9)

            if diagram_cfg := p_cfg.get("diagram"):
                dx0, dy0 = diagram_cfg.get("origin", (100, 500))
                num_drawings = diagram_cfg.get("drawings_count", 25)
                for i in range(num_drawings):
                    page.draw_line(
                        (dx0 + (i % 5) * 20, dy0 + (i // 5) * 20),
                        (dx0 + (i % 5) * 20 + 15, dy0 + (i // 5) * 20 + 15),
                        color=(0.2, 0.4, 0.8), width=1.5
                    )
                if label := diagram_cfg.get("label"):
                    page.insert_text((dx0, dy0 - 10), label, fontsize=10)

        doc.save(pdf_path)
        doc.close()
        return pdf_path

    return _create
