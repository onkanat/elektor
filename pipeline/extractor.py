import os
import csv
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
import pypdf
import pypdfium2 as pdfium
from datetime import datetime

class ArchiveExtractor:
    def __init__(self, config_path="config.json"):
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
            
        self.db_path = self.config["db_path"]
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ocr_threshold = self.config.get("ocr_threshold_chars", 100)
        self.tesseract_cmd = self.config.get("tesseract_cmd", "tesseract")
        
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
        self.conn.commit()
        
        # Backward compatibility migration for is_embedded column
        try:
            cursor.execute("SELECT is_embedded FROM articles LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE articles ADD COLUMN is_embedded INTEGER DEFAULT 0")
            self.conn.commit()

    def load_zoom_metadata(self):
        """Reads zoom_pageinfo.csv and builds a mapping of filename -> zoom snippet & title"""
        metadata = {}
        if not self.csv_path.exists():
            print(f"Warning: CSV metadata not found at {self.csv_path}")
            return metadata
            
        print(f"Loading zoom metadata from {self.csv_path}...")
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
        print(f"Loaded metadata for {len(metadata)} files.")
        return metadata

    def ocr_pdf(self, pdf_path):
        """Renders PDF pages to images and runs Tesseract OCR on them"""
        print(f"Running OCR on {pdf_path.name}...")
        ocr_text_parts = []
        try:
            doc = pdfium.PdfDocument(pdf_path)
            for i, page in enumerate(doc):
                # Render page at 300 DPI for high quality OCR
                bitmap = page.render(scale=300/72)
                pil_img = bitmap.to_pil()
                
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_img_path = tmp_img.name
                    pil_img.save(tmp_img_path)
                    
                with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp_out:
                    tmp_out_path = tmp_out.name
                    
                try:
                    cmd = [self.tesseract_cmd, tmp_img_path, tmp_out_path]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode != 0:
                        print(f"  Page {i+1} OCR failed: {result.stderr}")
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
            print(f"  Error rendering/OCRing {pdf_path}: {e}")
            return "", False

    def clean_ocr_text(self, text):
        """Sanitizes text by replacing common OCR character recognition mistakes, repairing broken word spaces, line hyphens, and cleaning TOC index artifacts."""
        if not text:
            return text
            
        import re
        
        # 1. Repair hyphenated word breaks across lines (e.g. "impa- \n ratorluk" -> "imparatorluk")
        text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
        
        # 2. General Turkish Suffix Re-joining (e.g. "medeni yeti" -> "medeniyeti", "ge nişliği" -> "genişliği")
        turkish_suffix_pattern = re.compile(
            r'(\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,})\s+(lar|ler|lık|lik|luk|lük|mda|mde|nda|nde|nin|nın|nün|nun|ten|tan|den|dan|ya|ye|yu|yü|cı|ci|cu|cü|lüğü|luğu|liğe|liğine|sının|sinin|ları|leri|yeti|yati|liği|lığı)\b',
            re.IGNORECASE
        )
        text = turkish_suffix_pattern.sub(r'\1\2', text)

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
            print(f"Parsed {len(toc_headings)} chapter entries from printed Table of Contents (FİHRİST).")
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
                        heading_nodes.append({"title": line[:80], "page": page_idx})
                        break
            except Exception:
                pass
                
        return heading_nodes

    def extract_text_from_pdf(self, pdf_path):
        """Attempts to extract digital text. If too short, falls back to OCR."""
        text_parts = []
        is_ocr = False
        try:
            reader = pypdf.PdfReader(pdf_path)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
            
            extracted_text = "\n\n".join(text_parts).strip()
            
            # If text is too short or empty, perform OCR
            if len(extracted_text) < self.ocr_threshold:
                ocr_text, ocr_success = self.ocr_pdf(pdf_path)
                if ocr_success:
                    extracted_text = ocr_text
                    is_ocr = True
                    
            if self.enable_vision_ocr:
                num_pages = len(reader.pages)
                vision_text = self._process_vision_ocr_for_pages(pdf_path, 0, num_pages - 1)
                if vision_text:
                    extracted_text += vision_text
                    
            return extracted_text, is_ocr
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
            # Try OCR directly on failure
            ocr_text, ocr_success = self.ocr_pdf(pdf_path)
            return ocr_text, ocr_success

    def parse_outline_nodes(self, reader, outline, parent_title=""):
        """Recursively parses outline nodes into a list of (title, page_num) dicts"""
        nodes = []
        if not outline:
            return nodes
            
        for item in outline:
            if isinstance(item, list):
                nodes.extend(self.parse_outline_nodes(reader, item, parent_title))
            else:
                title = item.get("/Title", "")
                page_num = None
                try:
                    page_num = reader.get_destination_page_number(item)
                except Exception:
                    pass
                    
                if page_num is not None:
                    full_title = f"{parent_title} - {title}" if parent_title else title
                    nodes.append({"title": full_title, "page": page_num})
        return nodes

    def extract_pages_range(self, pdf_path, start_page, end_page):
        """Extracts text from a specific page range (0-indexed, inclusive). Falls back to OCR if needed."""
        text_parts = []
        is_ocr = False
        try:
            reader = pypdf.PdfReader(pdf_path)
            for page_idx in range(start_page, min(end_page + 1, len(reader.pages))):
                page_text = reader.pages[page_idx].extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
                    
            extracted_text = "\n\n".join(text_parts).strip()
            
            # If text is too short, run OCR on these pages
            if len(extracted_text) < self.ocr_threshold:
                ocr_text, ocr_success = self.ocr_pdf_pages(pdf_path, start_page, end_page)
                if ocr_success:
                    extracted_text = ocr_text
                    is_ocr = True
                    
            if self.enable_vision_ocr:
                vision_text = self._process_vision_ocr_for_pages(pdf_path, start_page, end_page)
                if vision_text:
                    extracted_text += vision_text
                    
            return extracted_text, is_ocr
        except Exception as e:
            print(f"Error extracting range {start_page}-{end_page} from {pdf_path}: {e}")
            return "", False

    def _process_vision_ocr_for_pages(self, pdf_path, start_page, end_page):
        if not self.enable_vision_ocr:
            return ""
            
        print(f"  [Vision OCR: {self.vision_ocr.model_vision}] Analyzing visual layout on pages {start_page+1}-{end_page+1} of {Path(pdf_path).name}...")
        vision_descriptions = []
        
        for page_idx in range(start_page, end_page + 1):
            elements = self.layout_analyzer.analyze_page(str(pdf_path), page_idx)
            for el in elements:
                img_path = el.get("image_path")
                if img_path and os.path.exists(img_path):
                    context = el.get("context", "")
                    print(f"    [VLM / DeepSeek-OCR] Describing visual zone {el['id']} (caption context: '{context[:45].strip()}...')...")
                    desc = self.vision_ocr.describe_image(img_path, caption_context=context)
                    
                    block_md = (
                        f"\n\n--- [VISUAL & SCHEMATIC CONTENT: Page {page_idx+1} ({el['id']})] ---\n"
                        f"**Element Type**: {el['type'].upper()}\n"
                        f"**Bounding Box**: {el['bbox']}\n"
                        f"**Visual OCR & Diagram Analysis**:\n{desc}\n"
                    )
                    vision_descriptions.append(block_md)
                    
        return "".join(vision_descriptions)

    def ocr_pdf_pages(self, pdf_path, start_page, end_page):
        """Renders specific pages of a PDF and runs OCR on them"""
        print(f"Running OCR on range {start_page}-{end_page} of {pdf_path.name}...")
        ocr_text_parts = []
        try:
            doc = pdfium.PdfDocument(pdf_path)
            for page_idx in range(start_page, min(end_page + 1, len(doc))):
                page = doc[page_idx]
                bitmap = page.render(scale=300/72)
                pil_img = bitmap.to_pil()
                
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_img_path = tmp_img.name
                    pil_img.save(tmp_img_path)
                    
                with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp_out:
                    tmp_out_path = tmp_out.name
                    
                try:
                    cmd = [self.tesseract_cmd, tmp_img_path, tmp_out_path]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode != 0:
                        print(f"  Page {page_idx+1} OCR failed: {result.stderr}")
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
            print(f"Error OCRing pages {start_page}-{end_page} for {pdf_path}: {e}")
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
                        heading_nodes.append({"title": line[:80], "page": page_idx})
                        break
            except Exception:
                pass
                
        return heading_nodes

    def process_all_articles(self, limit=None):
        """Walks the article directory or splits a single PDF book, extracts text, and updates SQLite DB"""
        if not self.articles_dir.exists():
            print(f"Error: Articles directory or book path not found at {self.articles_dir}")
            return
            
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        cursor = self.conn.cursor()

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
            print(f"Found {len(unique_nodes)} bookmarks/chapters in digital outline for {pdf_path.name}.")
            unique_nodes.append({"title": "Appendix / Index", "page": total_pages})
            for i in range(len(unique_nodes) - 1):
                ch_title = unique_nodes[i]["title"]
                start_p = unique_nodes[i]["page"]
                end_p = unique_nodes[i+1]["page"] - 1
                if start_p <= end_p:
                    segments.append((ch_title, start_p, end_p))
        else:
            print(f"No digital bookmarks found in {pdf_path.name}. Attempting OCR & printed TOC heading detection...")
            detected_headings = self.detect_scanned_headings(reader, total_pages)
            if detected_headings:
                print(f"Detected {len(detected_headings)} heading/chapter markers in {pdf_path.name}.")
                detected_headings = sorted(detected_headings, key=lambda x: x["page"])
                detected_headings.append({"title": "Appendix / End", "page": total_pages})
                for i in range(len(detected_headings) - 1):
                    ch_title = detected_headings[i]["title"]
                    start_p = detected_headings[i]["page"]
                    end_p = detected_headings[i+1]["page"] - 1
                    if start_p <= end_p:
                        segments.append((ch_title, start_p, end_p))
            else:
                print(f"Splitting {pdf_path.name} into default 15-page segments.")
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

        if self.input_mode in ("rendergit", "github", "git_repo"):
            print(f"=== Extraction Mode: RENDERGIT (Target Repo: {self.input_path}) ===")
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

            print(f"Rendergit Extraction completed. Parsed {len(parsed_files)} source files, extracted {len(extracted_units)} AST code units.")
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
            print(f"Error: No valid PDF files found for extraction at {self.input_path}")
            return

        print(f"=== Extraction Mode: {self.input_mode.upper()} ({len(pdf_paths)} target PDF file(s)) ===")
        
        count = 0
        zoom_metadata = self.load_zoom_metadata()
        
        for pdf_path in pdf_paths:
            try:
                reader = pypdf.PdfReader(pdf_path)
                num_pages = len(reader.pages)
            except Exception as e:
                print(f"Warning: Could not read PDF {pdf_path.name}: {e}")
                continue

            # If in Book Mode OR if PDF volume in Folder Mode has > 15 pages: Split into chapters!
            if self.input_mode == "book" or num_pages > 15:
                print(f"Processing Multi-Page Volume ({num_pages} pages): {pdf_path.name}...")
                segments, pdf_reader = self.extract_book_segments(pdf_path)
                
                sliced_segments = segments[start:end] if end is not None else segments[start:]
                for ch_title, start_p, end_p in sliced_segments:
                    rel_path = f"{pdf_path.name}::range::{start_p}_{end_p}"
                    filename = pdf_path.name
                    
                    cursor.execute("SELECT id, extracted_text FROM articles WHERE file_path = ?", (rel_path,))
                    row = cursor.fetchone()
                    if row and row[1]:
                        continue
                        
                    print(f"  [{count+1}] Extracting Segment: '{pdf_path.stem} - {ch_title}' (Pages {start_p+1}-{end_p+1})...")
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
                    
                print(f"  [{count+1}] Processing Article PDF: {filename}...")
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

        print(f"Extraction step completed. Processed {count} new chapters/documents.")

    def close(self):
        if self.enable_vision_ocr and hasattr(self, "vision_ocr") and self.vision_ocr:
            print(f"Unloading vision model ('{self.vision_ocr.model_vision}') from VRAM...")
            from pipeline.llm_client import unload_ollama_model
            unload_ollama_model(self.config, self.vision_ocr.model_vision)
        self.conn.close()

if __name__ == "__main__":
    extractor = ArchiveExtractor()
    extractor.process_all_articles(limit=5)
    extractor.close()
