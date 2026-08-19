import os
import json
import sqlite3
import urllib.request
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import libzim
    LIBZIM_AVAILABLE = True
except ImportError:
    LIBZIM_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    import html2text
    HTML2TEXT_AVAILABLE = True
except ImportError:
    HTML2TEXT_AVAILABLE = False

class KiwixZimExtractor:
    """
    Extracts structured text and metadata from Kiwix (.zim) open archives (Wikipedia, StackExchange, Ted Talks, etc.)
    and stores them in the pipeline SQLite database ('articles' table).
    """

    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.db_path = self.config.get("db_path", "database/elektor_archive.db")
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.zim_path = self.config.get("kiwix_zim_path", "downloads/wikipedia_tr.zim")
        self.download_url = self.config.get("kiwix_download_url", "").strip()
        self.namespaces = self.config.get("kiwix_namespaces", None)
        self.min_chars = self.config.get("kiwix_min_chars", 300)

        # Connect/Initialize SQLite database
        self.conn = sqlite3.connect(self.db_path, timeout=60.0)
        self._init_tables()

        if HTML2TEXT_AVAILABLE:
            self.h2t = html2text.HTML2Text()
            self.h2t.ignore_links = False
            self.h2t.ignore_images = True
            self.h2t.body_width = 0
        else:
            self.h2t = None

    def _init_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
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

    def download_zim_if_needed(self, target_path: Optional[str] = None, url: Optional[str] = None) -> str:
        zim_file = target_path or self.zim_path
        src_url = url or self.download_url

        dest_path = Path(zim_file)
        if dest_path.exists():
            print(f"  [Kiwix] Found local ZIM archive -> {dest_path}")
            return str(dest_path)

        if not src_url:
            raise FileNotFoundError(f"Kiwix ZIM file not found at '{dest_path}' and no download URL specified.")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"  [Kiwix] Downloading ZIM catalog archive from '{src_url}' -> {dest_path}...")
        
        req = urllib.request.Request(src_url, headers={"User-Agent": "Mozilla/5.0 (Elektor-Kiwix-Pipeline/2.0)"})
        with urllib.request.urlopen(req) as resp, open(dest_path, "wb") as out_f:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            block_size = 1024 * 1024
            while True:
                buffer = resp.read(block_size)
                if not buffer:
                    break
                out_f.write(buffer)
                downloaded += len(buffer)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"    Progress: {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({pct:.1f}%)", end="\r")
        print(f"\n  [Kiwix] Download complete -> {dest_path}")
        return str(dest_path)

    def clean_html_to_markdown(self, html_content: str, title: str = "") -> str:
        """Converts raw ZIM HTML content into clean, structured text/markdown."""
        if not html_content or not html_content.strip():
            return ""

        if BS4_AVAILABLE:
            soup = BeautifulSoup(html_content, "html.parser")
            # Remove scripts, styles, navbars, footers, edit section buttons
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                tag.decompose()
            for cls in ["mw-editsection", "reflist", "navbox", "noprint", "sidebar"]:
                for elem in soup.find_all(class_=cls):
                    elem.decompose()
            html_content = str(soup)

        if self.h2t:
            text = self.h2t.handle(html_content)
        else:
            if BS4_AVAILABLE:
                text = soup.get_text(separator="\n\n")
            else:
                import re
                text = re.sub(r"<[^>]+>", " ", html_content)

        # Normalize whitespace
        lines = [line.strip() for line in text.splitlines()]
        cleaned_text = "\n".join([line for line in lines if line])

        if title and not cleaned_text.startswith("#"):
            cleaned_text = f"# {title}\n\n{cleaned_text}"

        return cleaned_text

    def extract_from_zim(self, zim_path: Optional[str] = None, limit: Optional[int] = None) -> int:
        """Extracts articles from a .zim file and saves them to SQLite database."""
        if not LIBZIM_AVAILABLE:
            raise ImportError("libzim package is not installed. Please run: pip install libzim")

        filepath = self.download_zim_if_needed(target_path=zim_path)
        archive = libzim.Archive(filepath)

        print(f"=== Extraction Mode: KIWIX ZIM ({archive.entry_count} entries in archive) ===")
        print(f"  Archive ID: {archive.uuid} | Main Entry: {archive.main_entry.path if archive.has_main_entry else 'None'}")

        cursor = self.conn.cursor()
        now_iso = datetime.now().isoformat()
        processed_count = 0

        # Iterate entries in archive
        entry_count = archive.entry_count
        for idx in range(entry_count):
            if limit and processed_count >= limit:
                break

            try:
                entry = archive._get_entry_by_id(idx)
            except Exception:
                continue

            if entry.is_redirect:
                continue

            title = entry.title
            path = entry.path

            # Check namespace if required
            namespace = getattr(entry, "namespace", "")
            if self.namespaces and namespace and namespace not in self.namespaces:
                continue

            # Skip media/style assets (.css, .js, .png, .jpg, .svg, and asset folders)
            if any(path.startswith(prefix) for prefix in ["images/", "Img/", "css/", "js/", "fonts/", "style/", "static/"]):
                continue
            if any(path.endswith(ext) for ext in [".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot"]):
                continue

            try:
                item = entry.get_item()
                if hasattr(item, "content"):
                    content_bytes = bytes(item.content)
                elif hasattr(item, "get_content"):
                    content_bytes = bytes(item.get_content())
                else:
                    content_bytes = bytes(item)
                html_str = content_bytes.decode("utf-8", errors="ignore")
            except Exception as e:
                continue

            cleaned_text = self.clean_html_to_markdown(html_str, title=title)
            if len(cleaned_text) < self.min_chars:
                continue

            file_identifier = f"zim://{Path(filepath).name}/{path}"
            snippet = cleaned_text[:250].replace("\n", " ") + "..."

            cursor.execute("""
                INSERT OR REPLACE INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_identifier,
                Path(filepath).name,
                title,
                datetime.now().year,
                snippet,
                cleaned_text,
                0,
                now_iso
            ))
            processed_count += 1
            if processed_count % 10 == 0 or processed_count == 1:
                print(f"  [Kiwix] Processed {processed_count} articles -> Title: '{title}' ({len(cleaned_text)} chars)")

        self.conn.commit()

        # Run Google LangExtract if enabled in config
        if self.config.get("enable_langextract", True):
            from pipeline.extractor import ArchiveExtractor
            ext = ArchiveExtractor(config_path=self.config)
            ext.run_langextract_all(limit=limit)

        print(f"✅ Kiwix ZIM extraction completed! Processed {processed_count} new articles into database.")
        return processed_count

    def close(self):
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
