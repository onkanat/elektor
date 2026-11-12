"""Provider capability contract.

The pipeline core should ask what a provider can do, not which vendor it is.
Vendor-specific names stay in adapters (analyzer, vision_ocr, ...).
"""
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _host(base_url: str) -> str:
    try:
        return (urlparse(base_url).hostname or "").lower()
    except Exception:
        return ""


def _remote(config: dict, key: str = "openai_base_url") -> bool:
    base = str(config.get(key) or "").strip()
    if not base:
        return False
    host = _host(base)
    return bool(host) and host not in _LOCAL_HOSTS


def analyzer_capabilities(config: dict) -> dict:
    """Capabilities of the analyzer/translator LLM endpoint."""
    remote = _remote(config)
    mode = str(config.get("structured_output_mode") or "client_parse").strip()
    if mode not in {"client_parse", "server_json"}:
        mode = "client_parse"
    return {
        "kind": "openai_compatible" if remote else "ollama",
        "remote": remote,
        "supports_sharding": not remote,
        "native_unload": not remote,
        "structured_output": mode,
    }


def ocr_capabilities(config: dict) -> dict:
    """Capabilities of the vision/OCR endpoint.

    OCR is normally local Ollama on the OCR host.  A remote OCR endpoint must
    not receive native /api/generate unload calls.
    """
    # `ollama_url` may point at another LAN host (ECE); that is still a
    # native Ollama endpoint, not a remote OpenAI-compatible provider.
    remote = _remote(config, "vision_base_url") if config.get("vision_base_url") else False
    model = str(config.get("model_vision") or "").strip()
    family = str(config.get("ocr_family") or "").strip().lower()
    if not family:
        family = "deepseek" if "deepseek" in model.lower() else "generic"
    native = bool(config.get("vision_native_api", not remote))
    return {
        "kind": "openai_compatible" if remote else "ollama",
        "remote": remote,
        "native_api": native,
        "native_unload": bool(native and config.get("vision_native_unload", True)),
        "family": family,
    }
