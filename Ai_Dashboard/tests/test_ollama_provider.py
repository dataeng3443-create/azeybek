import httpx

from ollama_provider import OllamaProvider


def test_health_check_handles_unavailable_endpoint(monkeypatch):
    def fail(*_args, **_kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", fail)
    ok, message = OllamaProvider("http://localhost:11434", "llama3.2").health_check()
    assert not ok
    assert "unavailable" in message


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _tags(*names):
    return lambda *_a, **_k: _FakeResponse({"models": [{"name": name} for name in names]})


def test_health_check_requires_exact_model_tag(monkeypatch):
    monkeypatch.setattr(httpx, "get", _tags("qwen3:4b"))
    ok, _ = OllamaProvider("http://localhost:11434", "qwen3:8b").health_check()
    assert not ok
    monkeypatch.setattr(httpx, "get", _tags("qwen3:8b"))
    ok, message = OllamaProvider("http://localhost:11434", "qwen3:8b").health_check()
    assert ok and "qwen3:8b" in message


def test_health_check_treats_untagged_name_as_latest(monkeypatch):
    monkeypatch.setattr(httpx, "get", _tags("llama3.2:latest"))
    ok, _ = OllamaProvider("http://localhost:11434", "llama3.2").health_check()
    assert ok


def test_generate_json_disables_thinking_and_strips_think_blocks(monkeypatch):
    sent = {}

    def fake_post(_url, json, **_kwargs):
        sent.update(json)
        return _FakeResponse({"response": '<think>plan {not json}</think>\n{"dax": "EVALUATE ROW(\\"x\\", 1)"}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = OllamaProvider("http://localhost:11434", "qwen3:8b").generate_json("q")
    assert result == {"dax": 'EVALUATE ROW("x", 1)'}
    assert sent["think"] is False and sent["format"] == "json"


def test_generate_json_rejects_non_object(monkeypatch):
    import pytest

    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _FakeResponse({"response": "[1, 2]"}))
    with pytest.raises(ValueError):
        OllamaProvider("http://localhost:11434", "qwen3:8b").generate_json("q")
