import json
from types import SimpleNamespace

from pipeline import analyzer as analyzer_module
from pipeline.analyzer import ArchiveAnalyzer


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _analyzer(config):
    obj = object.__new__(ArchiveAnalyzer)
    obj.config = config
    obj.model_name = "test-model"
    return obj


def test_latex_path_omits_response_format(monkeypatch):
    raw = r'{"summary":"x","sft_qa":[{"question":"q","answer":"\(f=\frac{1}{2}\)"}]}'
    client = FakeClient([raw])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({"disable_thinking": True, "max_concurrency": 4}).call_ollama_json("sys", "user")

    assert result is not None
    assert result["sft_qa"][0]["answer"].count(r"\frac") == 1
    assert "response_format" not in client.chat.completions.calls[0]
    assert client.chat.completions.calls[0]["max_tokens"] == 8192


def test_server_json_falls_back_without_response_format(monkeypatch):
    raw = r'{"sft_qa":[{"question":"q","answer":"a"}]}'
    err = RuntimeError("structured_output_failed: Invalid \\escape")
    client = FakeClient([err, raw])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({
        "disable_thinking": True,
        "max_concurrency": 4,
        "structured_output_mode": "server_json",
    }).call_ollama_json("sys", "user")

    assert result == {"sft_qa": [{"question": "q", "answer": "a"}]}
    calls = client.chat.completions.calls
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]


def test_transport_error_does_not_retry(monkeypatch):
    client = FakeClient([ConnectionError("network down"), r'{"ok": true}'])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({"disable_thinking": True, "max_concurrency": 4}).call_ollama_json("sys", "user")

    assert result is None
    assert len(client.chat.completions.calls) == 1


def test_literal_reasoning_tags_inside_json_are_preserved(monkeypatch):
    payload = {
        "summary": "The server saves a  thinking block and a  response block.",
        "topics": ["thinking"],
        "sft_qa": [
            {
                "question": "What is a  thinking block?",
                "answer": "It is saved before the  response text; do not drop it.",
            }
        ],
        "dpo_pair": {"question": "q", "chosen": "c", "rejected": "r"},
    }
    raw = json.dumps(payload)
    client = FakeClient([raw])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({"disable_thinking": True, "max_concurrency": 4}).call_ollama_json("sys", "user")

    assert result == payload


def test_leading_reasoning_wrapper_is_stripped(monkeypatch):
    payload = {
        "summary": "ok",
        "sft_qa": [{"question": "q", "answer": "a"}],
        "dpo_pair": {"question": "q", "chosen": "c", "rejected": "r"},
    }
    raw = " thinkinginternal reasoning</think>\n" + json.dumps(payload)
    client = FakeClient([raw])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({"disable_thinking": True, "max_concurrency": 4}).call_ollama_json("sys", "user")

    assert result == payload


def test_fenced_json_with_literal_reasoning_tags_is_preserved(monkeypatch):
    payload = {
        "summary": "Use  thinking and  response as literal labels.",
        "sft_qa": [{"question": "q", "answer": "a"}],
        "dpo_pair": {"question": "q", "chosen": "c", "rejected": "r"},
    }
    raw = "```json\n" + json.dumps(payload) + "\n```"
    client = FakeClient([raw])
    monkeypatch.setattr(analyzer_module, "get_openai_client", lambda cfg: client)

    result = _analyzer({"disable_thinking": True, "max_concurrency": 4}).call_ollama_json("sys", "user")

    assert result == payload
