import os
import json
import sqlite3
import urllib.request
import re
from html import unescape
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

try:
    import libzim
    LIBZIM_AVAILABLE = True
except ImportError:
    LIBZIM_AVAILABLE = False


def clean_html_fragment(html_str: str) -> str:
    """
    Zero-dependency, high-speed HTML to Markdown converter.
    Preserves code blocks, inline code, math expressions, lists, blockquotes, and headers.
    """
    if not html_str or not html_str.strip():
        return ""

    # 1. Remove unwanted script, style, svg, and form tags
    html_str = re.sub(r"<(script|style|svg|form|button|noscript)[^>]*>.*?</\1>", " ", html_str, flags=re.DOTALL | re.IGNORECASE)

    # 2. Preserve code blocks: <pre><code ...>...</code></pre> -> ```lang\n...\n```
    def _code_block_repl(m):
        code_tag = m.group(1)
        code_content = m.group(2)
        lang_match = re.search(r'class=["\'][^"\']*(?:lang-|language-)([a-zA-Z0-9_\-+]+)', code_tag)
        lang = lang_match.group(1) if lang_match else ""
        clean_code = unescape(code_content)
        # Strip internal tags inside code block if any
        clean_code = re.sub(r"<[^>]+>", "", clean_code)
        return f"\n```{lang}\n{clean_code.strip()}\n```\n"

    html_str = re.sub(r'<pre[^>]*><code([^>]*)>(.*?)</code></pre>', _code_block_repl, html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', html_str, flags=re.DOTALL | re.IGNORECASE)

    # 3. Preserve inline code: <code>...</code> -> `...`
    html_str = re.sub(r'<code[^>]*>(.*?)</code>', lambda m: f"`{unescape(re.sub(r'<[^>]+>', '', m.group(1)))}`", html_str, flags=re.DOTALL | re.IGNORECASE)

    # 4. Preserve MathJax / KaTeX / math-container spans -> $...$ or $$...$$
    html_str = re.sub(r'<span[^>]*class=["\'][^"\']*math-container[^"\']*["\'][^>]*>(.*?)</span>', r' $\1$ ', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<script[^>]*type=["\']math/tex(?:; mode=display)?["\'][^>]*>(.*?)</script>', r'\n$$\1$$\n', html_str, flags=re.DOTALL | re.IGNORECASE)

    # 5. Structure transformations
    html_str = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<h[4-6][^>]*>(.*?)</h[4-6]>', r'\n#### \1\n', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'</p>', '\n\n', html_str, flags=re.IGNORECASE)
    html_str = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
    html_str = re.sub(r'<li[^>]*>', '\n* ', html_str, flags=re.IGNORECASE)
    html_str = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'\n> \1\n', html_str, flags=re.DOTALL | re.IGNORECASE)
    html_str = re.sub(r'<hr\s*/?>', '\n---\n', html_str, flags=re.IGNORECASE)

    # 6. Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_str)
    text = unescape(text)

    # 7. Normalize line breaks and multiple whitespace
    lines = [l.rstrip() for l in text.splitlines()]
    clean_lines = []
    prev_blank = False
    for l in lines:
        stripped = l.strip()
        if not stripped:
            if not prev_blank:
                clean_lines.append("")
                prev_blank = True
        else:
            clean_lines.append(l)
            prev_blank = False

    return '\n'.join(clean_lines).strip()


class KiwixZimExtractor:
    """
    Extracts structured text, Q&A pairs, votes, tags, and metadata from Kiwix (.zim) open archives
    (StackExchange, Wikipedia, Vikikaynak, Ted Talks, etc.) and stores them in the pipeline SQLite database.
    """

    def __init__(self, config_path: str = "config.json"):
        if isinstance(config_path, dict):
            self.config = config_path
        else:
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
        self.min_chars = self.config.get("kiwix_min_chars", 100)
        self.batch_size = self.config.get("kiwix_batch_size", 500)
        self.extract_mode = self.config.get("kiwix_extract_mode", "auto").lower()
        self.min_chosen_score = self.config.get("kiwix_min_chosen_score", 1)
        self.min_vote_diff = self.config.get("kiwix_min_vote_diff", 2)

        # Connect/Initialize SQLite database
        self.conn = sqlite3.connect(self.db_path, timeout=60.0)
        self._init_tables()

    def _init_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
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

        # Dynamically ensure all modern metadata columns exist
        cursor.execute("PRAGMA table_info(articles)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in [
            ("source_type", "TEXT DEFAULT 'document'"),
            ("tags", "TEXT"),
            ("vote_score", "INTEGER DEFAULT 0"),
            ("is_accepted", "INTEGER DEFAULT 0"),
            ("is_vetoed", "INTEGER DEFAULT 0"),
            ("metadata_json", "TEXT")
        ]:
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE articles ADD COLUMN {col_name} {col_def};")
                except Exception as e:
                    print(f"Warning adding column {col_name} to articles: {e}")

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

    def clean_wiki_html(self, html_content: str, title: str = "") -> str:
        """Cleans Wikipedia / encyclopedic HTML into structured Markdown."""
        if not html_content or not html_content.strip():
            return ""

        # Remove MediaWiki specific navigation, edit sections, sidebars, footers
        for cls_pat in [
            r'<div[^>]*class=["\'][^"\']*(?:mw-editsection|reflist|navbox|noprint|sidebar|catlinks|hatnote|ambox)[^"\']*["\'][^>]*>.*?</div>',
            r'<table[^>]*class=["\'][^"\']*(?:navbox|sidebar)[^"\']*["\'][^>]*>.*?</table>',
            r'<header[^>]*>.*?</header>',
            r'<footer[^>]*>.*?</footer>',
            r'<nav[^>]*>.*?</nav>'
        ]:
            html_content = re.sub(cls_pat, " ", html_content, flags=re.DOTALL | re.IGNORECASE)

        cleaned_text = clean_html_fragment(html_content)
        if title and not cleaned_text.startswith("#"):
            cleaned_text = f"# {title}\n\n{cleaned_text}"

        return cleaned_text

    def parse_stackexchange_html(self, html_content: str, title: str = "") -> Optional[Dict[str, Any]]:
        """
        Parses StackExchange question & answer HTML.
        Extracts title, tags, question score, body, closed/veto status, and all answers with vote scores.
        Builds SFT and DPO pair candidates.
        """
        if not html_content or not html_content.strip():
            return None

        # 1. Title fallback from HTML if not provided
        if not title:
            t_match = re.search(r'<a[^>]*class=["\'][^"\']*question-hyperlink[^"\']*["\'][^>]*>(.*?)</a>', html_content, re.DOTALL | re.IGNORECASE)
            if not t_match:
                t_match = re.search(r'<h1[^>]*id=["\']question-header["\'][^>]*>(.*?)</h1>', html_content, re.DOTALL | re.IGNORECASE)
            title = unescape(re.sub(r'<[^>]+>', '', t_match.group(1))).strip() if t_match else ""

        # 2. Tags
        tag_matches = re.findall(r'<a[^>]*class=["\'][^"\']*post-tag[^"\']*["\'][^>]*>([^<]+)</a>', html_content, re.IGNORECASE)
        tags = [unescape(t).strip() for t in tag_matches if t.strip()]

        # 3. Question Score & Body
        q_score_match = re.search(r'id=["\']question["\'][^>]*data-score=["\'](-?\d+)["\']', html_content, re.IGNORECASE)
        if not q_score_match:
            q_score_match = re.search(r'class=["\'][^"\']*vote-count-post[^"\']*["\'][^>]*>(\d+)<', html_content, re.IGNORECASE)
        q_score = int(q_score_match.group(1)) if q_score_match else 0

        q_body_match = re.search(
            r'<div[^>]*class=["\'][^"\']*(?:post-text|js-post-body|s-prose)[^"\']*["\'][^>]*>(.*?)(?:</div>\s*<div[^>]*class=["\'](?:post-layout|mt24|js-post-menu|js-post-comments|votecell|comments)|</div>\s*</div>|\Z)',
            html_content, re.DOTALL | re.IGNORECASE
        )
        q_body = clean_html_fragment(q_body_match.group(1)) if q_body_match else ""

        # 4. Closed / Veto notice
        closed_match = re.search(
            r'<aside[^>]*class=["\'][^"\']*(?:s-notice|s-banner|question-status)[^"\']*["\'][^>]*>(.*?)</aside>',
            html_content, re.DOTALL | re.IGNORECASE
        )
        if not closed_match:
            closed_match = re.search(
                r'<div[^>]*class=["\'][^"\']*(?:question-status|s-notice)[^"\']*["\'][^>]*>(.*?)</div>',
                html_content, re.DOTALL | re.IGNORECASE
            )
        is_vetoed = 1 if closed_match else 0
        close_reason = clean_html_fragment(closed_match.group(1)) if closed_match else ""

        # 5. Extract Answers (decoupled attribute and body extraction)
        ans_blocks = re.finditer(
            r'<div([^>]*id=["\']answer-(\d+)["\'][^>]*)>(.*?)(?=<div[^>]*id=["\']answer-|\Z)',
            html_content, re.DOTALL | re.IGNORECASE
        )

        answers = []
        for ab in ans_blocks:
            tag_attrs = ab.group(1)
            ans_id = ab.group(2)
            ans_content = ab.group(3)

            score_m = re.search(r'data-score=["\'](-?\d+)["\']', tag_attrs, re.IGNORECASE)
            if not score_m:
                score_m = re.search(r'class=["\'][^"\']*(?:vote-count|js-vote-count)[^"\']*["\'][^>]*>(\d+)<', ans_content, re.IGNORECASE)
            ans_score = int(score_m.group(1)) if score_m else 0

            is_acc = ("accepted-answer" in tag_attrs) or ("acceptedAnswer" in ans_content) or ("js-accepted-answer-indicator" in ans_content)
            a_body_match = re.search(
                r'<div[^>]*class=["\'][^"\']*(?:post-text|js-post-body|s-prose)[^"\']*["\'][^>]*>(.*?)(?:</div>\s*<div[^>]*class=["\'](?:post-layout|mt24|js-post-menu|js-post-comments|comments)|</div>\s*</div>|\Z)',
                ans_content, re.DOTALL | re.IGNORECASE
            )
            a_body = clean_html_fragment(a_body_match.group(1)) if a_body_match else ""

            if a_body:
                answers.append({
                    "answer_id": ans_id,
                    "score": ans_score,
                    "is_accepted": is_acc,
                    "body": a_body
                })

        # Sort answers: accepted first, then by score descending
        answers.sort(key=lambda x: (1 if x["is_accepted"] else 0, x["score"]), reverse=True)

        top_answer = answers[0] if answers else None
        has_accepted = any(a["is_accepted"] for a in answers)

        # 6. SFT & DPO formulation
        sft_qa = None
        dpo_pairs = []

        if top_answer and top_answer["body"]:
            sft_qa = {
                "question": title,
                "tags": tags,
                "question_body": q_body,
                "answer": top_answer["body"],
                "is_accepted": top_answer["is_accepted"],
                "score": top_answer["score"]
            }

        if len(answers) >= 2:
            chosen = answers[0]
            # Find the best rejected candidate (lower score with vote difference >= min_vote_diff)
            for cand in reversed(answers[1:]):
                if not cand["is_accepted"] and (chosen["score"] - cand["score"]) >= self.min_vote_diff:
                    dpo_pairs.append({
                        "question": title,
                        "tags": tags,
                        "question_body": q_body,
                        "chosen": chosen["body"],
                        "rejected": cand["body"],
                        "chosen_score": chosen["score"],
                        "rejected_score": cand["score"],
                        "chosen_is_accepted": chosen["is_accepted"]
                    })
                    break

        # 7. Formulate rich markdown for extracted_text
        tags_str = ", ".join(tags) if tags else "General"
        structured_lines = [
            f"# {title}",
            f"**Tags:** `[{tags_str}]` | **Question Score:** {q_score}" + (" | **Status:** [Closed/Vetoed]" if is_vetoed else ""),
            "",
            "## Problem Description",
            q_body or "*(No body provided)*",
            ""
        ]

        if is_vetoed and close_reason:
            structured_lines.extend([
                "> [!WARNING]",
                f"> **Closed Notice:** {close_reason}",
                ""
            ])

        if top_answer:
            acc_str = " (Accepted Solution)" if top_answer["is_accepted"] else ""
            structured_lines.extend([
                f"## Top Answer{acc_str} [Score: {top_answer['score']}]",
                top_answer["body"],
                ""
            ])

        if len(answers) > 1:
            structured_lines.append("## Alternative Answers")
            for idx, a in enumerate(answers[1:], start=2):
                structured_lines.extend([
                    f"### Answer #{idx} [Score: {a['score']}]",
                    a["body"],
                    ""
                ])

        cleaned_text = "\n".join(structured_lines).strip()

        return {
            "title": title,
            "tags": tags,
            "vote_score": q_score,
            "is_accepted": 1 if has_accepted else 0,
            "is_vetoed": is_vetoed,
            "close_reason": close_reason,
            "question_body": q_body,
            "answers": answers,
            "top_answer": top_answer["body"] if top_answer else "",
            "sft_qa": sft_qa,
            "dpo_pairs": dpo_pairs,
            "extracted_text": cleaned_text,
            "source_type": "stackexchange"
        }

    def extract_from_zim(self, zim_path: Optional[str] = None, limit: Optional[Union[int, Tuple[int, int]]] = None) -> int:
        """Extracts articles from a .zim file and saves them in batches to SQLite database."""
        if not LIBZIM_AVAILABLE:
            raise ImportError("libzim package is not installed. Please install libzim.")

        filepath = self.download_zim_if_needed(target_path=zim_path)
        archive = libzim.Archive(filepath)

        filename_lower = Path(filepath).name.lower()
        is_se_archive = ("stackexchange" in filename_lower) or ("stackoverflow" in filename_lower) or (self.extract_mode == "stackexchange")

        print(f"=== Extraction Mode: KIWIX ZIM ({archive.entry_count} entries in archive) ===")
        print(f"  Archive ID: {archive.uuid} | Detected Format: {'StackExchange Q&A' if is_se_archive else 'Wiki/Encyclopedia'}")

        # Parse range limit (e.g. tuple (6, 11) -> start: 6, max_count: 5)
        start_idx = 0
        end_idx = None
        max_to_process = None
        if isinstance(limit, tuple):
            start_idx = limit[0]
            end_idx = limit[1]
            max_to_process = (end_idx - start_idx) if end_idx is not None else None
        elif isinstance(limit, int):
            start_idx = 0
            end_idx = limit
            max_to_process = limit

        cursor = self.conn.cursor()
        now_iso = datetime.now().isoformat()
        candidate_count = 0
        processed_count = 0
        batch_records = []

        entry_count = archive.entry_count
        for idx in range(entry_count):
            if max_to_process is not None and processed_count >= max_to_process:
                break

            try:
                entry = archive._get_entry_by_id(idx)
            except Exception:
                continue

            if entry.is_redirect:
                continue

            title = entry.title
            path = entry.path

            # Fast namespace check
            namespace = getattr(entry, "namespace", "")
            if self.namespaces and namespace and namespace not in self.namespaces:
                continue

            # Skip media, style assets, and non-article folders
            path_lower = path.lower()
            if any(path_lower.startswith(prefix) for prefix in [
                "images/", "img/", "css/", "js/", "fonts/", "style/", "static/", "users/", "api/", "tags/"
            ]):
                continue

            if any(substr in path_lower for substr in ["/img/", "/images/", "/content/img/", "sprite", "favicon"]):
                continue

            clean_path = path_lower.split("?")[0]
            if any(clean_path.endswith(ext) for ext in [
                ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico",
                ".webp", ".woff", ".woff2", ".ttf", ".eot", ".json", ".xml", ".mp3", ".mp4"
            ]):
                continue

            try:
                item = entry.get_item()
                mimetype = getattr(item, "mimetype", getattr(entry, "mimetype", ""))
                if mimetype and not (mimetype.startswith("text/") or mimetype in ("application/xhtml+xml", "application/html")):
                    continue

                if hasattr(item, "content"):
                    content_bytes = bytes(item.content)
                elif hasattr(item, "get_content"):
                    content_bytes = bytes(item.get_content())
                else:
                    content_bytes = bytes(item)
                html_str = content_bytes.decode("utf-8", errors="ignore")
            except Exception:
                continue

            # Determine whether this specific entry is a StackExchange question or Wiki article
            is_entry_se = is_se_archive or path.startswith("questions/") or ("post-tag" in html_str and "question" in html_str)

            if is_entry_se and self.extract_mode != "wiki":
                parsed = self.parse_stackexchange_html(html_str, title=title)
                if not parsed or len(parsed.get("extracted_text", "")) < self.min_chars:
                    continue

                cleaned_text = parsed["extracted_text"]
                source_type = "stackexchange"
                tags_json = json.dumps(parsed["tags"], ensure_ascii=False)
                vote_score = parsed["vote_score"]
                is_accepted = parsed["is_accepted"]
                is_vetoed = parsed["is_vetoed"]
                metadata_json = json.dumps({
                    "tags": parsed["tags"],
                    "vote_score": parsed["vote_score"],
                    "is_accepted": parsed["is_accepted"],
                    "is_vetoed": parsed["is_vetoed"],
                    "close_reason": parsed["close_reason"],
                    "question_body": parsed["question_body"],
                    "sft_qa": parsed["sft_qa"],
                    "dpo_pairs": parsed["dpo_pairs"],
                    "answers_count": len(parsed["answers"])
                }, ensure_ascii=False)
            else:
                cleaned_text = self.clean_wiki_html(html_str, title=title)
                if len(cleaned_text) < self.min_chars:
                    continue

                source_type = "wiki"
                tags_json = json.dumps([], ensure_ascii=False)
                vote_score = 0
                is_accepted = 0
                is_vetoed = 0
                metadata_json = json.dumps({"source_type": "wiki"}, ensure_ascii=False)

            file_identifier = f"zim://{Path(filepath).name}/{path}"
            snippet = cleaned_text[:250].replace("\n", " ") + "..."

            if candidate_count < start_idx:
                candidate_count += 1
                continue

            candidate_count += 1

            batch_records.append((
                file_identifier,
                Path(filepath).name,
                title,
                datetime.now().year,
                snippet,
                cleaned_text,
                0,
                now_iso,
                source_type,
                tags_json,
                vote_score,
                is_accepted,
                is_vetoed,
                metadata_json
            ))
            processed_count += 1

            if len(batch_records) >= self.batch_size:
                cursor.executemany("""
                    INSERT OR REPLACE INTO articles (
                        file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at,
                        source_type, tags, vote_score, is_accepted, is_vetoed, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch_records)
                self.conn.commit()
                batch_records.clear()
                print(f"  [Kiwix] Processed & Committed {processed_count} articles -> Latest: '{title[:40]}' ({len(cleaned_text)} chars)")

            elif processed_count % 50 == 0 or processed_count == 1:
                print(f"  [Kiwix] Processed {processed_count} articles -> Latest: '{title[:40]}' ({len(cleaned_text)} chars)")

        if batch_records:
            cursor.executemany("""
                INSERT OR REPLACE INTO articles (
                    file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at,
                    source_type, tags, vote_score, is_accepted, is_vetoed, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch_records)
            self.conn.commit()
            batch_records.clear()

        # Run Google LangExtract if enabled in config
        if self.config.get("enable_langextract", False):
            from pipeline.extractor import ArchiveExtractor
            ext = ArchiveExtractor(config_path=self.config)
            ext.run_langextract_all(limit=limit)

        print(f"✅ Kiwix ZIM extraction completed! Processed {processed_count} articles into database.")
        return processed_count

    def close(self):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    extractor = KiwixZimExtractor()
    extractor.extract_from_zim(limit=10)
    extractor.close()

