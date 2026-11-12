import os
import csv
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
import pypdf
import pypdfium2 as pdfium
import fitz
import re
from dataclasses import dataclass, field
from datetime import datetime
from PIL import Image, ImageEnhance
from pipeline.project_logger import safe_print, safe_close_db, BrokenPipeShield


def preprocess_image_for_ocr(pil_img: Image.Image) -> Image.Image:
    """Converts image to grayscale, enhances contrast, and applies Otsu-style threshold binarization."""
    if not isinstance(pil_img, Image.Image):
        return pil_img
    gray = pil_img.convert("L")
    try:
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(1.5)
    except Exception:
        enhanced = gray
    try:
        bw = enhanced.point(lambda x: 0 if x < 128 else 255, "1")
        return bw
    except Exception:
        return enhanced



@dataclass
class PageLayoutResult:
    text: str                                  # Clean Markdown text with reading order preserved
    tables: list[dict] = field(default_factory=list)  # Extracted tables: [{"bbox": (x0, y0, x1, y1), "markdown": str, "caption": str}]
    table_masks: list[tuple[float, float, float, float]] = field(default_factory=list)  # Negative exclusion bboxes for visual cropper
    code_blocks: list[dict] = field(default_factory=list)  # Fenced code blocks detected via monospace font spans


def is_mono_font(font: str, flags: int) -> bool:
    """Detects whether a font span is monospace based on flags or font family name."""
    f = (font or "").lower()
    return bool((flags & 8) or any(k in f for k in ["mono", "courier", "consolas", "mplus", "code", "fira", "dejavusansmono"]))


def is_running_header(bbox: tuple[float, float, float, float], text: str, page_height: float) -> bool:
    """Spatially identifies and filters out running headers using coordinates and title patterns."""
    if bbox[3] <= 50.0 or bbox[1] < 45.0:
        return True
    if bbox[1] <= 75.0:
        t = text.strip()
        if re.search(r"RP[0-9]{4}\s+Datasheet", t, re.I):
            return True
        if re.search(r"Raspberry\s+Pi", t, re.I) and len(t) < 40:
            return True
    return False


def is_running_footer(bbox: tuple[float, float, float, float], text: str, page_height: float) -> bool:
    """Spatially identifies and filters out running footers using coordinates and pagination patterns."""
    if bbox[1] >= page_height - 50.0:
        return True
    if bbox[1] >= page_height - 75.0:
        t = text.strip()
        if re.match(r"^\d+$", t) or re.match(r"^[0-9\.]+\s+[\w\s]+\s+\d+$", t):
            return True
    return False


def detect_code_language(code_str: str) -> str:
    """Detects programming language for fenced code blocks."""
    c_indicators = ["#include", "void ", "int ", "uint32_t", "uint16_t", "uint8_t", "struct ", "//", "/*", "dma_", "stdio.h"]
    if any(ind in code_str for ind in c_indicators):
        return "c"
    if any(ind in code_str for ind in ["def ", "import ", "class ", "elif ", "self."]):
        return "python"
    return "c"


def stitch_page_texts(pages: list[str]) -> str:
    """Stitches page texts together, preserving sentence continuity across page splits without injecting header/footer noise."""
    if not pages:
        return ""
    cleaned = [p.strip() for p in pages if p and p.strip()]
    if not cleaned:
        return ""
    result = cleaned[0]
    for nxt in cleaned[1:]:
        res_lines = result.split("\n")
        last_line = res_lines[-1].strip() if res_lines else ""
        nxt_lines = nxt.split("\n")
        first_line = nxt_lines[0].strip() if nxt_lines else ""
        
        is_table = last_line.startswith("|") or first_line.startswith("|")
        is_code = last_line.startswith("```") or first_line.startswith("```")
        is_heading = first_line.startswith("#")
        
        if not (is_table or is_code or is_heading):
            if last_line.endswith("-") and len(last_line) > 1 and last_line[-2].isalpha() and first_line and first_line[0].isalpha():
                result = result[:-1] + nxt
                continue
            elif last_line and last_line[-1] not in (".", "!", "?", ":", ";") and first_line and (first_line[0].islower() or any(first_line.startswith(prefix) for prefix in ["and ", "or ", "the ", "of ", "in ", "to ", "with ", "for ", "by ", "on "])):
                result = result + " " + nxt
                continue
        result = result + "\n\n" + nxt
    return result


def extract_page_layout(page: fitz.Page) -> PageLayoutResult:
    """Extracts text, tables, and exclusion masks from a PDF page using PyMuPDF layout analysis."""
    if not hasattr(page, "find_tables"):
        txt = page.get_text() if hasattr(page, "get_text") else (page.extract_text() if hasattr(page, "extract_text") else "")
        return PageLayoutResult(text=txt or "", tables=[], table_masks=[], code_blocks=[])

    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)

    # 1. Native PyMuPDF table extraction & left-margin / top caption binding
    tabs = page.find_tables().tables
    table_masks: list[tuple[float, float, float, float]] = []
    extracted_tables: list[dict] = []
    consumed_line_bboxes: list[tuple[float, float, float, float]] = []

    blocks = [b for b in page.get_text("blocks") if b[4].strip() and b[1] > 50 and b[3] < height - 50]
    consumed_block_indices: set[int] = set()

    for tab in tabs:
        tx0, ty0, tx1, ty1 = tab.bbox
        t_mask = (float(tx0), float(ty0), float(tx1), float(ty1))
        table_masks.append(t_mask)

        caption_text = ""
        start_idx = None
        min_dist = 999.0
        for i, b in enumerate(blocks):
            if i in consumed_block_indices:
                continue
            txt = b[4].strip()
            if re.search(r"(?:Table|Tablo|Figure|Şekil)\s+\d+", txt, re.I):
                is_left = (b[2] <= tx0 + 25 and abs(b[1] - ty0) <= 45)
                is_above = (b[3] <= ty0 + 10 and b[1] >= ty0 - 50 and b[2] >= tx0 and b[0] <= tx1)
                if is_left or is_above:
                    dist = abs(b[1] - ty0)
                    if dist < min_dist:
                        min_dist = dist
                        start_idx = i

        if start_idx is not None:
            caption_parts = []
            curr_y = blocks[start_idx][1]
            for j in range(start_idx, len(blocks)):
                if j in consumed_block_indices:
                    break
                b = blocks[j]
                if caption_parts and re.search(r"(?:Table|Tablo|Figure|Şekil)\s+\d+", b[4], re.I):
                    break
                if b[2] > tx0 + 25 and b[1] > ty0:
                    break
                if b[1] > ty1 + 15:
                    break
                if b[1] - curr_y > 25:
                    break
                consumed_block_indices.add(j)
                caption_parts.append(b[4].strip())
                consumed_line_bboxes.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
                curr_y = b[3]
            caption_text = " ".join(" ".join(caption_parts).split())

        md = tab.to_markdown().strip()
        formatted_md = f"### {caption_text}\n\n{md}" if caption_text else md
        extracted_tables.append({
            "bbox": t_mask,
            "markdown": formatted_md,
            "caption": caption_text,
            "y0": ty0 if not caption_text else min(ty0, blocks[start_idx][1])
        })

    # 2. Extract spans via dict, filter header/footer and table regions
    d = page.get_text("dict")
    raw_lines: list[dict] = []

    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            l_bbox = (float(l["bbox"][0]), float(l["bbox"][1]), float(l["bbox"][2]), float(l["bbox"][3]))
            txt_preview = "".join(s["text"] for s in l["spans"]).strip()

            # Filter running headers & footers
            if is_running_header(l_bbox, txt_preview, height) or is_running_footer(l_bbox, txt_preview, height):
                continue

            # Check table intersection (exclude table cell lines)
            lx_mid = (l_bbox[0] + l_bbox[2]) / 2
            ly_mid = (l_bbox[1] + l_bbox[3]) / 2
            in_table = any(tx0 <= lx_mid <= tx1 and ty0 <= ly_mid <= ty1 for (tx0, ty0, tx1, ty1) in table_masks)
            if in_table:
                continue

            # Check consumed caption intersection
            in_caption = any(cx0 - 2 <= lx_mid <= cx1 + 2 and cy0 - 2 <= ly_mid <= cy1 + 2 for (cx0, cy0, cx1, cy1) in consumed_line_bboxes)
            if in_caption:
                continue

            total_chars = sum(len(s["text"].strip()) for s in l["spans"])
            mono_chars = sum(len(s["text"].strip()) for s in l["spans"] if is_mono_font(s["font"], s["flags"]))
            is_mono = (total_chars > 0 and (mono_chars / total_chars >= 0.65))

            # Reconstruct inline code spans if line is mixed
            if not is_mono:
                reconstructed_parts = []
                for s in l["spans"]:
                    st = s["text"]
                    if not st:
                        continue
                    if is_mono_font(s["font"], s["flags"]) and len(st.strip()) > 0 and not st.startswith("`") and not st.endswith("`"):
                        clean_tok = st.strip()
                        l_ws = st[:len(st) - len(st.lstrip())]
                        r_ws = st[len(st.rstrip()):]
                        reconstructed_parts.append(f"{l_ws}`{clean_tok}`{r_ws}")
                    else:
                        reconstructed_parts.append(st)
                line_content = "".join(reconstructed_parts).strip()
            else:
                line_content = txt_preview

            raw_lines.append({
                "bbox": l_bbox,
                "text": line_content,
                "is_mono": is_mono,
                "size": max((s.get("size", 10.0) for s in l["spans"]), default=10.0),
                "y0": l_bbox[1],
                "y1": l_bbox[3]
            })

    # 3. Detect & preserve monospace code blocks
    code_blocks: list[list[dict]] = []
    filtered_lines: list[dict] = []
    curr_code_group: list[dict] = []

    for l in raw_lines:
        if l["is_mono"]:
            curr_code_group.append(l)
        else:
            if len(curr_code_group) >= 2 or (len(curr_code_group) == 1 and any(tok in curr_code_group[0]["text"] for tok in ["#include", "dma_", "{", "}", ";"])):
                code_blocks.append(curr_code_group)
            else:
                filtered_lines.extend(curr_code_group)
            curr_code_group = []
            filtered_lines.append(l)
    if len(curr_code_group) >= 2 or (len(curr_code_group) == 1 and any(tok in curr_code_group[0]["text"] for tok in ["#include", "dma_", "{", "}", ";"])):
        code_blocks.append(curr_code_group)
    else:
        filtered_lines.extend(curr_code_group)

    extracted_code_blocks: list[dict] = []
    for grp in code_blocks:
        gx0 = min(l["bbox"][0] for l in grp)
        gy0 = min(l["bbox"][1] for l in grp)
        gx1 = max(l["bbox"][2] for l in grp)
        gy1 = max(l["bbox"][3] for l in grp)

        has_line_nums = sum(1 for l in grp if re.match(r"^[\s\xa0]*\d+[\s\xa0]", l["text"])) >= 0.5 * len(grp)
        cleaned_lines = []
        for l in grp:
            t = l["text"].replace("\xa0", " ")
            if has_line_nums:
                t = re.sub(r"^\s*\d+\s{1,5}", "", t)
            cleaned_lines.append(t)
        code_str = "\n".join(cleaned_lines)
        language = detect_code_language(code_str)
        fenced_md = f"```{language}\n{code_str}\n```"
        extracted_code_blocks.append({
            "bbox": (float(gx0), float(gy0), float(gx1), float(gy1)),
            "code": code_str,
            "language": language,
            "markdown": fenced_md,
            "y0": gy0
        })

    # 4. Column gutter detection via horizontal projection
    bins = [0] * max(1, int(width))
    for l in filtered_lines:
        bb = l["bbox"]
        if (bb[2] - bb[0]) <= 0.60 * width and l.get("size", 10.0) <= 13.0:
            for x in range(max(0, int(bb[0])), min(int(width), int(bb[2]))):
                bins[x] += 1

    gutters: list[tuple[int, int]] = []
    in_gap = False
    start = 0
    for x in range(int(0.15 * width), int(0.85 * width)):
        if bins[x] == 0:
            if not in_gap:
                in_gap = True
                start = x
        else:
            if in_gap:
                in_gap = False
                if x - start >= 12:
                    left_count = sum(1 for l in filtered_lines if l["bbox"][2] <= start + 3.0)
                    right_count = sum(1 for l in filtered_lines if l["bbox"][0] >= x - 3.0)
                    if left_count >= 2 and right_count >= 2:
                        gutters.append((start, x))
    if in_gap and int(0.85 * width) - start >= 12:
        end_x = int(0.85 * width)
        left_count = sum(1 for l in filtered_lines if l["bbox"][2] <= start + 3.0)
        right_count = sum(1 for l in filtered_lines if l["bbox"][0] >= end_x - 3.0)
        if left_count >= 2 and right_count >= 2:
            gutters.append((start, end_x))

    # 5. Build unified layout items and order them
    all_items: list[dict] = []
    for tab_item in extracted_tables:
        all_items.append({"type": "table", "bbox": tab_item["bbox"], "y0": tab_item["y0"], "content": tab_item["markdown"]})
    for cb_item in extracted_code_blocks:
        all_items.append({"type": "code", "bbox": cb_item["bbox"], "y0": cb_item["y0"], "content": cb_item["markdown"]})
    for l_item in filtered_lines:
        all_items.append({"type": "line", "bbox": l_item["bbox"], "y0": l_item["y0"], "content": l_item["text"], "size": l_item.get("size", 10.0)})

    if not gutters:
        sorted_items = sorted(all_items, key=lambda item: item["y0"])
    else:
        g_mids = [(g[0] + g[1]) / 2 for g in gutters]
        primary_gmid = g_mids[0]

        def is_spanning_item(item):
            bb = item["bbox"]
            w = bb[2] - bb[0]
            # Page-spanning banner must either span across more than half the page width
            # or cross directly over a column gutter divider
            if w > 0.50 * width:
                return True
            for gm in g_mids:
                if bb[0] < gm < bb[2]:
                    return True
            return False

        spanning = [item for item in all_items if is_spanning_item(item)]
        non_spanning = [item for item in all_items if not is_spanning_item(item)]

        def get_col_idx(bbox):
            cx = (bbox[0] + bbox[2]) / 2
            for idx, gm in enumerate(g_mids):
                if cx <= gm:
                    return idx
            return len(g_mids)

        bands = []
        assigned_ids = set()
        for span_it in sorted(spanning, key=lambda it: it["y0"]):
            band_items = [it for it in non_spanning if id(it) not in assigned_ids and it["y0"] < span_it["y0"]]
            if band_items:
                for it in band_items:
                    assigned_ids.add(id(it))
                bands.append(("cols", band_items))
            bands.append(("span", [span_it]))

        # All remaining unassigned items in non_spanning are retained without dead-zone dropping
        remaining = [it for it in non_spanning if id(it) not in assigned_ids]
        if remaining:
            bands.append(("cols", remaining))

        sorted_items = []
        for b_type, b_items in bands:
            if b_type == "span":
                sorted_items.extend(b_items)
            else:
                num_cols = len(g_mids) + 1
                for c_idx in range(num_cols):
                    col_items = sorted([it for it in b_items if get_col_idx(it["bbox"]) == c_idx], key=lambda it: it["y0"])
                    sorted_items.extend(col_items)

    # 6. Assemble Markdown
    md_chunks: list[str] = []
    current_para: list[str] = []
    for it in sorted_items:
        if it["type"] in ("table", "code"):
            if current_para:
                md_chunks.append(" ".join(current_para))
                current_para = []
            md_chunks.append(it["content"])
        else:
            txt = it["content"].strip()
            if not txt:
                if current_para:
                    md_chunks.append(" ".join(current_para))
                    current_para = []
                continue
            if re.match(r"^#{1,6}\s+", txt) or it.get("size", 10.0) >= 13.0:
                if current_para:
                    md_chunks.append(" ".join(current_para))
                    current_para = []
                md_chunks.append(txt)
            else:
                if current_para and current_para[-1].endswith("-") and len(current_para[-1]) > 1 and current_para[-1][-2].isalpha() and txt[0].isalpha():
                    current_para[-1] = current_para[-1][:-1] + txt
                else:
                    current_para.append(txt)
    if current_para:
        md_chunks.append(" ".join(current_para))

    full_text = "\n\n".join(md_chunks).strip()
    return PageLayoutResult(
        text=full_text,
        tables=[{"bbox": t["bbox"], "markdown": t["markdown"], "caption": t["caption"]} for t in extracted_tables],
        table_masks=table_masks,
        code_blocks=[{"bbox": cb["bbox"], "code": cb["code"], "language": cb["language"]} for cb in extracted_code_blocks]
    )


class ArchiveExtractor:
    def __init__(self, config_path="config.json", config_dict=None):
        if config_dict is not None:
            self.config = config_dict
            self.config_path = str(config_path) if isinstance(config_path, (str, Path)) else "config.json"
        elif isinstance(config_path, dict):
            self.config = config_path
            self.config_path = "config.json"
        else:
            self.config_path = str(config_path)
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            
        self.input_mode = self.config.get("input_mode", "folder")
        self.raw_input_path = str(self.config.get("input_path", "")).strip()
        if self.raw_input_path.startswith("http://") or self.raw_input_path.startswith("https://") or self.raw_input_path.startswith("git@"):
            self.input_path = self.raw_input_path
            self.articles_dir = Path("downloads/repos")
        elif "input_path" in self.config:
            self.input_path = Path(self.config["input_path"])
            self.articles_dir = self.input_path
        else:
            usb_path = Path(self.config.get("usb_path", "/Volumes/USB DISK"))
            self.input_path = usb_path / "articles"
            self.articles_dir = self.input_path

        
        if "usb_path" in self.config:
            self.csv_path = Path(self.config["usb_path"]) / "lib" / "zoom_pageinfo.csv"
        else:
            self.csv_path = Path("lib/zoom_pageinfo.csv")
            
        self.db_path = self.config.get("db_path", ":memory:")
        if self.db_path != ":memory:":
            db_path_obj = Path(self.db_path)
            if len(db_path_obj.parts) == 1:
                self.db_path = str(Path("database") / self.db_path)
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ocr_threshold = self.config.get("ocr_threshold_chars", 100)
        self.tesseract_cmd = self.config.get("tesseract_cmd", "tesseract")
        # Outline segmentation controls. None/1 preserves the legacy behavior.
        self.outline_max_depth = self.config.get("outline_max_depth")
        if self.outline_max_depth is not None:
            try:
                self.outline_max_depth = max(0, int(self.outline_max_depth))
            except (TypeError, ValueError):
                self.outline_max_depth = None
        try:
            self.min_segment_pages = max(1, int(self.config.get("min_segment_pages", 1)))
        except (TypeError, ValueError):
            self.min_segment_pages = 1
        
        self.enable_vision_ocr = self.config.get("enable_vision_ocr", False)
        if self.enable_vision_ocr:
            from pipeline.layout_analyzer import DocumentLayoutAnalyzer
            from pipeline.vision_ocr import VisionOCRManager
            self.layout_analyzer = DocumentLayoutAnalyzer()
            self.vision_ocr = VisionOCRManager(config_path=config_path)
            
        # Connect/Initialize SQLite database with WAL mode and 60s timeout
        self.conn = sqlite3.connect(self.db_path, timeout=60.0)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=60000;")
        except sqlite3.OperationalError:
            pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                filename TEXT,
                title TEXT,
                year INTEGER,
                zoom_snippet TEXT,
                extracted_text TEXT,
                is_ocr INTEGER,
                is_embedded INTEGER DEFAULT 0,
                processed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS langextract_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                preset TEXT,
                text_span TEXT,
                start_char INTEGER,
                end_char INTEGER,
                attributes TEXT,
                provider TEXT,
                extracted_at TEXT,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            )
        """)
        self.conn.commit()
        
        # Backward compatibility migration for is_embedded column
        try:
            cursor.execute("SELECT is_embedded FROM articles LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE articles ADD COLUMN is_embedded INTEGER DEFAULT 0")
            self.conn.commit()

    def run_langextract_on_article(self, article_id: int, text: str, schema_preset: str = None):
        """Runs LangExtract grounded entity extraction on an article text and stores extractions in SQLite."""
        if not text or not text.strip():
            return
        preset = schema_preset or self.config.get("langextract_schema_preset", "technical_components")
        try:
            from pipeline.langextract_engine import LangExtractEngine
            engine = LangExtractEngine(self.config)
            result = engine.extract_grounded_entities(text=text, schema_preset=preset)
            
            entities = result.get("entities", [])
            provider = result.get("provider", "ollama")
            processed_at = datetime.now().isoformat()
            
            cursor = self.conn.cursor()
            for ent in entities:
                stext = ent.get("text_span", "")
                start = ent.get("start_char", 0)
                end = ent.get("end_char", len(stext))
                attr = json.dumps(ent.get("attributes", {}), ensure_ascii=False)
                
                cursor.execute("""
                    INSERT INTO langextract_extractions (article_id, preset, text_span, start_char, end_char, attributes, provider, extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (article_id, preset, stext, start, end, attr, provider, processed_at))
            self.conn.commit()
            if entities:
                safe_print(f"  [LangExtract] Grounded {len(entities)} entity spans for Article #{article_id} (Preset: '{preset}', Provider: '{provider}').")
        except Exception as e:
            safe_print(f"  [LangExtract Note] Ingestion extraction skipped for Article #{article_id}: {e}")

    def run_langextract_all(self, limit=None):
        """Runs LangExtract on all articles in the database if enable_langextract is True."""
        if not self.config.get("enable_langextract", True):
            return
        
        cursor = self.conn.cursor()
        query = "SELECT id, title, extracted_text FROM articles"
        if isinstance(limit, tuple):
            start, end = limit
            lim_val = (end - start) if end is not None else None
            offset_val = start
            if lim_val is not None:
                query += f" LIMIT {lim_val} OFFSET {offset_val}"
            elif offset_val:
                query += f" LIMIT -1 OFFSET {offset_val}"
        elif isinstance(limit, int):
            query += f" LIMIT {limit}"
        cursor.execute(query)
        articles = cursor.fetchall()
        
        if not articles:
            return
            
        preset = self.config.get("langextract_schema_preset", "technical_components")
        provider = self.config.get("langextract_provider", "ollama")
        safe_print(f"\n🔍 Google LangExtract Entegrasyonu (Grounded Extraction | Provider: '{provider}', Preset: '{preset}')...")
        
        extracted_count = 0
        for art_id, title, text in articles:
            cursor.execute("SELECT COUNT(*) FROM langextract_extractions WHERE article_id = ?", (art_id,))
            if cursor.fetchone()[0] > 0:
                continue
            self.run_langextract_on_article(art_id, text, schema_preset=preset)
            extracted_count += 1
            
        if extracted_count > 0:
            safe_print(f"✅ LangExtract completed for {extracted_count} articles.")

    def load_zoom_metadata(self):
        """Reads zoom_pageinfo.csv and builds a mapping of filename -> zoom snippet & title"""
        metadata = {}
        if not self.csv_path.exists():
            safe_print(f"Warning: CSV metadata not found at {self.csv_path}")
            return metadata
            
        safe_print(f"Loading zoom metadata from {self.csv_path}...")
        with open(self.csv_path, mode='r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 3:
                    continue
                # row[0]: relative path (e.g. "./2022/220267-01.pdf")
                # row[1]: filename (e.g. "220267-01.pdf")
                # row[2]: title/snippet
                filename = row[1]
                snippet = row[2]
                metadata[filename] = snippet
        safe_print(f"Loaded metadata for {len(metadata)} files.")
        return metadata

    def ocr_pdf(self, pdf_path):
        """Renders PDF pages to images and runs Tesseract OCR on them"""
        pdf_path = Path(pdf_path)
        safe_print(f"Running OCR on {pdf_path.name}...")
        ocr_text_parts = []
        try:
            doc = pdfium.PdfDocument(pdf_path)
            for i, page in enumerate(doc):
                # Render page at 300 DPI for high quality OCR
                bitmap = page.render(scale=300/72)
                pil_img = bitmap.to_pil()
                preprocessed_img = preprocess_image_for_ocr(pil_img)
                
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_img_path = tmp_img.name
                    preprocessed_img.save(tmp_img_path)
                    
                with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp_out:
                    tmp_out_path = tmp_out.name
                    
                try:
                    ocr_lang = getattr(self, "ocr_language", None) or self.config.get("ocr_language", "eng")
                    cmd = [self.tesseract_cmd, tmp_img_path, tmp_out_path, "--dpi", "300", "-l", ocr_lang, "--psm", "6"]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode != 0:
                        safe_print(f"  Page {i+1} OCR failed: {result.stderr}")
                        continue
                        
                    txt_path = Path(f"{tmp_out_path}.txt")
                    if txt_path.exists():
                        page_text = txt_path.read_text(encoding='utf-8')
                        txt_path.unlink()
                        ocr_text_parts.append(f"--- Page {i+1} ---\n{page_text.strip()}")
                finally:
                    if os.path.exists(tmp_img_path):
                        os.unlink(tmp_img_path)
                    if os.path.exists(tmp_out_path):
                        os.unlink(tmp_out_path)
            
            return "\n\n".join(ocr_text_parts), True
        except Exception as e:
            safe_print(f"  Error rendering/OCRing {pdf_path}: {e}")
            return "", False

    def clean_ocr_text(self, text):
        """Sanitizes text by replacing common OCR character recognition mistakes, repairing broken word spaces, line hyphens, and cleaning TOC index artifacts."""
        if not text:
            return text
            
        import re
        
        # 1. Repair hyphenated word breaks across lines (e.g. "impa- \n ratorluk" -> "imparatorluk")
        text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
        
        # 2. General Turkish Suffix Re-joining (e.g. "medeni yeti" -> "medeniyeti", "ge nişliği" -> "genişliği")
        # Unambiguous suffixes that are distinctly Turkish
        unambiguous_suffixes = (
            r'lar|ler|lık|lik|luk|lük|mda|mde|nda|nde|nin|nın|nün|nun|'
            r'yu|yü|cı|ci|cu|cü|lüğü|luğu|liğe|liğine|sının|sinin|ları|leri|yeti|yati|liği|lığı'
        )
        turkish_suffix_pattern = re.compile(
            rf'(\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{{3,}})\s+({unambiguous_suffixes})\b',
            re.IGNORECASE
        )
        text = turkish_suffix_pattern.sub(r'\1\2', text)

        # Ambiguous suffixes: ten, tan, den, dan, ya, ye
        # Guard against merging English words (e.g. "pin ten", "for ten", "all ten", "greater tan")
        english_words = {
            "pin", "for", "all", "greater", "less", "hold", "step", "top", "at", "to", "in", "on",
            "and", "is", "was", "with", "by", "see", "wait", "each", "every", "about", "than",
            "line", "channel", "bank", "byte", "bit", "core", "clock", "port", "buffer", "item", "page"
        }
        def _safe_ambiguous_join(match):
            prefix = match.group(1)
            suffix = match.group(2)
            if prefix.lower() in english_words or re.match(r'^\d+$', prefix):
                return match.group(0)
            if any(c in "çğıöşüÇĞİÖŞÜ" for c in prefix):
                return f"{prefix}{suffix}"
            if re.search(r'[çğıöşüÇĞİÖŞÜ]', text):
                return f"{prefix}{suffix}"
            return match.group(0)

        ambiguous_pattern = re.compile(
            r'(\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,})\s+(ten|tan|den|dan|ya|ye)\b',
            re.IGNORECASE
        )
        text = ambiguous_pattern.sub(_safe_ambiguous_join, text)

        # 3. Repair common historical OCR typography mistakes (e.g., İkesuslar -> İksoslar, Teb devri, vb.)
        tr_ocr_corrections = {
            r"\bİke\s*susl?\s*ar?\b": "İksoslar",
            r"\bİkesusla\s*rın\b": "İksosların",
            r"\bTep\s+de\s*vri\b": "Teb devri",
            r"\binh\s*itat\b": "inhitat",
            r"\bBeşin\s+ci\b": "Beşinci",
            r"\bmedeni\s+yeti\b": "medeniyeti",
            r"\bm\s+usiki\b": "musiki",
            r"\bimpa\s*rator\s*luk?\b": "imparatorluk",
            r"\bim\s*paratorlu\s*ğu\b": "imparatorluğu",
            r"\bSan['’\s]*at\s*ler\b": "Sanatları",
            r"\bS\.\s*lll\.\b": "S. III.",
            r"\bM\.\s*E\.\b": "M.Ö.",
        }
        
        for pattern, replacement in tr_ocr_corrections.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
        # 4. Spaced technical & English OCR fixes
        text = text.replace("circu it", "circuit").replace("transi stor", "transistor").replace("resis tor", "resistor").replace("capaci tor", "capacitor")
        
        replacements = {
            r"\bsw1ng1ng\b": "swinging",
            r"\bc1rcu1t\b": "circuit",
            r"\bc1rcu1ts\b": "circuits",
            r"\bd1stortion\b": "distortion",
            r"\bd1g1tal\b": "digital",
            r"\bampl1f1er\b": "amplifier",
            r"\btrans1stor\b": "transistor",
            r"\bres1stor\b": "resistor",
            r"\bcapac1tor\b": "capacitor",
            r"\brnicro\b": "micro",
            r"\bcligital\b": "digital",
            r"\banaclog\b": "analogue",
            r"\bF1gute\b": "Figure",
            r"\bf1gure\b": "figure",
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
        return text

    @staticmethod
    def is_boilerplate_segment(title: str, text: str = "") -> bool:
        """Identifies non-technical front-matter, colophon, and table-of-contents segments."""
        t_low = (title or "").lower().strip()
        if any(k in t_low for k in ["colophon", "table of contents", "içindekiler", "fihrist", "disclaimer", "revision history", "document history"]):
            return True
        prefix = (text or "")[:400].lower()
        if "colophon" in prefix or "creative commons attribution" in prefix or "portions copyright" in prefix:
            return True
        return False

    def parse_printed_toc(self, reader, total_pages):
        """Scans front pages for printed Table of Contents (FİHRİST / İÇİNDEKİLER) with page numbers like 'S. 112', '127-149'"""
        import re
        toc_nodes = []
        # Matches printed TOC lines: "IX - ANADOLU. . 127-149", "S. 112. - İksoslar devri", "A. Etiler imparatorluğu. . . S. 127."
        toc_pattern = re.compile(
            r'([I|V|X]+|[A-Z]|\d+)\s*[\.\-]?\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\-\,\:\'\’]{3,60})[\.\s]*S?\s*[\.\:]?\s*(\d{1,4})',
            re.IGNORECASE
        )
        
        seen_pages = set()
        for page_idx in range(min(total_pages, 25)):
            try:
                page_text = reader.pages[page_idx].extract_text() or ""
                if "İÇİNDEKİLER" in page_text.upper() or "FİHRİST" in page_text.upper() or "FIHRIST" in page_text.upper():
                    lines = [line.strip() for line in page_text.split('\n') if line.strip()]
                    for line in lines:
                        match = toc_pattern.search(line)
                        if match:
                            prefix, title, p_str = match.groups()
                            target_p = int(p_str)
                            if 0 <= target_p <= total_pages and target_p not in seen_pages:
                                seen_pages.add(target_p)
                                full_title = f"{prefix.upper()} - {title.strip()}"
                                toc_nodes.append({"title": full_title[:80], "page": target_p - 1})
            except Exception:
                pass
                
        return toc_nodes

    def detect_scanned_headings(self, reader, total_pages):
        """Scans PDF page text to detect heading titles (e.g. BÖLÜM, KISIM, CHAPTER, 1. GİRİŞ) when digital PDF bookmarks are missing"""
        import re
        
        # 1. First attempt parsing printed Table of Contents page (FİHRİST / İÇİNDEKİLER)
        toc_headings = self.parse_printed_toc(reader, total_pages)
        if toc_headings:
            safe_print(f"Parsed {len(toc_headings)} chapter entries from printed Table of Contents (FİHRİST).")
            return toc_headings

        heading_nodes = []
        # Matches lines like: "BÖLÜM 1: GİRİŞ", "CHAPTER 3", "I. TÜRK TARİHİ", "1. TARİH ÖNCESİ DEVRİLER"
        heading_pattern = re.compile(
            r'^\s*(BÖLÜM|CHAPTER|KISIM|SECTION|PART|[0-9]+\.|[I|V|X]+\.)\s+([A-ZÇĞİÖŞÜ0-9\s\-\.\:\,]{3,80})', 
            re.IGNORECASE
        )
        
        seen_pages = set()
        for page_idx in range(min(total_pages, 200)):
            try:
                page_text = reader.pages[page_idx].extract_text() or ""
                lines = [line.strip() for line in page_text.split('\n') if line.strip()]
                for line in lines[:3]:
                    if heading_pattern.match(line) and page_idx not in seen_pages:
                        seen_pages.add(page_idx)
                        heading_nodes.append({"title": line[:80], "page": page_idx, "depth": 0})
                        break
            except Exception:
                pass
                
        return heading_nodes

    def extract_text_from_pdf(self, pdf_path):
        """Attempts to extract digital text using PyMuPDF layout analysis. If too short, falls back to OCR."""
        text_parts = []
        is_ocr = False
        num_pages = 0
        try:
            doc = fitz.open(pdf_path)
            num_pages = len(doc)
            for page in doc:
                res = extract_page_layout(page)
                if res.text:
                    text_parts.append(res.text.strip())
            doc.close()
            extracted_text = stitch_page_texts(text_parts).strip()
        except Exception as fitz_err:
            try:
                reader = pypdf.PdfReader(pdf_path)
                num_pages = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text.strip())
                extracted_text = "\n\n".join(text_parts).strip()
            except Exception as e:
                safe_print(f"Error extracting text from {pdf_path}: {e}")
                extracted_text = ""

        # If text is too short or empty, perform OCR
        if len(extracted_text) < self.ocr_threshold:
            ocr_text, ocr_success = self.ocr_pdf(pdf_path)
            if ocr_success:
                extracted_text = ocr_text
                is_ocr = True

        if self.enable_vision_ocr and num_pages > 0:
            vision_text = self._process_vision_ocr_for_pages(pdf_path, 0, num_pages - 1)
            if vision_text:
                extracted_text += vision_text

        return extracted_text, is_ocr

    def parse_outline_nodes(self, reader, outline, parent_title="", depth=0):
        """Recursively parses outline nodes into (title, page, depth) dicts.

        ``depth`` is zero for top-level chapters and increases for nested
        sections.  The parent title is attached to child titles so a flattened
        outline stays readable, while the depth lets callers keep only the
        top-level chapter structure.
        """
        nodes = []
        if not outline:
            return nodes

        handled_child_lists = set()
        for idx, item in enumerate(outline):
            if isinstance(item, list):
                if idx not in handled_child_lists:
                    nodes.extend(self.parse_outline_nodes(reader, item, parent_title, depth + 1))
                continue

            title = item.get("/Title", "")
            page_num = None
            try:
                page_num = reader.get_destination_page_number(item)
            except Exception:
                pass

            if page_num is not None:
                full_title = f"{parent_title} - {title}" if parent_title else title
                nodes.append({"title": full_title, "page": page_num, "depth": depth})
                # In a PDF outline a parent destination is followed by its
                # children as a nested list.  Attach that list to this title.
                if idx + 1 < len(outline) and isinstance(outline[idx + 1], list):
                    handled_child_lists.add(idx + 1)
                    nodes.extend(self.parse_outline_nodes(
                        reader, outline[idx + 1], full_title, depth + 1
                    ))
        return nodes

    def extract_pages_range(self, pdf_path, start_page, end_page):
        """Extracts text from a specific page range (0-indexed, inclusive) using PyMuPDF layout analysis. Falls back to OCR if needed."""
        text_parts = []
        is_ocr = False
        total_pages = 0
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            for page_idx in range(start_page, min(end_page + 1, total_pages)):
                res = extract_page_layout(doc[page_idx])
                if res.text:
                    text_parts.append(res.text.strip())
            doc.close()
            extracted_text = stitch_page_texts(text_parts).strip()
        except Exception as fitz_err:
            try:
                reader = pypdf.PdfReader(pdf_path)
                total_pages = len(reader.pages)
                for page_idx in range(start_page, min(end_page + 1, total_pages)):
                    page_text = reader.pages[page_idx].extract_text()
                    if page_text:
                        text_parts.append(page_text.strip())
                extracted_text = "\n\n".join(text_parts).strip()
            except Exception as e:
                safe_print(f"Error extracting range {start_page}-{end_page} from {pdf_path}: {e}")
                extracted_text = ""

        # If text is too short, run OCR on these pages
        if len(extracted_text) < self.ocr_threshold:
            if self.enable_vision_ocr and hasattr(self, 'vision_ocr') and self.vision_ocr:
                # DeepSeek-OCR Hybrid Mode: Convert scanned page images to Markdown for all pages in range (Feature 5)
                safe_print(f"  [DeepSeek-OCR Hybrid] Page text length below threshold ({len(extracted_text)} < {self.ocr_threshold}). Converting document page images to Markdown...")
                rendered_md_parts = []
                max_p = total_pages if total_pages > 0 else (end_page + 1)
                for p_idx in range(start_page, min(end_page + 1, max_p)):
                    page_img_path = self.render_single_page_image(pdf_path, p_idx)
                    if page_img_path and os.path.exists(page_img_path):
                        try:
                            ds_md = self.vision_ocr.convert_document_to_markdown(page_img_path)
                            if ds_md:
                                rendered_md_parts.append(ds_md.strip())
                        finally:
                            if os.path.exists(page_img_path):
                                try:
                                    os.unlink(page_img_path)
                                except Exception:
                                    pass
                if rendered_md_parts:
                    extracted_text = stitch_page_texts(rendered_md_parts)
                    is_ocr = True

            if not is_ocr or not extracted_text:
                ocr_text, ocr_success = self.ocr_pdf_pages(pdf_path, start_page, end_page)
                if ocr_success:
                    extracted_text = ocr_text
                    is_ocr = True

        if self.enable_vision_ocr:
            vision_text = self._process_vision_ocr_for_pages(pdf_path, start_page, end_page)
            if vision_text:
                extracted_text += vision_text

        return extracted_text, is_ocr

    def _process_vision_ocr_for_pages(self, pdf_path, start_page, end_page):
        if not self.enable_vision_ocr:
            return ""
            
        safe_print(f"  [Vision OCR: {self.vision_ocr.model_vision}] Analyzing visual layout on pages {start_page+1}-{end_page+1} of {Path(pdf_path).name}...")
        vision_descriptions = []
        
        for page_idx in range(start_page, end_page + 1):
            elements = self.layout_analyzer.analyze_page(str(pdf_path), page_idx)
            for el in elements:
                img_path = el.get("image_path")
                if img_path and os.path.exists(img_path):
                    context = el.get("context", "")
                    safe_print(f"    [VLM / DeepSeek-OCR] Describing visual zone {el['id']} (caption context: '{context[:45].strip()}...')...")
                    desc = self.vision_ocr.describe_image(img_path, caption_context=context)
                    
                    block_md = (
                        f"\n\n--- [VISUAL & SCHEMATIC CONTENT: Page {page_idx+1} ({el['id']})] ---\n"
                        f"**Element Type**: {el['type'].upper()}\n"
                        f"**Bounding Box**: {el['bbox']}\n"
                        f"**Visual OCR & Diagram Analysis**:\n{desc}\n"
                    )
                    vision_descriptions.append(block_md)
                    
        return "".join(vision_descriptions)

    def render_single_page_image(self, pdf_path, page_idx):
        """Renders a single PDF page at 300 DPI into a temporary PNG file for DeepSeek-OCR analysis."""
        try:
            doc = pdfium.PdfDocument(pdf_path)
            if 0 <= page_idx < len(doc):
                page = doc[page_idx]
                bitmap = page.render(scale=300/72)
                pil_img = bitmap.to_pil()
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_img_path = tmp_img.name
                    pil_img.save(tmp_img_path)
                    return tmp_img_path
        except Exception as e:
            safe_print(f"Warning: Failed to render page {page_idx+1} image from {pdf_path}: {e}")
        return None

    def ocr_pdf_pages(self, pdf_path, start_page, end_page):
        """Renders specific pages of a PDF and runs OCR on them"""
        pdf_path = Path(pdf_path)
        safe_print(f"Running OCR on range {start_page}-{end_page} of {pdf_path.name}...")
        ocr_text_parts = []
        try:
            doc = pdfium.PdfDocument(pdf_path)
            for page_idx in range(start_page, min(end_page + 1, len(doc))):
                page = doc[page_idx]
                bitmap = page.render(scale=300/72)
                pil_img = bitmap.to_pil()
                preprocessed_img = preprocess_image_for_ocr(pil_img)
                
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_img_path = tmp_img.name
                    preprocessed_img.save(tmp_img_path)
                    
                with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp_out:
                    tmp_out_path = tmp_out.name
                    
                try:
                    ocr_lang = getattr(self, "ocr_language", None) or self.config.get("ocr_language", "eng")
                    cmd = [self.tesseract_cmd, tmp_img_path, tmp_out_path, "--dpi", "300", "-l", ocr_lang, "--psm", "6"]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode != 0:
                        safe_print(f"  Page {page_idx+1} OCR failed: {result.stderr}")
                        continue
                        
                    txt_path = Path(f"{tmp_out_path}.txt")
                    if txt_path.exists():
                        page_text = txt_path.read_text(encoding='utf-8')
                        txt_path.unlink()
                        ocr_text_parts.append(f"--- Page {page_idx+1} ---\n{page_text.strip()}")
                finally:
                    if os.path.exists(tmp_img_path):
                        os.unlink(tmp_img_path)
                    if os.path.exists(tmp_out_path):
                        os.unlink(tmp_out_path)
            return "\n\n".join(ocr_text_parts), True
        except Exception as e:
            safe_print(f"Error OCRing pages {start_page}-{end_page} for {pdf_path}: {e}")
            return "", False

    def detect_scanned_headings(self, reader, total_pages):
        """Scans PDF page text to detect heading titles (e.g. BÖLÜM, KISIM, CHAPTER, 1. GİRİŞ) when digital PDF bookmarks are missing"""
        import re
        heading_nodes = []
        # Matches lines like: "BÖLÜM 1: GİRİŞ", "CHAPTER 3", "I. TÜRK TARİHİ", "1. TARİH ÖNCESİ DEVRİLER"
        heading_pattern = re.compile(
            r'^\s*(BÖLÜM|CHAPTER|KISIM|SECTION|PART|[0-9]+\.|[I|V|X]+\.)\s+([A-ZÇĞİÖŞÜ0-9\s\-\.\:\,]{3,80})', 
            re.IGNORECASE
        )
        
        seen_pages = set()
        for page_idx in range(min(total_pages, 200)):
            try:
                page_text = reader.pages[page_idx].extract_text() or ""
                lines = [line.strip() for line in page_text.split('\n') if line.strip()]
                for line in lines[:3]:
                    if heading_pattern.match(line) and page_idx not in seen_pages:
                        seen_pages.add(page_idx)
                        heading_nodes.append({"title": line[:80], "page": page_idx, "depth": 0})
                        break
            except Exception:
                pass
                
        return heading_nodes

    def process_all_articles(self, limit=None):
        """Walks the article directory or splits a single PDF book, extracts text, and updates SQLite DB"""
        if not self.articles_dir.exists():
            safe_print(f"Error: Articles directory or book path not found at {self.articles_dir}")
            return
            
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        cursor = self.conn.cursor()

    def _build_outline_segments(self, nodes, total_pages):
        """Build contiguous chapter segments from parsed outline nodes.

        ``outline_max_depth`` keeps only top-level (or depth-limited) outline
        nodes.  ``min_segment_pages`` merges very short adjacent sections so a
        title page or a one-page preface does not become its own training
        article.  Both settings are opt-in; their defaults preserve the old
        behavior.
        """
        if not nodes:
            return []

        filtered = nodes
        if self.outline_max_depth is not None:
            filtered = [
                n for n in nodes
                if int(n.get("depth", 0)) <= self.outline_max_depth
            ]
            # Never turn a valid outline into an empty document if its roots
            # are malformed; fall back to the full outline in that case.
            if not filtered:
                filtered = nodes

        anchors = sorted(filtered, key=lambda x: x["page"])
        anchors.append({"title": "Appendix / Index", "page": total_pages, "depth": 0})

        raw = []
        for i in range(len(anchors) - 1):
            ch_title = anchors[i]["title"]
            start_p = anchors[i]["page"]
            end_p = anchors[i + 1]["page"] - 1
            if start_p > end_p:
                continue
            if self.is_boilerplate_segment(ch_title):
                safe_print(f"  [Skip Boilerplate] Skipping outline section: '{ch_title}'")
                continue
            raw.append({"title": ch_title, "start": start_p, "end": end_p})

        if self.min_segment_pages > 1 and raw:
            merged = []
            for seg in raw:
                if merged:
                    prev = merged[-1]
                    prev_pages = prev["end"] - prev["start"] + 1
                    if prev_pages < self.min_segment_pages:
                        prev["end"] = seg["end"]
                        if seg["title"] not in prev["title"]:
                            prev["title"] = (prev["title"] + " / " + seg["title"])[:180]
                        continue
                merged.append(dict(seg))
            # Avoid a tiny trailing section; it belongs with the previous one.
            if len(merged) > 1:
                last = merged[-1]
                if (last["end"] - last["start"] + 1) < self.min_segment_pages:
                    last = merged.pop()
                    prev = merged[-1]
                    prev["end"] = last["end"]
                    if last["title"] not in prev["title"]:
                        prev["title"] = (prev["title"] + " / " + last["title"])[:180]
            raw = merged

        return [(s["title"], s["start"], s["end"]) for s in raw]

    def extract_book_segments(self, pdf_path):
        """Splits a single PDF book file into logical chapter segments using digital outline bookmarks, printed TOC, or scanned headings"""
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        # 1. Parse bookmarks/outline
        outline = reader.outline
        nodes = self.parse_outline_nodes(reader, outline)
        
        # Sort bookmarks by page number to create contiguous ranges
        nodes = sorted(nodes, key=lambda x: x["page"])
        
        unique_nodes = []
        seen_pages = set()
        for n in nodes:
            if n["page"] not in seen_pages:
                seen_pages.add(n["page"])
                unique_nodes.append(n)
        
        segments = []
        if unique_nodes:
            safe_print(f"Found {len(unique_nodes)} bookmarks/chapters in digital outline for {pdf_path.name}.")
            if self.outline_max_depth is not None:
                depth_kept = sum(
                    1 for n in unique_nodes
                    if int(n.get("depth", 0)) <= self.outline_max_depth
                )
                safe_print(
                    f"  [Outline Filter] depth<={self.outline_max_depth}: "
                    f"{depth_kept}/{len(unique_nodes)} nodes kept"
                )
            segments = self._build_outline_segments(unique_nodes, total_pages)
        else:
            safe_print(f"No digital bookmarks found in {pdf_path.name}. Attempting OCR & printed TOC heading detection...")
            detected_headings = self.detect_scanned_headings(reader, total_pages)
            if detected_headings:
                safe_print(f"Detected {len(detected_headings)} heading/chapter markers in {pdf_path.name}.")
                segments = self._build_outline_segments(detected_headings, total_pages)
            else:
                safe_print(f"Splitting {pdf_path.name} into default 15-page segments.")
                segment_size = 15
                for start_p in range(0, total_pages, segment_size):
                    end_p = min(start_p + segment_size - 1, total_pages - 1)
                    segments.append((f"Section starting page {start_p + 1}", start_p, end_p))

        return segments, reader

    def process_all_articles(self, limit=None):
        """Walks the article directory or splits single/multiple PDF books, extracts text, and updates SQLite DB"""
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        cursor = self.conn.cursor()

        if self.input_mode in ("kiwix", "zim") or str(self.input_path).lower().endswith(".zim"):
            safe_print(f"=== Extraction Mode: KIWIX ZIM (Target ZIM: {self.input_path}) ===")
            from pipeline.kiwix_extractor import KiwixZimExtractor
            zim_extractor = KiwixZimExtractor(config_path=self.config_path if hasattr(self, "config_path") else "config.json")
            zim_extractor.extract_from_zim(zim_path=str(self.input_path) if str(self.input_path).endswith(".zim") else None, limit=limit)
            zim_extractor.close()
            return

        if self.input_mode in ("rendergit", "github", "git_repo"):
            safe_print(f"=== Extraction Mode: RENDERGIT (Target Repo: {self.input_path}) ===")
            repo_input = str(self.input_path).strip()
            project_id = self.config.get("project_id", "git_project")

            from pipeline.code_extractor import clone_repository, flatten_repository_rendergit, extract_and_store_code_units

            if repo_input.startswith("http://") or repo_input.startswith("https://") or repo_input.startswith("git@"):
                repo_name = repo_input.rstrip("/").split("/")[-1].replace(".git", "")
                repo_dir = Path("downloads/repos") / repo_name
                clone_repository(repo_input, repo_dir)
            else:
                repo_dir = Path(repo_input)

            rendergit_out_path = Path("exports") / f"{project_id}_rendergit.md"
            flattened_text, parsed_files = flatten_repository_rendergit(repo_dir, output_file=rendergit_out_path)

            extracted_units = extract_and_store_code_units(
                parsed_files=parsed_files,
                repo_dir=repo_dir,
                db_path=Path(self.db_path),
                project_id=project_id,
                repo_url=repo_input
            )

            # Store flattened repo text as an article entry in SQLite DB
            rel_path = f"repo::{repo_dir.name}"
            processed_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (rel_path, repo_dir.name, f"Git Repository: {repo_dir.name}", datetime.now().year, f"Flattened repository text ({len(parsed_files)} source files)", flattened_text, 0, processed_at))
            self.conn.commit()

            safe_print(f"Rendergit Extraction completed. Parsed {len(parsed_files)} source files, extracted {len(extracted_units)} AST code units.")
            return

        # Gather target PDF files
        pdf_paths = []
        raw_path_str = str(self.input_path)
        candidate_paths = [p.strip() for p in raw_path_str.replace('\n', ',').replace(';', ',').split(',') if p.strip()]

        for cp in candidate_paths:
            p_obj = Path(cp)
            if p_obj.is_file() and p_obj.suffix.lower() == '.pdf':
                pdf_paths.append(p_obj)
            elif p_obj.is_dir():
                for root, dirs, files in os.walk(p_obj):
                    for file in files:
                        if file.lower().endswith('.pdf'):
                            pdf_paths.append(Path(root) / file)

        # Also fallback check self.articles_dir if separate
        if not pdf_paths and hasattr(self, 'articles_dir') and self.articles_dir.exists():
            if self.articles_dir.is_file() and self.articles_dir.suffix.lower() == '.pdf':
                pdf_paths.append(self.articles_dir)
            elif self.articles_dir.is_dir():
                for root, dirs, files in os.walk(self.articles_dir):
                    for file in files:
                        if file.lower().endswith('.pdf'):
                            pdf_paths.append(Path(root) / file)
                            
        pdf_paths = sorted(list(set(pdf_paths)))
        if not pdf_paths:
            safe_print(f"Error: No valid PDF files found for extraction at {self.input_path}")
            return

        safe_print(f"=== Extraction Mode: {self.input_mode.upper()} ({len(pdf_paths)} target PDF file(s)) ===")
        
        count = 0
        zoom_metadata = self.load_zoom_metadata()
        
        for pdf_path in pdf_paths:
            try:
                reader = pypdf.PdfReader(pdf_path)
                num_pages = len(reader.pages)
            except Exception as e:
                safe_print(f"Warning: Could not read PDF {pdf_path.name}: {e}")
                continue

            # If in Book Mode OR if PDF volume in Folder Mode has > 15 pages: Split into chapters!
            if self.input_mode == "book" or num_pages > 15:
                safe_print(f"Processing Multi-Page Volume ({num_pages} pages): {pdf_path.name}...")
                segments, pdf_reader = self.extract_book_segments(pdf_path)
                
                sliced_segments = segments[start:end] if end is not None else segments[start:]
                for ch_title, start_p, end_p in sliced_segments:
                    rel_path = f"{pdf_path.name}::range::{start_p}_{end_p}"
                    filename = pdf_path.name
                    
                    cursor.execute("SELECT id, extracted_text FROM articles WHERE file_path = ?", (rel_path,))
                    row = cursor.fetchone()
                    if row and row[1]:
                        continue
                        
                    safe_print(f"  [{count+1}] Extracting Segment: '{pdf_path.stem} - {ch_title}' (Pages {start_p+1}-{end_p+1})...")
                    extracted_text, is_ocr = self.extract_pages_range(pdf_path, start_p, end_p)
                    extracted_text = self.clean_ocr_text(extracted_text)
                    ch_title = self.clean_ocr_text(ch_title)
                    full_title = ch_title
                    
                    year = datetime.now().year
                    processed_at = datetime.now().isoformat()
                    zoom_snippet = f"Volume segment from pages {start_p+1} to {end_p+1}."
                    
                    cursor.execute("""
                        INSERT OR REPLACE INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (rel_path, filename, full_title, year, zoom_snippet, extracted_text, 1 if is_ocr else 0, processed_at))
                    
                    self.conn.commit()
                    count += 1
            else:
                # Single-article short PDF (<= 15 pages) inside folder
                rel_path = str(pdf_path.name)
                filename = pdf_path.name
                
                cursor.execute("SELECT id, extracted_text FROM articles WHERE file_path = ?", (rel_path,))
                row = cursor.fetchone()
                if row and row[1]:
                    continue
                    
                safe_print(f"  [{count+1}] Processing Article PDF: {filename}...")
                extracted_text, is_ocr = self.extract_text_from_pdf(pdf_path)
                extracted_text = self.clean_ocr_text(extracted_text)
                title = self.clean_ocr_text(filename)
                
                year = datetime.now().year
                processed_at = datetime.now().isoformat()
                zoom_snippet = zoom_metadata.get(filename, "")
                
                cursor.execute("""
                    INSERT OR REPLACE INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (rel_path, filename, title, year, zoom_snippet, extracted_text, 1 if is_ocr else 0, processed_at))
                
                self.conn.commit()
                count += 1

        safe_print(f"Extraction step completed. Processed {count} new chapters/documents.")
        self.run_langextract_all(limit=limit)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def close(self):
        try:
            if self.enable_vision_ocr and hasattr(self, "vision_ocr") and self.vision_ocr:
                safe_print(f"Unloading vision model ('{self.vision_ocr.model_vision}') from VRAM...")
                try:
                    from pipeline.llm_client import unload_ollama_model
                    unload_ollama_model(self.config, self.vision_ocr.model_vision)
                except Exception as e:
                    safe_print(f"Warning: Failed to unload vision model: {e}")
        except Exception:
            pass
        finally:
            if hasattr(self, "conn") and self.conn:
                safe_close_db(self.conn)
                self.conn = None

if __name__ == "__main__":
    extractor = ArchiveExtractor()
    extractor.process_all_articles(limit=5)
    extractor.close()
