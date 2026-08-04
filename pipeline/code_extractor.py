import os
import ast
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".antigravity",
    "node_modules", ".idea", ".vscode", "dist", "build", ".egg-info", "qdrant_db"
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin", ".tar", ".gz",
    ".zip", ".7z", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".db",
    ".sqlite", ".sqlite3", ".pkl", ".feather", ".parquet", ".onnx", ".pt", ".safetensors"
}


class CodeAnalyzer(ast.NodeVisitor):
    """
    Python AST parser that extracts functions, classes, and significant loops/blocks
    with docstrings, signatures, line numbers, and body source code.
    """
    def __init__(self, source_code: str, file_path: str):
        self.source_code = source_code
        self.file_path = file_path
        self.lines = source_code.splitlines()
        self.items: List[Dict[str, Any]] = []

    def _get_source(self, node: ast.AST) -> str:
        lineno = getattr(node, 'lineno', 1)
        end_lineno = getattr(node, 'end_lineno', lineno)
        return "\n".join(self.lines[lineno - 1 : end_lineno])

    def visit_FunctionDef(self, node: ast.FunctionDef):
        code = self._get_source(node)
        line_count = len(code.splitlines())
        
        # Skip trivial single-line pass/ellipsis functions
        if line_count >= 2:
            sig = ""
            if hasattr(ast, 'unparse'):
                try:
                    sig = f"def {node.name}({ast.unparse(node.args)})"
                    if node.returns:
                        sig += f" -> {ast.unparse(node.returns)}"
                except Exception:
                    sig = f"def {node.name}(...)"
            else:
                sig = f"def {node.name}(...)"

            self.items.append({
                "unit_type": "function",
                "name": node.name,
                "signature": sig,
                "docstring": ast.get_docstring(node) or "",
                "code": code,
                "line_count": line_count,
                "lineno": node.lineno
            })
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        code = self._get_source(node)
        line_count = len(code.splitlines())
        if line_count >= 2:
            sig = ""
            if hasattr(ast, 'unparse'):
                try:
                    sig = f"async def {node.name}({ast.unparse(node.args)})"
                    if node.returns:
                        sig += f" -> {ast.unparse(node.returns)}"
                except Exception:
                    sig = f"async def {node.name}(...)"
            else:
                sig = f"async def {node.name}(...)"

            self.items.append({
                "unit_type": "function",
                "name": node.name,
                "signature": sig,
                "docstring": ast.get_docstring(node) or "",
                "code": code,
                "line_count": line_count,
                "lineno": node.lineno
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        code = self._get_source(node)
        line_count = len(code.splitlines())
        if line_count >= 2:
            bases = []
            if hasattr(ast, 'unparse'):
                bases = [ast.unparse(b) for b in node.bases]
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"

            self.items.append({
                "unit_type": "class",
                "name": node.name,
                "signature": sig,
                "docstring": ast.get_docstring(node) or "",
                "code": code,
                "line_count": line_count,
                "lineno": node.lineno
            })
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        lineno = getattr(node, 'lineno', 1)
        end_lineno = getattr(node, 'end_lineno', lineno)
        if (end_lineno - lineno + 1) >= 3:
            code = self._get_source(node)
            self.items.append({
                "unit_type": "loop",
                "name": f"for_loop_L{lineno}",
                "signature": self.lines[lineno - 1].strip(),
                "docstring": "",
                "code": code,
                "line_count": len(code.splitlines()),
                "lineno": lineno
            })
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        lineno = getattr(node, 'lineno', 1)
        end_lineno = getattr(node, 'end_lineno', lineno)
        if (end_lineno - lineno + 1) >= 3:
            code = self._get_source(node)
            self.items.append({
                "unit_type": "loop",
                "name": f"while_loop_L{lineno}",
                "signature": self.lines[lineno - 1].strip(),
                "docstring": "",
                "code": code,
                "line_count": len(code.splitlines()),
                "lineno": lineno
            })
        self.generic_visit(node)



def clone_repository(repo_url: str, target_dir: Path) -> Path:
    """
    Clones a git repository URL into target_dir. If target_dir exists with .git, pulls latest.
    If target_dir exists without .git (incomplete clone), cleans directory before cloning.
    """
    import shutil
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    
    if target_dir.exists():
        if (target_dir / ".git").exists():
            print(f"Repository '{target_dir.name}' already exists at '{target_dir}'. Pulling latest updates...")
            try:
                subprocess.run(
                    ["git", "-C", str(target_dir), "pull"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
                )
                print(f"Git pull completed for '{target_dir.name}'.")
            except Exception as e:
                print(f"Git pull warning (using existing local repository): {e}")
            return target_dir
        else:
            print(f"Found incomplete directory '{target_dir}' without .git. Cleaning before cloning...")
            shutil.rmtree(target_dir, ignore_errors=True)

    print(f"Cloning repository '{repo_url}' into '{target_dir}' (this may take a moment for large repositories)...")
    cmd = ["git", "clone", "--depth", "1", repo_url, str(target_dir)]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to clone git repo '{repo_url}': {res.stderr}")
        print(f"Successfully cloned '{repo_url}' into '{target_dir}'.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Git clone timed out after 600s for repository '{repo_url}'.")

    return target_dir


def flatten_repository_rendergit(repo_dir: Path, output_file: Optional[Path] = None) -> Tuple[str, List[Path]]:
    """
    Traverses repository directory, generating a rendergit-style single markdown document.
    Returns (flattened_text, list_of_parsed_source_files).
    """
    tree_lines = []
    file_contents = []
    parsed_files = []

    tree_lines.append(f"# Repository Structure: {repo_dir.name}\n")
    tree_lines.append("```")

    for root, dirs, files in os.walk(repo_dir):
        # Filter ignored directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]

        rel_root = Path(root).relative_to(repo_dir)
        indent = "  " * len(rel_root.parts) if str(rel_root) != "." else ""
        
        if str(rel_root) != ".":
            tree_lines.append(f"{indent}📁 {rel_root.name}/")
        
        for file in sorted(files):
            if file.startswith(".") or file in IGNORE_DIRS:
                continue
            
            file_path = Path(root) / file
            if file_path.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            
            rel_file_path = file_path.relative_to(repo_dir)
            tree_lines.append(f"{indent}  📄 {rel_file_path}")
            parsed_files.append(file_path)

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                header = f"================================================================================\n" \
                         f"FILE: {rel_file_path}\n" \
                         f"================================================================================\n"
                file_contents.append(f"{header}\n```{file_path.suffix[1:] if file_path.suffix else ''}\n{content}\n```\n")
            except Exception as e:
                file_contents.append(f"<!-- Could not read {rel_file_path}: {e} -->\n")

    tree_lines.append("```\n\n")

    flattened_text = "".join(tree_lines) + "\n\n# File Contents\n\n" + "\n".join(file_contents)

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(flattened_text, encoding="utf-8")

    return flattened_text, parsed_files


def init_code_db(db_path: Path):
    """
    Initializes the SQLite database table for storing extracted AST code units.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")


    cursor.execute("""
    CREATE TABLE IF NOT EXISTS code_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        repo_url TEXT,
        file_path TEXT,
        unit_type TEXT,
        name TEXT,
        signature TEXT,
        docstring TEXT,
        code TEXT,
        line_count INTEGER,
        lineno INTEGER,
        created_at REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS synthetic_code_pairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code_unit_id INTEGER,
        project_id TEXT,
        instruction TEXT,
        input_code TEXT,
        output_response TEXT,
        tr_instruction TEXT,
        tr_output_response TEXT,
        category TEXT,
        created_at REAL,
        FOREIGN KEY(code_unit_id) REFERENCES code_units(id)
    )
    """)

    conn.commit()
    conn.close()


def extract_and_store_code_units(
    parsed_files: List[Path],
    repo_dir: Path,
    db_path: Path,
    project_id: str,
    repo_url: str = ""
) -> List[Dict[str, Any]]:
    """
    Parses Python source files using AST, extracts code units, and saves them into SQLite DB.
    """
    init_code_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    all_extracted_units = []

    # Clear existing code units for this project_id if re-extracting
    cursor.execute("DELETE FROM code_units WHERE project_id = ?", (project_id,))

    for file_path in parsed_files:
        if file_path.suffix.lower() != ".py":
            continue

        rel_path = str(file_path.relative_to(repo_dir))
        try:
            source_code = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source_code)
            analyzer = CodeAnalyzer(source_code, rel_path)
            analyzer.visit(tree)

            for item in analyzer.items:
                cursor.execute("""
                INSERT INTO code_units 
                (project_id, repo_url, file_path, unit_type, name, signature, docstring, code, line_count, lineno, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id, repo_url, rel_path, item["unit_type"], item["name"],
                    item["signature"], item["docstring"], item["code"], item["line_count"], item["lineno"], time.time()
                ))
                item["file_path"] = rel_path
                all_extracted_units.append(item)

        except SyntaxError as se:
            print(f"AST SyntaxError in {rel_path}: {se}")
        except Exception as e:
            print(f"Error parsing AST in {rel_path}: {e}")

    conn.commit()
    conn.close()
    return all_extracted_units
