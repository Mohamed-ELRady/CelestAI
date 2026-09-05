"""Runtime AI settings shared by the web UI, CLI, and every AI feature.

Secrets entered in the UI live in process memory.  When the user explicitly
asks CelestAI to remember a key, it is delegated to the operating-system
credential store through ``keyring``; the JSON preferences file never contains
the secret itself.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    adapter: str
    name_ar: str
    name_en: str
    description_ar: str
    description_en: str
    base_url: str = ""
    default_model: str = ""
    models: tuple[str, ...] = ()
    free_tier: bool = False
    local: bool = False
    vision_default: bool = False
    key_url: str = ""
    docs_url: str = ""
    requires_key: bool = True

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["models"] = list(self.models)
        return data


PROVIDERS: dict[str, ProviderPreset] = {
    "groq": ProviderPreset(
        id="groq", adapter="openai", name_ar="Groq", name_en="Groq",
        description_ar="سريع جدًا وبخطة مجانية مناسبة للتجربة والمشاريع الصغيرة.",
        description_en="Very fast, with a free tier suited to evaluation and small projects.",
        base_url="https://api.groq.com/openai/v1",
        default_model="qwen/qwen3.6-27b",
        models=(
            "qwen/qwen3.6-27b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "groq/compound",
        ),
        free_tier=True,
        key_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs/openai",
    ),
    "openrouter": ProviderPreset(
        id="openrouter", adapter="openai", name_ar="OpenRouter", name_en="OpenRouter",
        description_ar="راوتر مجاني يختار موديلًا مجانيًا متاحًا تلقائيًا.",
        description_en="A free router that automatically selects an available free model.",
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/free",
        models=("openrouter/free",),
        free_tier=True,
        vision_default=True,
        key_url="https://openrouter.ai/settings/keys",
        docs_url="https://openrouter.ai/docs/guides/routing/routers/free-router",
    ),
    "gemini": ProviderPreset(
        id="gemini", adapter="openai", name_ar="Google Gemini", name_en="Google Gemini",
        description_ar="واجهة Gemini المتوافقة مع OpenAI وخطة مجانية من Google AI Studio.",
        description_en="Gemini's OpenAI-compatible endpoint with a Google AI Studio free tier.",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-3.8-flash",
        models=("gemini-3.8-flash",),
        free_tier=True,
        vision_default=True,
        key_url="https://aistudio.google.com/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs/openai",
    ),
    "ollama": ProviderPreset(
        id="ollama", adapter="openai", name_ar="Ollama (محلي)", name_en="Ollama (local)",
        description_ar="تشغيل محلي بالكامل بلا اشتراك أو مفتاح API.",
        description_en="Fully local inference with no subscription or API key.",
        base_url="http://localhost:11434/v1/",
        default_model="gpt-oss:20b",
        models=("gpt-oss:20b", "qwen3:8b", "llama3.2"),
        free_tier=True,
        local=True,
        vision_default=False,
        docs_url="https://docs.ollama.com/api/openai-compatibility",
        requires_key=False,
    ),
    "anthropic": ProviderPreset(
        id="anthropic", adapter="anthropic", name_ar="Anthropic Claude", name_en="Anthropic Claude",
        description_ar="الدعم الأصلي لـ Claude مع المخرجات المُهيكلة.",
        description_en="Native Claude support with structured outputs.",
        default_model="claude-opus-5",
        models=("claude-opus-5",),
        key_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/en/api/client-sdks",
        vision_default=True,
    ),
    "openai": ProviderPreset(
        id="openai", adapter="openai", name_ar="OpenAI", name_en="OpenAI",
        description_ar="اتصال مباشر بواجهة OpenAI الرسمية.",
        description_en="Direct access to the official OpenAI API.",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5-mini",
        models=("gpt-5-mini", "gpt-5"),
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs/api-reference",
        vision_default=True,
    ),
    "custom": ProviderPreset(
        id="custom", adapter="openai", name_ar="مزوّد مخصّص", name_en="Custom provider",
        description_ar="أي API يطبّق صيغة OpenAI Chat Completions.",
        description_en="Any API implementing OpenAI Chat Completions.",
        vision_default=False,
    ),
}


@dataclass(frozen=True)
class AIConfig:
    provider_id: str
    adapter: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    vision: bool = False
    remember: bool = False
    source: str = "environment"


def _config_dir() -> Path:
    override = os.environ.get("CELESTAI_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".config") / "celestai"


def _preferences_path() -> Path:
    return _config_dir() / "ai-settings.json"


def _keyring_backend():
    try:
        import keyring

        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:
            return None
        return keyring
    except Exception:  # pragma: no cover - depends on the host desktop
        return None


def secure_storage_available() -> bool:
    return _keyring_backend() is not None


def _keyring_get(provider_id: str) -> str:
    backend = _keyring_backend()
    if backend is None:
        return ""
    try:
        return backend.get_password("CelestAI", provider_id) or ""
    except Exception:  # pragma: no cover - depends on the host desktop
        return ""


def _keyring_set(provider_id: str, api_key: str) -> None:
    backend = _keyring_backend()
    if backend is None:
        raise RuntimeError(
            "Secure system storage is unavailable. Install a keyring backend "
            "or leave ‘Remember key’ disabled."
        )
    backend.set_password("CelestAI", provider_id, api_key)


def _keyring_delete(provider_id: str) -> None:
    backend = _keyring_backend()
    if backend is None:
        return
    try:
        backend.delete_password("CelestAI", provider_id)
    except Exception:
        pass


def _infer_provider(base_url: str) -> str:
    value = base_url.lower()
    if "groq.com" in value:
        return "groq"
    if "openrouter.ai" in value:
        return "openrouter"
    if "generativelanguage.googleapis.com" in value:
        return "gemini"
    if "localhost:11434" in value or "127.0.0.1:11434" in value:
        return "ollama"
    if not value or "api.openai.com" in value:
        return "openai"
    return "custom"


def _environment_config() -> AIConfig | None:
    raw = os.environ.get("CELESTAI_AI_PROVIDER", "").strip().lower()
    anthropic_key = (
        os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    )
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()

    explicit_openai = (
        raw in {"openai", "groq", "openai_compatible", "compatible"}
        or (raw in PROVIDERS and PROVIDERS[raw].adapter == "openai")
    )
    if explicit_openai:
        provider_id = (
            raw if raw in {"groq", "openrouter", "gemini", "ollama", "custom"}
            else _infer_provider(base_url)
        )
        preset = PROVIDERS[provider_id]
        return AIConfig(
            provider_id=provider_id,
            adapter="openai",
            api_key=openai_key or ("ollama" if provider_id == "ollama" else ""),
            model=os.environ.get("CELESTAI_AI_MODEL", "").strip() or preset.default_model,
            base_url=base_url or preset.base_url,
            vision=os.environ.get("CELESTAI_AI_VISION", "").strip().lower() in {"1", "true", "yes"},
            source="environment",
        )
    if raw == "offline":
        return AIConfig(provider_id="offline", adapter="none", source="environment")
    if raw == "anthropic" or not raw or raw not in PROVIDERS:
        preset = PROVIDERS["anthropic"]
        return AIConfig(
            provider_id="anthropic", adapter="anthropic", api_key=anthropic_key,
            model=os.environ.get("CELESTAI_AI_MODEL", "").strip() or preset.default_model,
            vision=True, source="environment",
        )
    return None


def _read_saved() -> AIConfig | None:
    path = _preferences_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        provider_id = str(data.get("provider_id", ""))
        if provider_id == "offline":
            return AIConfig(provider_id="offline", adapter="none", remember=True, source="keychain")
        preset = PROVIDERS[provider_id]
        key = "ollama" if not preset.requires_key else _keyring_get(provider_id)
        return AIConfig(
            provider_id=provider_id,
            adapter=preset.adapter,
            api_key=key,
            model=str(data.get("model", "")) or preset.default_model,
            base_url=str(data.get("base_url", "")) or preset.base_url,
            vision=bool(data.get("vision", preset.vision_default)),
            remember=True,
            source="keychain",
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_saved(config: AIConfig) -> None:
    path = _preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider_id": config.provider_id,
        "model": config.model,
        "base_url": config.base_url,
        "vision": config.vision,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _delete_saved() -> None:
    try:
        _preferences_path().unlink()
    except FileNotFoundError:
        pass


_lock = threading.RLock()
_runtime: AIConfig | None = None


def current() -> AIConfig:
    """Resolve runtime UI settings, then environment, then saved desktop settings."""
    with _lock:
        if _runtime is not None:
            return _runtime
        configured = _environment_config() or _read_saved()
        if configured is not None:
            return configured
        return AIConfig(
            provider_id="anthropic", adapter="anthropic",
            model=PROVIDERS["anthropic"].default_model,
            vision=True, source="default",
        )


def _normalise(
    provider_id: str,
    *,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    vision: bool | None = None,
    remember: bool = False,
) -> AIConfig:
    provider_id = provider_id.strip().lower()
    if provider_id == "offline":
        return AIConfig(
            provider_id="offline", adapter="none", remember=remember,
            source="keychain" if remember else "runtime",
        )
    if provider_id not in PROVIDERS:
        raise ValueError("Unknown AI provider")
    preset = PROVIDERS[provider_id]

    previous = current()
    key = api_key.strip()
    if not key and previous.provider_id == provider_id:
        key = previous.api_key
    if not key and remember:
        key = _keyring_get(provider_id)
    if not preset.requires_key:
        key = key or "ollama"
    if preset.requires_key and not key:
        raise ValueError("An API key is required for this provider")
    if len(key) > 4096:
        raise ValueError("API key is too long")

    resolved_model = model.strip() or preset.default_model
    if not resolved_model or len(resolved_model) > 200:
        raise ValueError("A valid model name is required")
    resolved_url = base_url.strip() or preset.base_url
    if preset.adapter == "openai":
        parsed = urlparse(resolved_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("A valid HTTP(S) base URL is required")
    if len(resolved_url) > 1000:
        raise ValueError("Base URL is too long")

    return AIConfig(
        provider_id=provider_id,
        adapter=preset.adapter,
        api_key=key,
        model=resolved_model,
        base_url=resolved_url,
        vision=preset.vision_default if vision is None else bool(vision),
        remember=remember,
        source="keychain" if remember else "runtime",
    )


def preview(**values: Any) -> AIConfig:
    """Validate settings without mutating the active configuration."""
    return _normalise(**values)


def configure(**values: Any) -> AIConfig:
    """Activate settings and optionally persist the secret in the OS keychain."""
    global _runtime
    config = _normalise(**values)
    with _lock:
        if config.remember:
            if config.provider_id != "offline" and PROVIDERS[config.provider_id].requires_key:
                _keyring_set(config.provider_id, config.api_key)
            _write_saved(config)
        else:
            saved = _read_saved()
            if saved and saved.provider_id in PROVIDERS:
                _keyring_delete(saved.provider_id)
            _delete_saved()
        _runtime = config
    return config


def disconnect(*, forget_saved: bool = True) -> AIConfig:
    """Switch this process to the deterministic offline engine."""
    global _runtime
    with _lock:
        if forget_saved:
            saved = _read_saved()
            if saved and saved.provider_id in PROVIDERS:
                _keyring_delete(saved.provider_id)
            _delete_saved()
        _runtime = AIConfig(provider_id="offline", adapter="none", source="runtime")
        return _runtime


def reset_runtime_for_tests() -> None:
    global _runtime
    with _lock:
        _runtime = None


def public_state() -> dict[str, Any]:
    config = current()
    preset = PROVIDERS.get(config.provider_id)
    return {
        "provider_id": config.provider_id,
        "adapter": config.adapter,
        "provider_name_ar": preset.name_ar if preset else "بدون AI",
        "provider_name_en": preset.name_en if preset else "Offline",
        "model": config.model,
        "base_url": config.base_url,
        "vision": config.vision,
        "has_api_key": bool(config.api_key) if config.adapter != "none" else False,
        "remembered": config.remember,
        "source": config.source,
        "secure_storage_available": secure_storage_available(),
        "providers": [provider.public_dict() for provider in PROVIDERS.values()],
    }
