from urllib.request import Request

from pipeline.llm_client import unload_ollama_model


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_remote_analyzer_does_not_signal_ocr_host(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=5):
        calls.append((req.full_url, req.data))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = {
        "openai_base_url": "http://192.0.2.10:8080/v1",
        "ollama_url": "http://192.0.2.26:11434",
        "model_vision": "deepseek-ocr:3b",
    }
    unload_ollama_model(cfg, "qwen3.8-flash-next-q2_0")
    assert calls == []


def test_local_ocr_unload_still_works_on_lan(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=5):
        calls.append((req.full_url, req.data))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = {
        "openai_base_url": "http://192.0.2.10:8080/v1",
        "ollama_url": "http://192.0.2.26:11434",
        "model_vision": "deepseek-ocr:3b",
    }
    unload_ollama_model(cfg, "deepseek-ocr:3b")
    assert len(calls) == 1
    assert calls[0][0] == "http://192.0.2.26:11434/api/generate"


def test_remote_ocr_is_not_signaled(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: calls.append(a) or FakeResponse())
    cfg = {
        "vision_base_url": "http://192.0.2.20:8080/v1",
        "ollama_url": "http://192.0.2.26:11434",
        "model_vision": "dots-ocr:latest",
    }
    unload_ollama_model(cfg, "dots-ocr:latest")
    assert calls == []
