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
            
        self.usb_path = Path(self.config["usb_path"])
        self.articles_dir = self.usb_path / "articles"
        self.csv_path = self.usb_path / "lib" / "zoom_pageinfo.csv"
        self.db_path = self.config["db_path"]
        self.ocr_threshold = self.config.get("ocr_threshold_chars", 100)
        self.tesseract_cmd = self.config.get("tesseract_cmd", "tesseract")
        
        # Connect/Initialize SQLite database
        self.conn = sqlite3.connect(self.db_path)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
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
        """Sanitizes text by replacing common OCR character recognition mistakes"""
        if not text:
            return text
            
        # 1. Spaced words or broken hyphenations
        text = text.replace("circu it", "circuit")
        text = text.replace("circu its", "circuits")
        text = text.replace("transi stor", "transistor")
        text = text.replace("transi stors", "transistors")
        text = text.replace("resis tor", "resistor")
        text = text.replace("resis tors", "resistors")
        text = text.replace("capaci tor", "capacitor")
        text = text.replace("capaci tors", "capacitors")
        text = text.replace("op- arnp", "op-amp")
        text = text.replace("op arnp", "op-amp")
        
        # 2. Specific word replacements with word boundaries
        import re
        replacements = {
            r"\bsw1ng1ng\b": "swinging",
            r"\bc1rcu1t\b": "circuit",
            r"\bc1rcu1ts\b": "circuits",
            r"\bd1stortion\b": "distortion",
            r"\bd1g1tal\b": "digital",
            r"\bl1kew1se\b": "likewise",
            r"\bampl1f1er\b": "amplifier",
            r"\bampl1f1ers\b": "amplifiers",
            r"\btrans1stor\b": "transistor",
            r"\btrans1stors\b": "transistors",
            r"\bres1stor\b": "resistor",
            r"\bres1stors\b": "resistors",
            r"\bcapac1tor\b": "capacitor",
            r"\bcapac1tors\b": "capacitors",
            r"\b74I0\b": "7410",
            r"\b1C11\b": "IC11",
            r"\boparnp\b": "op-amp",
            r"\barnp\b": "amp",
            r"\barnps\b": "amps",
            r"\brnicro\b": "micro",
            r"\bcligital\b": "digital",
            r"\banaclog\b": "analogue",
            r"\bF1gute\b": "Figure",
            r"\bf1gure\b": "figure",
            r"\bf1gures\b": "figures",
            r"\bF1g\b": "Figure",
            r"\bf1g\b": "figure",
            r"\bl0nF\b": "10nF",
            r"\bl00nF\b": "100nF",
            r"\blµF\b": "1µF",
            r"\bl0µF\b": "10µF",
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
        return text

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
            
            return extracted_text, is_ocr
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
            # Try OCR directly on failure
            ocr_text, ocr_success = self.ocr_pdf(pdf_path)
            return ocr_text, ocr_success

    def process_all_articles(self, limit=None):
        """Walks the article directory, extracts text, and updates SQLite DB"""
        if not self.articles_dir.exists():
            print(f"Error: Articles directory not found at {self.articles_dir}")
            return
            
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        zoom_metadata = self.load_zoom_metadata()
        cursor = self.conn.cursor()
        
        # Get list of all PDFs under articles folder
        pdf_paths = []
        for root, dirs, files in os.walk(self.articles_dir):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_paths.append(Path(root) / file)
                    
        print(f"Found {len(pdf_paths)} total PDFs in {self.articles_dir}")
        pdf_paths = sorted(pdf_paths)
        
        # Apply slice based on range
        sliced_paths = pdf_paths[start:end] if end is not None else pdf_paths[start:]
        print(f"Processing range [{start}:{end if end is not None else len(pdf_paths)}] ({len(sliced_paths)} files)...")
        
        count = 0
        for pdf_path in sliced_paths:
            # Get path relative to the usb articles dir
            rel_path = str(pdf_path.relative_to(self.articles_dir.parent))
            filename = pdf_path.name
            
            # Check if already processed
            cursor.execute("SELECT id, extracted_text FROM articles WHERE file_path = ?", (rel_path,))
            row = cursor.fetchone()
            if row and row[1]:
                # Already processed and has text, skip
                continue
                
            print(f"[{count+1}] Processing: {rel_path}...")
            
            # Extract Year from path
            # Path is like .../articles/YYYY/...
            year = None
            for p in pdf_path.parts:
                if p.isdigit() and len(p) == 4:
                    year = int(p)
                    break
                    
            # Get Zoom snippet & title
            zoom_snippet = zoom_metadata.get(filename, "")
            title = ""
            if zoom_snippet:
                # Title is usually the first line or first part of snippet
                title = zoom_snippet.split("By")[0].replace("project ", "").replace("PROJECT ", "").strip()
                if not title:
                    title = filename
            else:
                title = filename
                
            # Extract text
            extracted_text, is_ocr = self.extract_text_from_pdf(pdf_path)
            extracted_text = self.clean_ocr_text(extracted_text)
            title = self.clean_ocr_text(title)
            
            # Save or Update SQLite
            processed_at = datetime.now().isoformat()
            if row:
                cursor.execute("""
                    UPDATE articles 
                    SET extracted_text = ?, is_ocr = ?, processed_at = ?, title = ?, year = ?, zoom_snippet = ?
                    WHERE file_path = ?
                """, (extracted_text, 1 if is_ocr else 0, processed_at, title, year, zoom_snippet, rel_path))
            else:
                cursor.execute("""
                    INSERT INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (rel_path, filename, title, year, zoom_snippet, extracted_text, 1 if is_ocr else 0, processed_at))
                
            self.conn.commit()
            count += 1
            
        print(f"Extraction step completed. Processed {count} new files.")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    extractor = ArchiveExtractor()
    extractor.process_all_articles(limit=5)
    extractor.close()
