"""Cost-saving cache tests — no real provider calls."""

from __future__ import annotations

from pydantic import BaseModel

from celestai.ai import settings
from celestai.ai.cache import compact_json, response_cache


class _Answer(BaseModel):
    answer: str


class _FakeOpenAI:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **_kwargs):
        self.calls += 1
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def _configure_fake_groq(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CELESTAI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CELESTAI_AI_PROVIDER", "groq")
    monkeypatch.setenv("OPENAI_API_KEY", "gsk_fake_cache_test")
    monkeypatch.setenv("CELESTAI_AI_MODEL", "llama-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    settings.reset_runtime_for_tests()


def test_identical_structured_request_uses_one_provider_call(monkeypatch, tmp_path):
    import celestai.ai.client as client

    _configure_fake_groq(monkeypatch, tmp_path)
    fake = _FakeOpenAI('{"answer":"same quality"}')
    monkeypatch.setattr(client, "_openai_client", lambda: fake)

    first = client.ask("system", "identical", _Answer, task="cache-test")
    second = client.ask("system", "identical", _Answer, task="cache-test")

    assert first == second
    assert first is not second
    assert fake.calls == 1
    assert response_cache.snapshot()["api_calls_saved"] == 1
    stats = client.telemetry.snapshot()["groq"]
    assert stats["api_calls"] == 1
    assert stats["cache_hits"] == 1


def test_changed_prompt_never_reuses_a_response(monkeypatch, tmp_path):
    import celestai.ai.client as client

    _configure_fake_groq(monkeypatch, tmp_path)
    fake = _FakeOpenAI('{"answer":"valid"}')
    monkeypatch.setattr(client, "_openai_client", lambda: fake)

    client.ask("system", "request one", _Answer)
    client.ask("system", "request two", _Answer)

    assert fake.calls == 2
    assert response_cache.snapshot()["cache_hits"] == 0


def test_identical_text_request_is_cached(monkeypatch, tmp_path):
    import celestai.ai.client as client

    _configure_fake_groq(monkeypatch, tmp_path)
    fake = _FakeOpenAI("unchanged answer")
    monkeypatch.setattr(client, "_openai_client", lambda: fake)

    assert client.ask_text("system", "same question") == "unchanged answer"
    assert client.ask_text("system", "same question") == "unchanged answer"
    assert fake.calls == 1


def test_compact_json_removes_only_structural_whitespace():
    value = {"type": "object", "properties": {"name": {"type": "string"}}}
    encoded = compact_json(value)

    assert encoded == '{"properties":{"name":{"type":"string"}},"type":"object"}'
