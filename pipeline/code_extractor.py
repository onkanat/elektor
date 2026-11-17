import io
import os
import ast
import importlib
import json
import hashlib
import sqlite3
import subprocess
import time
import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

try:  # .gitignore için tercih edilen motor; yoksa fnmatch yedeği kullanılır
    import pathspec  # type: ignore
except ImportError:  # pragma: no cover - Pi venv'inde pathspec yok
    pathspec = None

IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".antigravity",
    "node_modules", ".idea", ".vscode", "dist", "build", ".egg-info", "qdrant_db"
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin", ".tar", ".gz",
    ".zip", ".7z", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".db",
    ".sqlite", ".sqlite3", ".pkl", ".feather", ".parquet", ".onnx", ".pt", ".safetensors",
    # S1: model/ağırlık, medya, font, JVM, nesne kodu, tensör/kolonar formatları
    ".gguf", ".mlmodel", ".wav", ".mp3", ".mp4", ".webm", ".ogg", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".wasm", ".jar", ".war", ".o", ".a",
    ".so.1", ".lib", ".obj", ".npy", ".npz", ".h5", ".ckpt", ".msgpack",
    ".arrow", ".orc", ".lance", ".ggml", ".idx",
}

# Çok ekli girdiler (".so.1") Path.suffix ile eşleşmez -> ad sonu karşılaştırması
LONG_IGNORE_EXTENSIONS = {ext for ext in IGNORE_EXTENSIONS if ext.count(".") > 1}

# _looks_binary sniff penceresi (bayt)
SNIFF_BYTES = 8192


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
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno)
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
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno)
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
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno)
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
                "lineno": lineno,
                "end_lineno": end_lineno
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
                "lineno": lineno,
                "end_lineno": end_lineno
            })
        self.generic_visit(node)



def safe_rmtree(
    target: Path,
    *,
    repo_dir: Optional[Path] = None,
    force: bool = False,
) -> None:
    """
    S4 guard'lı dizin silme. Amaç: yanlış hedefle çalışma ağacını/ev dizinini silmeyi
    imkânsız kılmak.

    Reddedilen hedefler (``ValueError``): ``/``, ``$HOME``, ``$HOME`` üst dizini,
    verilen ``repo_dir`` kökü ve iki bileşenden kısa yollar. ``.git`` içermeyen bir
    dizin ``force=True`` verilmeden silinmez (yarım klon temizliği bile açık bayrak ister).
    """
    import shutil

    raw = Path(str(target)).expanduser()
    try:
        resolved = raw.resolve()
    except OSError:  # pragma: no cover - bozuk symlink
        resolved = Path(os.path.abspath(str(raw)))

    home = Path.home().resolve()
    forbidden = {Path("/"), home, home.parent}
    if repo_dir is not None:
        forbidden.add(Path(str(repo_dir)).expanduser().resolve())

    if resolved in forbidden or len(resolved.parts) <= 2:
        raise ValueError(f"rmtree reddedildi: tehlikeli hedef {resolved}")
    if not resolved.exists():
        return
    if not resolved.is_dir():
        raise ValueError(f"rmtree reddedildi: dizin değil {resolved}")
    if not (resolved / ".git").exists() and not force:
        raise ValueError(
            f"rmtree reddedildi: {resolved} içinde .git yok (force=True gerekir)"
        )
    shutil.rmtree(resolved)


def clone_repository(
    repo_url: str,
    target_dir: Path,
    *,
    return_status: bool = False,
) -> Any:
    """
    Clones a git repository URL into target_dir. Mevcut klonda ``git pull`` yerine
    ``git fetch --depth 1 origin HEAD && git reset --hard FETCH_HEAD`` çalıştırılır
    (S4: kirli ağaç/ıraksak dal pull çakışması üretmesin, yerel değişiklik kalmasın).

    Güncelleme başarısız olursa hata **yutulmaz**: uyarı basılır ve ``return_status=True``
    iken dönen sözlükte ``stale: True`` + ``error`` bulunur (çağıran sessizce eski kodla
    devam etmez). ``target_dir`` var ama ``.git`` yoksa (yarım klon) guard'lı silme
    (``safe_rmtree(..., force=True)``) sonrası yeniden klonlanır.
    """
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    def _status(updated: bool, stale: bool, error: str = "") -> Dict[str, Any]:
        return {
            "path": str(target_dir),
            "repo_url": repo_url,
            "updated": updated,
            "stale": stale,
            "error": error,
        }

    if target_dir.exists():
        if (target_dir / ".git").exists():
            print(f"Repository '{target_dir.name}' already exists at '{target_dir}'. Fetch/reset to HEAD...")
            try:
                subprocess.run(
                    ["git", "-C", str(target_dir), "fetch", "--depth", "1", "origin", "HEAD"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300,
                )
                subprocess.run(
                    ["git", "-C", str(target_dir), "reset", "--hard", "FETCH_HEAD"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
                )
                print(f"Git fetch/reset completed for '{target_dir.name}'.")
                return _status(True, False) if return_status else target_dir
            except Exception as e:
                detail = str(e)
                stderr = getattr(e, "stderr", None)
                if stderr:
                    detail = f"{detail}: {str(stderr).strip()}"
                print(
                    f"UYARI: '{target_dir.name}' güncellenemedi (stale: true) — yerel kopya "
                    f"kullanılacak, kod eski olabilir: {detail}"
                )
                return _status(False, True, detail) if return_status else target_dir
        else:
            print(f"Found incomplete directory '{target_dir}' without .git. Cleaning before cloning...")
            safe_rmtree(target_dir, repo_dir=target_dir.parent, force=True)

    print(f"Cloning repository '{repo_url}' into '{target_dir}' (this may take a moment for large repositories)...")
    cmd = ["git", "clone", "--depth", "1", repo_url, str(target_dir)]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to clone git repo '{repo_url}': {res.stderr}")
        print(f"Successfully cloned '{repo_url}' into '{target_dir}'.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Git clone timed out after 600s for repository '{repo_url}'.")

    return _status(True, False) if return_status else target_dir


def _ignored_extension(path: Path) -> bool:
    """Uzantı hızlı yolu: tek ekli (.so) ve çok ekli (.so.1) girişleri kapsar."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in IGNORE_EXTENSIONS:
        return True
    return any(ext.count(".") > 1 and name.endswith(ext) for ext in LONG_IGNORE_EXTENSIONS)


def _looks_binary(path: Path, sniff: int = SNIFF_BYTES) -> bool:
    """
    Emniyet ağı: ilk ``sniff`` baytı okuyup ikili dosya olup olmadığına karar verir.

    Kural (S1 şartnamesi): NUL oranı > %1 **veya** çözülemeyen UTF-8 oranı > %30.
    Okunamayan dosya için False döner; çağıran taraf ``unreadable`` sebebiyle atlar.
    """
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(sniff)
    except OSError:
        return False
    if not chunk:
        return False
    if chunk.count(b"\x00") / len(chunk) > 0.01:
        return True
    try:
        chunk.decode("utf-8")
        return False
    except UnicodeDecodeError:
        text = chunk.decode("utf-8", errors="replace")
        undecodable = text.count("\ufffd")
        return (undecodable / max(1, len(text))) > 0.30


def _is_readable(path: Path) -> bool:
    """Açılabilir mi? (S2 streaming yolunda okuma ikinci geçişte yapıldığı için
    yalnız erişim hatasını yakalayan ucuz kapı.)"""
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError:
        return False
    return True


def _parse_ignore_rule(raw: str) -> Optional[Tuple[str, bool, bool]]:
    """``.gitignore`` satırını (desen, negate, yalnız-dizin) üçlüsüne çevirir."""
    line = raw.rstrip("\r\n")
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    line = line.strip()
    if not line:
        return None
    dir_only = line.endswith("/")
    if dir_only:
        line = line.rstrip("/")
    return line, negate, dir_only


class _IgnoreRules:
    """
    ``.gitignore`` / ``--exclude`` desen kümesi.

    ``pathspec`` kuruluysa onun gitwildmatch motoru kullanılır; değilse
    fnmatch tabanlı minimal uygulama devreye girer (yeni zorunlu bağımlılık yok).
    Minimal uygulama: son eşleşme kazanır (``!`` negasyonu), eğik çizgisiz desen
    dosya adıyla her derinlikte eşleşir, ``/`` ile biten desen yalnız dizinleri eler.
    """

    def __init__(self, label: str = "gitignore") -> None:
        self.label = label
        self.backend = "pathspec" if pathspec is not None else "fnmatch"
        self._specs: List[Any] = []
        self._rules: List[Tuple[str, str, bool, bool]] = []

    # -- yükleme -----------------------------------------------------------
    def add_file(self, path: Path, base_rel: str = "") -> None:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        self.add_patterns(lines, base_rel)

    def add_patterns(self, lines: Sequence[str], base_rel: str = "") -> None:
        lines = list(lines)
        if not lines:
            return
        if pathspec is not None:
            prefixed = [p for p in (self._prefix(line, base_rel) for line in lines) if p]
            if prefixed:
                try:
                    self._specs.append(pathspec.PathSpec.from_lines("gitwildmatch", prefixed))
                    return
                except Exception:  # bozuk desende fnmatch yedeğine düş
                    self.backend = "fnmatch"
        for raw in lines:
            parsed = _parse_ignore_rule(raw)
            if parsed:
                pattern, negate, dir_only = parsed
                self._rules.append((base_rel, pattern, negate, dir_only))

    @staticmethod
    def _prefix(line: str, base_rel: str) -> Optional[str]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if not base_rel:
            return line
        negate = stripped.startswith("!")
        body = stripped[1:] if negate else stripped
        body = body.lstrip("/")
        return f"{'!' if negate else ''}{base_rel}/{body}"

    # -- sorgu -------------------------------------------------------------
    def ignored(self, rel_posix: str, is_dir: bool = False) -> bool:
        if self._specs:
            target = rel_posix + "/" if is_dir else rel_posix
            try:
                if any(spec.match_file(target) for spec in self._specs):
                    return True
            except Exception:
                pass
        decision = False
        for base, pattern, negate, dir_only in self._rules:
            if dir_only and not is_dir:
                continue
            if _rule_matches(rel_posix, base, pattern):
                decision = not negate
        return decision


def _rule_matches(rel_posix: str, base: str, pattern: str) -> bool:
    target = rel_posix
    if base:
        prefix = base.rstrip("/") + "/"
        if not target.startswith(prefix):
            return False
        target = target[len(prefix):]
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    if anchored or "/" in pattern:
        if fnmatch.fnmatchcase(target, pattern):
            return True
        return target.startswith(pattern.rstrip("/") + "/")
    return fnmatch.fnmatchcase(target.rsplit("/", 1)[-1], pattern)


def _normalize_ext(include_ext: Optional[Sequence[str]]) -> Optional[Set[str]]:
    """``--include-ext py,JS`` / ``['.py', 'js']`` → ``{'.py', '.js'}``."""
    if not include_ext:
        return None
    values = [include_ext] if isinstance(include_ext, str) else list(include_ext)
    out: Set[str] = set()
    for value in values:
        for part in str(value).split(","):
            ext = part.strip().lower()
            if not ext:
                continue
            out.add(ext if ext.startswith(".") else "." + ext)
    return out or None


def _join_rel(rel_root_posix: str, name: str) -> str:
    return f"{rel_root_posix}/{name}" if rel_root_posix else name


def _rendergit_sidecar_paths(output_file: Optional[Path], repo_dir: Path) -> Tuple[Path, Path]:
    """
    ``exports/<project_id>_skipped.jsonl`` ve ``..._coverage.json`` yollarını üretir.

    Üretimde ``output_file`` zaten ``exports/<project_id>_rendergit.md`` olduğu için
    yan dosyalar aynı dizine (exports/) düşer. ``output_file`` verilmemişse ``exports/``.
    """
    base_dir = output_file.parent if output_file is not None else Path("exports")
    if output_file is not None:
        stem = output_file.name
        if stem.endswith("_rendergit.md"):
            stem = stem[: -len("_rendergit.md")]
        else:
            stem = output_file.stem or repo_dir.name
    else:
        stem = repo_dir.name
    return base_dir / f"{stem}_skipped.jsonl", base_dir / f"{stem}_coverage.json"


def _read_text_normalized(path: Path) -> str:
    """
    S3: BOM'u atar (``utf-8-sig``) ve satır sonlarını LF'e normalleştirir (``newline=None``).
    Böylece BOM'lu dosyanın ilk karakteri ``\\ufeff`` olmaz, CRLF'li dosya LF'e iner.
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline=None) as fh:
        return fh.read()


def _sha1_text(text: str) -> str:
    """İçeriğin sha1'i (dedupe ve ``code_units.sha1`` için tek biçim)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _line_byte_offsets(text: str) -> List[int]:
    """Normalize edilmiş metnin satır başı bayt ofsetleri (0-tabanlı, UTF-8)."""
    offsets = [0]
    total = 0
    for line in text.splitlines(keepends=True):
        total += len(line.encode("utf-8"))
        offsets.append(total)
    return offsets


# ── S5: tree-sitter (opsiyonel ikinci parser) ────────────────────────────────
# Zorunlu bağımlılık DEĞİL: paket yoksa yalnız Python AST yolu çalışır; varsayılan
# (``ast_lang="python"``) davranış S5 öncesiyle birebir aynı kalır.
try:  # paket yok / bozuk derleme aynı kapıdan geçer
    import tree_sitter as _ts  # type: ignore

    _TS_CORE = True
except Exception:  # pragma: no cover - paket kurulu olmayan ortam
    _ts = None
    _TS_CORE = False

VALID_AST_LANGS: Tuple[str, ...] = ("python", "cpp", "cuda", "metal", "typescript")

# lang -> (modül, attribute). Attribute ``None`` ise modülün ``language()`` çağrılır.
_TS_MODULES: Dict[str, Tuple[str, Optional[str]]] = {
    "cpp": ("tree_sitter_cpp", None),
    "cuda": ("tree_sitter_cuda", None),
    "metal": ("tree_sitter_metal", None),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
}

# Gramer paketi yoksa denenecek yedek (Metal C++14 türevi, CUDA C++ üst kümesi)
_TS_FALLBACK: Dict[str, str] = {"metal": "cpp", "cuda": "cpp"}

_TS_LANG_CACHE: Dict[str, Any] = {}
_TS_PARSER_CACHE: Dict[str, Any] = {}

# Uzantı -> iç dil anahtarı (yalnız ``--ast-lang`` ile açıldığında kullanılır)
TS_EXTENSIONS: Dict[str, str] = {
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c++": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".h++": "cpp",
    ".h": "cpp", ".c": "cpp", ".ipp": "cpp", ".inl": "cpp", ".tcc": "cpp",
    ".cu": "cuda", ".cuh": "cuda",
    ".metal": "metal",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
}

_TS_FUNC_NODES = {
    "function_definition", "function_declaration", "method_definition",
    "constructor_declaration", "destructor_declaration",
    "arrow_function", "generator_function_declaration",
}
_TS_CLASS_NODES = {
    "class_specifier", "struct_specifier", "union_specifier", "enum_specifier",
    "class_declaration", "abstract_class_declaration", "interface_declaration",
}
_TS_LOOP_NODES = {
    "for_statement", "while_statement", "do_statement",
    "for_range_loop", "for_in_statement",
}
_TS_NAMESPACE_NODES = {"namespace_definition", "internal_module", "module"}
_TS_MACRO_NODES = {"preproc_def", "preproc_function_def", "macro_definition"}
_TS_IDENTIFIER_NODES = {
    "identifier", "field_identifier", "type_identifier", "namespace_identifier",
    "property_identifier", "operator_name", "destructor_name", "qualified_identifier",
}
_TS_OPAQUE_NODES = {
    "parameter_list", "argument_list", "template_parameter_list",
    "field_declaration_list", "compound_statement",
}


def treesitter_available() -> bool:
    """tree-sitter çekirdeği içe aktarılabildi mi? (bayrak/fallback raporu)."""
    return bool(_TS_CORE)


def reset_tree_sitter_cache() -> None:
    """Dil/parser önbelleğini boşaltır (test ve kurulum sonrası ilk koşum)."""
    _TS_LANG_CACHE.clear()
    _TS_PARSER_CACHE.clear()


def _ts_language(name: str) -> Any:
    """
    Dil nesnesini yükler; yoksa ``None`` döner (istisna yükseltmez).

    Üç paket biçimi de desteklenir: ``Language(capsule)`` (yeni abi3 paketleri),
    ``Language(int)`` (eski paketler) ve doğrudan ``Language`` döndüren modüller
    (ör. ``tree_sitter_metal``).
    """
    if not _TS_CORE or _ts is None:
        return None
    if name in _TS_LANG_CACHE:
        return _TS_LANG_CACHE[name]
    language = None
    spec = _TS_MODULES.get(name)
    if spec is not None:
        module_name, attr = spec
        try:
            module = importlib.import_module(module_name)
            factory = getattr(module, attr) if attr else getattr(module, "language", None)
            if factory is not None:
                raw = factory()
                language = raw if isinstance(raw, _ts.Language) else _ts.Language(raw)
        except Exception:
            language = None
    if language is None and name in _TS_FALLBACK:
        language = _ts_language(_TS_FALLBACK[name])
    _TS_LANG_CACHE[name] = language
    return language


def _ts_parser(name: str) -> Any:
    """Dil için parser (önbellekli). Yeni API ``Parser(lang)``, eski API ``set_language``."""
    if not _TS_CORE or _ts is None:
        return None
    if name in _TS_PARSER_CACHE:
        return _TS_PARSER_CACHE[name]
    language = _ts_language(name)
    parser = None
    if language is not None:
        try:
            parser = _ts.Parser(language)
        except TypeError:  # tree-sitter < 0.22
            try:
                parser = _ts.Parser()
                parser.set_language(language)
            except Exception:
                parser = None
        except Exception:
            parser = None
    _TS_PARSER_CACHE[name] = parser
    return parser


def treesitter_languages() -> List[str]:
    """Yüklenebilen diller (rapor/CLI doğrulaması için)."""
    return [
        name for name in ("cpp", "cuda", "metal", "typescript", "tsx")
        if _ts_language(name) is not None
    ]


def _normalize_ast_lang(ast_lang: Any) -> Tuple[str, ...]:
    """
    ``--ast-lang python,cpp`` → ``('python', 'cpp')``.

    ``None``/boş → ``('python',)`` (varsayılan; S5 öncesi davranış korunur).
    Tanınmayan dil sessizce yutulmaz, ``ValueError`` yükselir.
    """
    if not ast_lang:
        return ("python",)
    values = [ast_lang] if isinstance(ast_lang, str) else list(ast_lang)
    out: List[str] = []
    for value in values:
        for part in str(value).split(","):
            lang = part.strip().lower()
            if not lang:
                continue
            if lang in ("py", "python3"):
                lang = "python"
            elif lang in ("c++", "cxx", "cc"):
                lang = "cpp"
            elif lang in ("ts", "tsx", "javascript"):
                lang = "typescript"
            if lang not in VALID_AST_LANGS:
                raise ValueError(
                    f"Geçersiz ast_lang: {part.strip()!r} (geçerli: {', '.join(VALID_AST_LANGS)})"
                )
            if lang not in out:
                out.append(lang)
    return tuple(out or ("python",))


def _ts_lang_for_path(path: Path, requested: Sequence[str]) -> Optional[str]:
    """Uzantıya göre iç dil anahtarı; dil istenmemiş ya da gramer yoksa ``None``."""
    base = TS_EXTENSIONS.get(path.suffix.lower())
    if base is None:
        return None
    if base == "tsx":
        if "typescript" not in requested:
            return None
        for candidate in ("tsx", "typescript"):
            if _ts_language(candidate) is not None:
                return candidate
        return None
    if base not in requested:
        return None
    if _ts_language(base) is not None:
        return base
    fallback = _TS_FALLBACK.get(base)
    if fallback and _ts_language(fallback) is not None:
        return fallback
    return None


class TreeSitterAnalyzer:
    """
    S5: C++/CUDA/Metal/TS kaynaklarından ``function/class/loop`` birimleri çıkarır.

    ``namespace``/``macro`` birimleri yalnız ``extended=True`` iken toplanır (opt-in).
    Çıktı sözleşmesi Python yolunun aynısıdır: ``unit_type, name, signature,
    docstring, code, line_count, lineno, end_lineno``.
    """

    def __init__(self, source_code: str, file_path: str, language: str, *, extended: bool = False):
        self.source_code = source_code
        self.file_path = file_path
        self.language = language
        self.extended = extended
        self.lines = source_code.splitlines()
        self.items: List[Dict[str, Any]] = []
        self.has_error = False

    # -- yardımcılar -------------------------------------------------------
    def _span(self, node: Any) -> Tuple[int, int]:
        """1-tabanlı (ilk satır, son satır). ``end_point`` dosya sonunda bir satır
        taşabildiği için satır sayısına kırpılır (IndexError yerine güvenli aralık)."""
        total = max(1, len(self.lines))
        start = min(max(1, node.start_point[0] + 1), total)
        end = min(max(start, node.end_point[0] + 1), total)
        return start, end

    def _code(self, start: int, end: int) -> str:
        return "\n".join(self.lines[max(0, start - 1): end])

    @staticmethod
    def _leftmost_identifier(node: Any) -> str:
        queue = [node]
        while queue:
            current = queue.pop(0)
            if current.type in _TS_IDENTIFIER_NODES:
                return current.text.decode("utf-8", "replace").strip()
            if current.type in _TS_OPAQUE_NODES:
                continue
            queue.extend(current.children)
        return ""

    @classmethod
    def _node_name(cls, node: Any) -> str:
        for field in ("declarator", "name"):
            child = node.child_by_field_name(field)
            if child is not None:
                found = cls._leftmost_identifier(child)
                if found:
                    return found
        return cls._leftmost_identifier(node)

    def _signature(self, start: int, end: int) -> str:
        """Bildirim başlığı: ``{`` / ``;`` / kapanan parantez görülene kadar (en çok 3 satır)."""
        parts: List[str] = []
        for index in range(start - 1, min(end, start + 2)):
            parts.append(self.lines[index].strip())
            joined = " ".join(parts)
            if "{" in joined or joined.rstrip().endswith(";") or joined.rstrip().endswith(")"):
                break
        return " ".join(parts)[:240]

    @staticmethod
    def _clean_comment(text: str) -> str:
        cleaned: List[str] = []
        for line in text.splitlines():
            line = line.strip()
            for marker in ("/**", "/*", "///", "//", "*", "#"):
                if line.startswith(marker):
                    line = line[len(marker):].strip()
                    break
            if line.endswith("*/"):
                line = line[: -len("*/")].strip()
            if line:
                cleaned.append(line)
        return "\n".join(cleaned)

    def _docstring(self, node: Any) -> str:
        sibling = node.prev_sibling
        while sibling is not None and sibling.type in ("comment", "attribute_declaration"):
            if sibling.type == "comment":
                return self._clean_comment(sibling.text.decode("utf-8", "replace"))
            sibling = sibling.prev_sibling
        return ""

    @staticmethod
    def _target(node: Any) -> Any:
        """``template <...>`` sarmalı varsa şablon satırı da birime dahil edilir."""
        parent = node.parent
        if parent is not None and parent.type == "template_declaration":
            return parent
        return node

    # -- birim üretimi -----------------------------------------------------
    def _add(self, node: Any, unit_type: str, *, min_lines: int) -> None:
        target = self._target(node)
        start, end = self._span(target)
        line_count = end - start + 1
        if line_count < min_lines:
            return
        name = self._node_name(node)
        if unit_type == "function" and node.type == "arrow_function" and node.parent is not None:
            parent_name = self._node_name(node.parent)
            name = parent_name or name
        if unit_type == "macro" and not name:
            header = self.lines[start - 1] if start - 1 < len(self.lines) else ""
            name = header.replace("#define", "").strip().split("(")[0].strip()
        self.items.append({
            "unit_type": unit_type,
            "name": name or f"{unit_type}_L{start}",
            "signature": self._signature(start, end),
            "docstring": self._docstring(node),
            "code": self._code(start, end),
            "line_count": line_count,
            "lineno": start,
            "end_lineno": end,
        })

    def _add_loop(self, node: Any) -> None:
        start, end = self._span(node)
        if end - start + 1 < 3:
            return
        label = {
            "while_statement": "while_loop",
            "do_statement": "do_while_loop",
        }.get(node.type, "for_loop")
        self.items.append({
            "unit_type": "loop",
            "name": f"{label}_L{start}",
            "signature": self._signature(start, end),
            "docstring": "",
            "code": self._code(start, end),
            "line_count": end - start + 1,
            "lineno": start,
            "end_lineno": end,
        })

    def _consider(self, node: Any) -> None:
        node_type = node.type
        if node_type in _TS_FUNC_NODES:
            self._add(node, "function", min_lines=2)
        elif node_type in _TS_CLASS_NODES:
            self._add(node, "class", min_lines=2)
        elif node_type in _TS_LOOP_NODES:
            self._add_loop(node)
        elif self.extended and node_type in _TS_NAMESPACE_NODES:
            self._add(node, "namespace", min_lines=2)
        elif self.extended and node_type in _TS_MACRO_NODES:
            self._add(node, "macro", min_lines=1)

    def analyze(self) -> List[Dict[str, Any]]:
        """Kaynağı ayrıştırır ve birimleri döndürür (kısmi ağaçta da döner)."""
        parser = _ts_parser(self.language)
        if parser is None:
            raise ValueError(f"tree-sitter parser yok: {self.language}")
        tree = parser.parse(self.source_code.encode("utf-8"))
        root = getattr(tree, "root_node", None)
        if root is None:
            raise ValueError("tree-sitter boş ağaç döndü")
        self.has_error = bool(getattr(root, "has_error", False))
        stack = [root]
        while stack:
            node = stack.pop()
            self._consider(node)
            children = node.children
            if children:
                stack.extend(reversed(children))
        return self.items


def _merge_spans(spans: Sequence[Tuple[int, int]], max_line: int) -> List[Tuple[int, int]]:
    """Kesişen satır aralıklarını birleştirir (örtüşen birim baytı bir kez sayılır)."""
    cleaned = sorted(
        (max(1, start), min(max(end, start), max_line)) for start, end in spans
    )
    merged: List[Tuple[int, int]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def ast_byte_coverage(
    units: Sequence[Dict[str, Any]],
    repo_dir: Optional[Path] = None,
    files: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    """
    S5 ölçümü: birimlerin kapladığı **bayt** oranı.

    Payda ``files`` verilmişse o dosyaların boyutları, yoksa birim içeren dosyalar.
    Pay, her dosyada ``[lineno, end_lineno]`` aralıklarının birleşimidir (iç içe
    birimler bir kez sayılır); satır sonu baytları dahildir.
    """
    by_file: Dict[str, List[Tuple[int, int]]] = {}
    for unit in units:
        path = unit.get("file_path")
        if not path:
            continue
        start = int(unit.get("lineno") or 1)
        end = int(unit.get("end_lineno") or start)
        by_file.setdefault(str(path), []).append((start, end))

    covered_bytes = 0
    file_bytes: Dict[str, int] = {}
    for path, spans in sorted(by_file.items()):
        full = (Path(repo_dir) / path) if repo_dir is not None else Path(path)
        try:
            offsets = _line_byte_offsets(_read_text_normalized(full))
        except OSError:
            continue
        file_bytes[path] = offsets[-1]
        last = len(offsets) - 1
        for start, end in _merge_spans(spans, last):
            covered_bytes += offsets[min(end, last)] - offsets[min(start - 1, last)]

    if files is not None:
        total_bytes = 0
        for candidate in files:
            try:
                total_bytes += Path(candidate).stat().st_size
            except OSError:
                continue
    else:
        total_bytes = sum(file_bytes.values())

    return {
        "bytes_covered": covered_bytes,
        "bytes_total": total_bytes,
        "ratio": (covered_bytes / total_bytes) if total_bytes else 0.0,
        "files_with_units": len(file_bytes),
        "files_total": len(files) if files is not None else len(file_bytes),
        "by_file": file_bytes,
    }


def _write_file_blocks(
    sink,
    render_files: Sequence[Tuple[Path, Path]],
    *,
    dedupe: bool = True,
    duplicates: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Dosya gövdelerini **akışlı** yazar: içerik listesi biriktirilmez, her dosya
    okunur, yazılır ve bırakılır (S2 bellek kuralı).

    S3: okuma ``utf-8-sig`` + ``newline=None`` ile yapılır (BOM atılır, CRLF→LF).
    ``dedupe=True`` iken aynı içerik ikinci kez yazılmaz; blok başlığına
    ``duplicate_of: <ilk yol>`` işareti düşülür ve dosya ``duplicates`` listesine eklenir.
    """
    seen: Dict[str, str] = {}
    for index, (file_path, rel_file_path) in enumerate(render_files):
        if index:
            sink.write("\n")
        rel_posix = Path(rel_file_path).as_posix()
        try:
            content = _read_text_normalized(file_path)
        except (OSError, ValueError) as e:
            sink.write(f"<!-- Could not read {rel_file_path}: {e} -->\n")
            continue
        suffix = file_path.suffix[1:] if file_path.suffix else ""
        header = (
            "=" * 80 + "\n"
            f"FILE: {rel_file_path}\n"
            + "=" * 80 + "\n"
        )
        digest = _sha1_text(content) if dedupe else None
        original = seen.get(digest) if dedupe else None
        if original is not None:
            sink.write(
                f"{header}\n<!-- duplicate_of: {original} (sha1 {digest}); "
                f"içerik ilk kopyada yazıldı -->\n```{suffix}\n```\n"
            )
            if duplicates is not None:
                duplicates.append({
                    "path": rel_posix,
                    "duplicate_of": original,
                    "sha1": digest,
                    "bytes": len(content.encode("utf-8")),
                })
            continue
        if dedupe:
            seen[digest] = rel_posix
        sink.write(f"{header}\n```{suffix}\n{content}\n```\n")


def _flatten_repository_rendergit_v2(
    repo_dir: Path,
    output_file: Optional[Path] = None,
    *,
    exclude: Optional[Sequence[str]] = None,
    include_ext: Optional[Sequence[str]] = None,
    dedupe: bool = True,
) -> Tuple[str, List[Path]]:
    """
    S1/S2 (v2) yolu: ikili dosyalar uzantı listesi **ve** magic-byte sniff ile elenir,
    ``.gitignore`` (varsa ``pathspec``, yoksa fnmatch) ve ``exclude`` desenleri uygulanır,
    atlanan her dosya ``exports/<project_id>_skipped.jsonl`` dosyasına yazılır ve
    ``exports/<project_id>_coverage.json`` kapsam özeti (``by_lang`` dahil) üretilir.

    Yazma akışlıdır: ``output_file`` verilmişse içerik doğrudan dosyaya yazılır,
    bellekte ``file_contents`` listesi ve ``"".join`` tutulmaz → bu modda **boş dize**
    döner. Metnin kendisi gerekiyorsa ``output_file=None`` verilir; o zaman içerik
    ``io.StringIO`` ile toplanır ve döndürülür (test/API yolu).
    """
    include_set = _normalize_ext(include_ext)
    exclude_rules = _IgnoreRules("exclude")
    exclude_rules.add_patterns(list(exclude or []))
    gitignore_rules = _IgnoreRules("gitignore")

    tree_lines: List[str] = []
    render_files: List[Tuple[Path, Path]] = []
    parsed_files: List[Path] = []
    skipped: List[Dict[str, Any]] = []
    skipped_dirs: List[Dict[str, str]] = []
    bytes_rendered = 0

    tree_lines.append(f"# Repository Structure: {repo_dir.name}\n")
    tree_lines.append("```")

    for root, dirs, files in os.walk(repo_dir):
        rel_root = Path(root).relative_to(repo_dir)
        rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

        gitignore_file = Path(root) / ".gitignore"
        if gitignore_file.is_file():
            gitignore_rules.add_file(gitignore_file, rel_root_posix)

        kept_dirs: List[str] = []
        for d in sorted(dirs):
            rel_dir = _join_rel(rel_root_posix, d)
            if d in IGNORE_DIRS or d.startswith("."):
                continue
            if exclude_rules.ignored(rel_dir, True):
                skipped_dirs.append({"path": rel_dir + "/", "reason": "exclude"})
                continue
            if gitignore_rules.ignored(rel_dir, True):
                skipped_dirs.append({"path": rel_dir + "/", "reason": "gitignore"})
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs
        files = sorted(files)

        indent = "  " * len(rel_root.parts) if rel_root_posix else ""
        if rel_root_posix:
            tree_lines.append(f"{indent}📁 {rel_root.name}/")

        for file in files:
            if file.startswith(".") or file in IGNORE_DIRS:
                continue

            file_path = Path(root) / file
            rel_file_path = file_path.relative_to(repo_dir)
            rel_posix = rel_file_path.as_posix()
            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0

            reason: Optional[str] = None
            if include_set is not None and file_path.suffix.lower() not in include_set:
                reason = "include_ext"
            elif exclude_rules.ignored(rel_posix, False):
                reason = "exclude"
            elif gitignore_rules.ignored(rel_posix, False):
                reason = "gitignore"
            elif _ignored_extension(file_path):
                reason = "ext"
            elif _looks_binary(file_path):
                reason = "sniff"
            elif not _is_readable(file_path):
                reason = "unreadable"

            if reason is None:
                tree_lines.append(f"{indent}  📄 {rel_file_path}")
                render_files.append((file_path, rel_file_path))
                parsed_files.append(file_path)
                bytes_rendered += size
                continue

            skipped.append({
                "path": str(rel_file_path),
                "reason": reason,
                "bytes": size,
                "ext": file_path.suffix.lower(),
            })

    tree_lines.append("```\n\n")
    if skipped:
        tree_lines.append(f"<!-- {len(skipped)} dosya atlandı (ikili/okunamaz/gitignore); ayrıntı: {repo_dir.name}_skipped.jsonl -->\n\n")

    head = "".join(tree_lines) + "\n\n# File Contents\n\n"

    duplicates: List[Dict[str, Any]] = []
    flattened_text = ""
    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(head)
            _write_file_blocks(fh, render_files, dedupe=dedupe, duplicates=duplicates)
    else:
        buffer = io.StringIO()
        buffer.write(head)
        _write_file_blocks(buffer, render_files, dedupe=dedupe, duplicates=duplicates)
        flattened_text = buffer.getvalue()

    skipped_path, coverage_path = _rendergit_sidecar_paths(output_file, repo_dir)
    by_reason: Dict[str, int] = {"ext": 0, "sniff": 0, "unreadable": 0}
    by_ext: Dict[str, int] = {}
    by_lang: Dict[str, int] = {}
    bytes_skipped = 0
    for entry in skipped:
        by_reason[entry["reason"]] = by_reason.get(entry["reason"], 0) + 1
        by_ext[entry["ext"] or "<yok>"] = by_ext.get(entry["ext"] or "<yok>", 0) + 1
        bytes_skipped += entry["bytes"]

    for file_path, _rel_file_path in render_files:
        key = file_path.suffix.lower() or "<yok>"
        try:
            size = file_path.stat().st_size
        except OSError:
            size = 0
        by_lang[key] = by_lang.get(key, 0) + size

    coverage = {
        "files_total": len(parsed_files) + len(skipped),
        "files_rendered": len(parsed_files),
        "files_skipped": len(skipped),
        "bytes_rendered": bytes_rendered,
        "bytes_skipped": bytes_skipped,
        "by_reason": by_reason,
        "by_ext": by_ext,
        "by_lang": by_lang,
        # S3: içerik tekrarı — aynı sha1'e sahip sonraki dosyalar içerik taşımaz
        "files_deduplicated": len(duplicates),
        "bytes_deduplicated": sum(entry["bytes"] for entry in duplicates),
        "duplicates": duplicates,
        # Budanan dizinler dosya sayımına girmez (yürüyüşte hiç ziyaret edilmez);
        # izlenebilirlik için ayrı listede tutulur.
        "dirs_skipped": skipped_dirs,
    }

    try:
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        with open(skipped_path, "w", encoding="utf-8") as fh:
            for entry in skipped:
                fh.write(json.dumps({"path": entry["path"], "reason": entry["reason"], "bytes": entry["bytes"]}, ensure_ascii=False) + "\n")
        coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"Uyarı: rendergit yan dosyaları yazılamadı ({skipped_path.parent}): {e}")

    return flattened_text, parsed_files


def flatten_repository_rendergit(
    repo_dir: Path,
    output_file: Optional[Path] = None,
    *,
    v2: bool = False,
    exclude: Optional[Sequence[str]] = None,
    include_ext: Optional[Sequence[str]] = None,
    dedupe: bool = True,
) -> Tuple[str, List[Path]]:
    """
    Traverses repository directory, generating a rendergit-style single markdown document.
    Returns (flattened_text, list_of_parsed_source_files).

    ``v2=True`` ikili dosya kör noktasını kapatan yolu açar (uzantı listesi + sniff +
    skipped/coverage kaydı + ``.gitignore``/``exclude``/``include_ext`` + ``by_lang``).
    Varsayılan (v2=False) eski davranıştır (yalnız uzantı kapısı, yan dosya yok).

    S2: v2 yolunda ``output_file`` verilirse metin **dosyaya akıtılır** ve boş dize
    döner; metin gerekiyorsa ``output_file=None`` kullanılır (``io.StringIO``).
    S3: v2 yolunda okuma ``utf-8-sig`` + ``newline=None`` (BOM atılır, CRLF→LF) ve
    ``dedupe=True`` iken aynı içerik tek kez yazılır (``duplicate_of`` işareti).
    """
    if v2:
        return _flatten_repository_rendergit_v2(
            repo_dir, output_file, exclude=exclude, include_ext=include_ext, dedupe=dedupe
        )

    tree_lines = []
    file_contents = []
    parsed_files = []

    tree_lines.append(f"# Repository Structure: {repo_dir.name}\n")
    tree_lines.append("```")

    for root, dirs, files in os.walk(repo_dir):
        # Filter ignored directories in-place (S2: determinizm için sıralanır)
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith("."))

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

    S3: ``sha1`` / ``byte_offset`` / ``end_offset`` kolonları eklenir (eski DB'lerde
    ``ALTER TABLE ... ADD COLUMN`` ile göç edilir; hiçbir kolon silinmez) ve
    ``(project_id, file_path)`` + ``(project_id, unit_type)`` indeksleri kurulur.
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
        created_at REAL,
        sha1 TEXT,
        byte_offset INTEGER,
        end_offset INTEGER
    )
    """)

    # S3 göçü: mevcut DB'lerde eksik kolonları ekle (kolon silinmez → eski kod çalışır)
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(code_units)")}
    for column, sql_type in (("sha1", "TEXT"), ("byte_offset", "INTEGER"), ("end_offset", "INTEGER")):
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE code_units ADD COLUMN {column} {sql_type}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_units_project_file ON code_units(project_id, file_path)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_units_project_type ON code_units(project_id, unit_type)"
    )
    # S3 kabulü "name LIKE < 3 ms": plan iki indeksle bunu karşılamıyordu (ölçüm 25 ms).
    # NOCASE kolasyonu LIKE önek optimizasyonunu açar → kapsayıcı indeks taraması.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_code_units_project_name "
        "ON code_units(project_id, name COLLATE NOCASE)"
    )

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


VALID_UNIT_TYPES: Tuple[str, ...] = ("function", "class", "loop")

# S5: yalnız tree-sitter yolu açıkken üretilen birim tipleri (opt-in)
EXTENDED_UNIT_TYPES: Tuple[str, ...] = ("namespace", "macro")


def _normalize_units(units: Any) -> Optional[Set[str]]:
    """
    ``--units function,class`` / ``['function']`` → ``{'function','class'}``.

    ``None``/boş → ``None`` (varsayılan: tüm birim tipleri korunur). Tanınmayan tip
    sessizce yutulmaz, ``ValueError`` yükselir (yanlış filtre üretimi önlenir).
    """
    if not units:
        return None
    values = [units] if isinstance(units, str) else list(units)
    out: Set[str] = set()
    for value in values:
        for part in str(value).split(","):
            unit_type = part.strip().lower()
            if not unit_type:
                continue
            if unit_type not in VALID_UNIT_TYPES + EXTENDED_UNIT_TYPES:
                raise ValueError(
                    "Geçersiz unit_type: {!r} (geçerli: {}; S5 uzantısı: {})".format(
                        unit_type,
                        ", ".join(VALID_UNIT_TYPES),
                        ", ".join(EXTENDED_UNIT_TYPES),
                    )
                )
            out.add(unit_type)
    return out or None


def _coerce_bool(value: Any) -> bool:
    """``"0"/"false"/"no"/"off"`` → False; diğer her şey bool()."""
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "", "false", "no", "off")
    return bool(value)


def _ast_errors_path(project_id: str, ast_errors_path: Optional[Path] = None) -> Path:
    if ast_errors_path is not None:
        return Path(ast_errors_path)
    return Path("exports") / f"{project_id}_ast_errors.json"


def _manifest_path(project_id: str, manifest_path: Optional[Path] = None) -> Path:
    """``exports/<project_id>_manifest.json`` (S4 artımlı parse defteri)."""
    if manifest_path is not None:
        return Path(manifest_path)
    return Path("exports") / f"{project_id}_manifest.json"


def _load_manifest(path: Path) -> Dict[str, Any]:
    """Manifest dosyasını okur; yoksa/bozuksa boş sözlük (artımlılık kapanır)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _file_stat(path: Path) -> Tuple[float, int]:
    """``(mtime, size)`` — artımlılığın hızlı kapısı; okunamazsa ``(0.0, -1)``."""
    try:
        st = path.stat()
    except OSError:
        return 0.0, -1
    return round(st.st_mtime, 6), st.st_size


def _sha1_file_text(text: str) -> str:
    """Normalize edilmiş (BOM'suz, LF) metnin sha1'i — dosya baytı değil, içerik izi."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def extract_and_store_code_units(
    parsed_files: List[Path],
    repo_dir: Path,
    db_path: Path,
    project_id: str,
    repo_url: str = "",
    *,
    units: Any = None,
    store_code: Any = True,
    ast_errors_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    incremental: Any = None,
    ast_lang: Any = None,
) -> List[Dict[str, Any]]:
    """
    Parses Python source files using AST, extracts code units, and saves them into SQLite DB.

    S3 davranışı:
    - Kaynak ``utf-8-sig`` + ``newline=None`` ile okunur (BOM atılır, CRLF→LF).
    - ``units`` verilirse yalnız o birim tipleri saklanır (varsayılan: hepsi).
    - ``store_code=False`` (``--store-code 0``) → ``code`` kolonu NULL bırakılır; DB küçülür.
    - Her satıra ``sha1``, ``byte_offset``, ``end_offset`` yazılır.
    - Tek transaction + ``executemany``; parse hataları ``<project_id>_ast_errors.json``'a düşer.

    S4 (artımlılık):
    - ``manifest_path`` verilirse (üretimde ``exports/<project_id>_manifest.json``) her
      koşumda ``{path: {mtime, size, sha1}}`` + ayar imzası yazılır. ``incremental``
      verilmezse manifest_path varlığına göre açılır (geriye dönük uyum: yol yoksa eski
      tam-parse davranışı korunur, testler ``exports/`` dizinini kirletmez).
    - ``incremental=True`` iken manifest'teki ``(mtime, size)`` aynı olan dosya **yeniden
      parse edilmez**; ``DELETE`` yalnız değişen/yeni dosyalar ve silinmiş dosyalar için
      ``WHERE project_id AND file_path`` ile çalışır (tam tablo silme yok).
    - ``units``/``store_code`` değişirse (ayar imzası farklı) tam yeniden parse edilir —
      eski satırlar yeni şemayla karışmaz.
    - Dönüş: **bu koşumda** parse edilen birimler (artımlı atlanan dosyaların birimleri
      DB'de kalır ama listede yer almaz — sayı için ``ast_errors.json`` istatistiklerine bak).

    S5 (tree-sitter, opt-in):
    - ``ast_lang`` verilmezse ``("python",)`` → S5 öncesi davranış birebir korunur.
      ``ast_lang="python,cpp"`` (veya ``"cpp,cuda,metal,typescript"``) tree-sitter yolunu
      açar: ``function/class/loop`` şeması aynı kalır, ``namespace``/``macro`` yalnız bu
      bayrak açıkken (ve ``units`` filtresi izin veriyorsa) üretilir.
    - Paket yoksa/gramer eksikse istisna yükseltilmez: o diller atlanır, kalan yollar
      çalışır (``stats["ast_lang_unavailable"]``).
    - Dil seti varsayılan dışına çıkarsa manifest ayar imzasına ``ast_lang`` eklenir →
      sonraki koşumda tam parse; varsayılanda imza değişmez (gece hattı etkilenmez).
    """
    init_code_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    unit_filter = _normalize_units(units)
    keep_code = _coerce_bool(store_code)
    # S5: dil seti. Varsayılan ("python") S5 öncesi davranışı birebir korur.
    ast_langs = _normalize_ast_lang(ast_lang)
    ts_langs = tuple(lang for lang in ast_langs if lang != "python")
    # namespace/macro yalnız tree-sitter yolu açıkken ve filtre izin veriyorsa üretilir
    emit_extended = bool(ts_langs) and (
        unit_filter is None or bool(unit_filter & set(EXTENDED_UNIT_TYPES))
    )
    ts_unavailable: List[str] = []
    if ts_langs:
        if not treesitter_available():
            ts_unavailable = list(ts_langs)
            print(
                "UYARI: --ast-lang içinde {} istendi ama tree-sitter kurulu değil; "
                "yalnız Python dosyaları ayrıştırılacak.".format(", ".join(ts_langs))
            )
        else:
            ts_unavailable = [lang for lang in ts_langs if _ts_language(lang) is None]
            if ts_unavailable:
                print(
                    "UYARI: gramer paketi yok ({}); bu diller atlanacak.".format(
                        ", ".join(ts_unavailable)
                    )
                )
    incremental_on = (
        _coerce_bool(incremental) if incremental is not None else manifest_path is not None
    )
    settings = {
        "units": sorted(unit_filter) if unit_filter else sorted(VALID_UNIT_TYPES),
        "store_code": keep_code,
    }
    if ast_langs != ("python",):
        # Varsayılan dil setinde anahtar EKLENMEZ → S5 öncesi manifest imzası aynı kalır,
        # gece hattı gereksiz tam parse yapmaz. Dil seti değişince tam parse tetiklenir.
        settings["ast_lang"] = list(ast_langs)
    manifest_p = _manifest_path(project_id, manifest_path)
    previous = _load_manifest(manifest_p) if incremental_on else {}
    prev_files: Dict[str, Any] = previous.get("files") if isinstance(previous.get("files"), dict) else {}
    prev_settings = previous.get("settings") if isinstance(previous.get("settings"), dict) else None
    reuse = bool(incremental_on and prev_files and prev_settings == settings)

    all_extracted_units: List[Dict[str, Any]] = []
    rows: List[Tuple[Any, ...]] = []
    ast_errors: List[Dict[str, str]] = []
    py_files = (
        [p for p in parsed_files if p.suffix.lower() == ".py"] if "python" in ast_langs else []
    )
    # (dosya, dil) çiftleri: python yolu önce, tree-sitter dosyaları sonra (deterministik)
    parse_plan: List[Tuple[Path, str]] = [(p, "python") for p in py_files]
    if ts_langs:
        for candidate in parsed_files:
            if candidate.suffix.lower() == ".py":
                continue
            language = _ts_lang_for_path(candidate, ts_langs)
            if language is not None:
                parse_plan.append((candidate, language))
    files_partial_parse = 0
    units_by_lang: Dict[str, int] = {}
    files_parsed = 0
    files_skipped_unchanged = 0
    files_changed = 0
    files_removed = 0
    new_manifest: Dict[str, Dict[str, Any]] = {}
    created_at = time.time()

    try:
        if not reuse:
            # Tam yeniden parse: ilk koşum, manifest yok ya da ayar imzası değişti
            cursor.execute("DELETE FROM code_units WHERE project_id = ?", (project_id,))

        for file_path, language in parse_plan:
            rel_path = str(file_path.relative_to(repo_dir))
            mtime, size = _file_stat(file_path)
            entry = prev_files.get(rel_path) if reuse else None
            if (
                isinstance(entry, dict)
                and entry.get("mtime") == mtime
                and entry.get("size") == size
            ):
                new_manifest[rel_path] = {
                    "mtime": mtime,
                    "size": size,
                    "sha1": entry.get("sha1", ""),
                }
                files_skipped_unchanged += 1
                continue

            files_changed += 1
            # Yalnız bu dosyanın satırları silinir (S4: DELETE kapsamı daraltıldı)
            cursor.execute(
                "DELETE FROM code_units WHERE project_id = ? AND file_path = ?",
                (project_id, rel_path),
            )
            try:
                source_code = _read_text_normalized(file_path)
                if language == "python":
                    tree = ast.parse(source_code)
                else:
                    tree = None
            except SyntaxError as se:
                ast_errors.append({"file_path": rel_path, "error": f"SyntaxError: {se}"})
                print(f"AST SyntaxError in {rel_path}: {se}")
                new_manifest[rel_path] = {"mtime": mtime, "size": size, "sha1": ""}
                continue
            except Exception as e:
                ast_errors.append({"file_path": rel_path, "error": f"{type(e).__name__}: {e}"})
                print(f"Error parsing AST in {rel_path}: {e}")
                new_manifest[rel_path] = {"mtime": mtime, "size": size, "sha1": ""}
                continue

            files_parsed += 1
            new_manifest[rel_path] = {
                "mtime": mtime,
                "size": size,
                "sha1": _sha1_file_text(source_code),
            }
            if language == "python":
                analyzer = CodeAnalyzer(source_code, rel_path)
                analyzer.visit(tree)
                items = analyzer.items
            else:
                try:
                    analyzer = TreeSitterAnalyzer(
                        source_code, rel_path, language, extended=emit_extended
                    )
                    items = analyzer.analyze()
                except Exception as e:  # bozuk kaynak tüm koşuyu düşürmez
                    files_parsed -= 1
                    ast_errors.append({
                        "file_path": rel_path,
                        "error": f"TreeSitter {type(e).__name__}: {e}",
                    })
                    print(f"Error parsing {language} in {rel_path}: {e}")
                    new_manifest[rel_path] = {"mtime": mtime, "size": size, "sha1": ""}
                    continue
                if getattr(analyzer, "has_error", False):
                    files_partial_parse += 1
                units_by_lang[language] = units_by_lang.get(language, 0) + len(items)

            offsets = _line_byte_offsets(source_code)
            last_index = len(offsets) - 1

            for item in items:
                if item["unit_type"] in EXTENDED_UNIT_TYPES and not emit_extended:
                    continue
                if unit_filter is not None and item["unit_type"] not in unit_filter:
                    continue

                lineno = item["lineno"]
                end_lineno = item.get("end_lineno", lineno)
                byte_offset = offsets[min(lineno - 1, last_index)]
                end_offset = offsets[min(max(end_lineno, lineno), last_index)]
                digest = _sha1_text(item["code"])

                rows.append((
                    project_id, repo_url, rel_path, item["unit_type"], item["name"],
                    item["signature"], item["docstring"],
                    item["code"] if keep_code else None,
                    item["line_count"], lineno, created_at,
                    digest, byte_offset, end_offset,
                ))
                item["file_path"] = rel_path
                item["sha1"] = digest
                item["byte_offset"] = byte_offset
                item["end_offset"] = end_offset
                all_extracted_units.append(item)

        if reuse:
            # Diskten silinen dosyaların birimleri de temizlenir
            for rel_path in prev_files:
                if rel_path in new_manifest:
                    continue
                cursor.execute(
                    "DELETE FROM code_units WHERE project_id = ? AND file_path = ?",
                    (project_id, rel_path),
                )
                files_removed += 1

        if rows:
            cursor.executemany("""
            INSERT INTO code_units
            (project_id, repo_url, file_path, unit_type, name, signature, docstring, code,
             line_count, lineno, created_at, sha1, byte_offset, end_offset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        conn.commit()
    finally:
        conn.close()

    errors_path = _ast_errors_path(project_id, ast_errors_path)
    stats = {
        "files_considered": len(parse_plan),
        "ast_lang": list(ast_langs),
        "ast_lang_unavailable": ts_unavailable,
        "treesitter": treesitter_available(),
        "files_partial_parse": files_partial_parse,
        "units_by_lang": units_by_lang,
        "files_parsed": files_parsed,
        "files_changed": files_changed,
        "files_skipped_unchanged": files_skipped_unchanged,
        "files_removed": files_removed,
        "files_with_errors": len(ast_errors),
        "units_stored": len(rows),
        "store_code": keep_code,
        "units_filter": sorted(unit_filter) if unit_filter else sorted(VALID_UNIT_TYPES),
        "incremental": reuse,
    }
    try:
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        errors_path.write_text(json.dumps({
            "project_id": project_id,
            **stats,
            "errors": ast_errors,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"Uyarı: ast_errors.json yazılamadı ({errors_path}): {e}")

    if incremental_on or manifest_path is not None:
        try:
            manifest_p.parent.mkdir(parents=True, exist_ok=True)
            manifest_p.write_text(json.dumps({
                "project_id": project_id,
                "repo_url": repo_url,
                "generated_at": time.time(),
                "settings": settings,
                "stats": stats,
                "files": new_manifest,
            }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"Uyarı: manifest yazılamadı ({manifest_p}): {e}")

    return all_extracted_units
