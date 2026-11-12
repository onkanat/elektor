from pipeline.providers import analyzer_capabilities, ocr_capabilities


def test_remote_analyzer_has_no_sharding_or_native_unload():
    cfg = {
        "openai_base_url": "http://192.0.2.10:8080/v1",
        "model_vision": "deepseek-ocr:3b",
    }
    a = analyzer_capabilities(cfg)
    assert a["remote"] is True
    assert a["kind"] == "openai_compatible"
    assert a["supports_sharding"] is False
    assert a["native_unload"] is False
    assert a["structured_output"] == "client_parse"


def test_local_analyzer_can_shard_and_unload():
    cfg = {"ollama_url": "http://127.0.0.1:11434"}
    a = analyzer_capabilities(cfg)
    assert a["remote"] is False
    assert a["kind"] == "ollama"
    assert a["supports_sharding"] is True
    assert a["native_unload"] is True


def test_lan_ocr_is_native_ollama_and_can_unload():
    cfg = {
        "openai_base_url": "http://192.0.2.10:8080/v1",
        "ollama_url": "http://192.0.2.26:11434",
        "model_vision": "deepseek-ocr:3b",
    }
    o = ocr_capabilities(cfg)
    assert o["remote"] is False
    assert o["kind"] == "ollama"
    assert o["native_unload"] is True
    assert o["family"] == "deepseek"


def test_remote_ocr_is_not_native():
    cfg = {"vision_base_url": "http://192.0.2.20:8080/v1", "model_vision": "dots-ocr:latest"}
    o = ocr_capabilities(cfg)
    assert o["remote"] is True
    assert o["native_unload"] is False
    assert o["family"] == "generic"


def test_invalid_structured_output_mode_falls_back_to_client_parse():
    cfg = {"openai_base_url": "http://192.0.2.10:8080/v1", "structured_output_mode": "bogus"}
    assert analyzer_capabilities(cfg)["structured_output"] == "client_parse"
