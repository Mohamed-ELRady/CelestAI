"""Provider configuration: GUI keys must work without ever being echoed back."""

from __future__ import annotations

import json

import pytest

from celestai.ai import settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("CELESTAI_CONFIG_DIR", str(tmp_path))
    for name in (
        "CELESTAI_AI_PROVIDER", "CELESTAI_AI_MODEL", "CELESTAI_AI_VISION",
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-anthropic-profile"))
    settings.reset_runtime_for_tests()
    yield
    settings.reset_runtime_for_tests()


def test_groq_can_be_configured_at_runtime_without_environment_variables():
    from celestai.ai import client

    config = settings.configure(
        provider_id="groq",
        api_key="gsk_test_secret",
        model="llama-3.3-70b-versatile",
        base_url="",
        vision=False,
        remember=False,
    )

    assert config.adapter == "openai"
    assert config.base_url == "https://api.groq.com/openai/v1"
    assert client.provider() == "openai"
    assert client.credentials_available()


def test_public_settings_never_contain_the_api_key():
    secret = "sk-or-super-secret-value"
    settings.configure(
        provider_id="openrouter", api_key=secret, model="openrouter/free",
        base_url="", vision=True, remember=False,
    )

    state = settings.public_state()
    serialised = json.dumps(state)
    assert state["has_api_key"] is True
    assert secret not in serialised
    assert "api_key" not in state


def test_ollama_needs_no_real_api_key():
    config = settings.configure(
        provider_id="ollama", api_key="", model="gpt-oss:20b",
        base_url="", vision=False, remember=False,
    )
    assert config.api_key == "ollama"
    assert config.base_url == "http://localhost:11434/v1/"


def test_custom_provider_requires_a_valid_url_and_model():
    with pytest.raises(ValueError, match="base URL"):
        settings.configure(
            provider_id="custom", api_key="secret", model="my-model",
            base_url="not-a-url", vision=False, remember=False,
        )


def test_api_settings_response_is_sanitised():
    from celestai.api import AISettingsIn, get_ai_settings, save_ai_settings

    response = save_ai_settings(AISettingsIn(
        provider_id="gemini",
        api_key="gemini-secret",
        model="gemini-3.8-flash",
        vision=True,
    ))
    fetched = get_ai_settings()

    assert response["provider_id"] == "gemini"
    assert response["ai_available"] is True
    assert fetched["has_api_key"] is True
    assert "gemini-secret" not in json.dumps(response)
    assert "gemini-secret" not in json.dumps(fetched)


def test_disconnect_forces_rules_even_when_environment_has_a_key(monkeypatch):
    from celestai.ai.client import credentials_available

    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-secret")
    settings.reset_runtime_for_tests()
    assert credentials_available()

    settings.disconnect()
    assert settings.current().provider_id == "offline"
    assert not credentials_available()
