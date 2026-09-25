from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


DEFAULT_PROVIDER_ORDER = [
    "groq",
    "gemini",
    "openai",
    "anthropic",
    "mistral",
    "deepseek",
    "ollama",
]


def _redact_sensitive_text(value: Any) -> str:
    """Oculta credenciales que puedan aparecer en URLs o errores de proveedores."""
    text = str(value or "")
    text = re.sub(
        r"(?i)([?&](?:api[_-]?key|key|access[_-]?token|token|secret|password)=)[^&#\s\"']+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\s*([=:])\s*[\"']?([^\s,;&\"'<>]+)",
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\b(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return text


def _provider_default_models(provider_name: str) -> List[str]:
    defaults = _default_provider_map()
    return list(defaults.get(provider_name, {}).get("models", []) or [])


def _sanitize_provider_models(provider_name: str, models: Optional[Iterable[str]]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    aliases = {
        "gemini 2.5 flash": "gemini-2.5-flash",
        "gemini 2.5 pro": "gemini-2.5-pro",
        "gemini 2.0 flash": "gemini-3.8-flash",
        "gemini-2.0-flash": "gemini-3.8-flash",
        "gemini 2.0 flash lite": "gemini-3.5-flash-lite",
        "gemini-2.0-flash-lite": "gemini-3.5-flash-lite",
    } if provider_name == "gemini" else {}
    for model in list(models or []):
        value = str(model or "").strip()
        value = aliases.get(value.lower(), value)
        if not value or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    return cleaned


def normalize_provider_url(base_url: str, provider_type: str = "openai_compatible") -> str:
    """Acepta una URL de proveedor en formato base o endpoint de chat."""
    value = str(base_url or "").strip()
    if not value:
        return ""
    alias = value.lower().strip().rstrip("/")
    named_endpoints = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
        "google gemini": "https://generativelanguage.googleapis.com/v1beta/models",
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "claude": "https://api.anthropic.com/v1/messages",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "ollama": "http://localhost:11434/api/chat",
    }
    if alias in named_endpoints:
        return named_endpoints[alias]
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    scheme = parts.scheme or "https"
    netloc = parts.netloc
    path = parts.path.rstrip("/")
    if not netloc:
        return value.rstrip("/")
    host = netloc.lower().split(":", 1)[0]
    if host in {"groq.com", "api.groq.com"}:
        netloc = "api.groq.com"
        if path in {"", "/", "/v1", "/openai/v1"}:
            path = "/openai/v1/chat/completions"
    elif host in {"googleapis.com", "generativelanguage.googleapis.com"}:
        netloc = "generativelanguage.googleapis.com"
        if path in {"", "/", "/v1beta"}:
            path = "/v1beta/models"
    elif provider_type.lower() == "openai_compatible" and path.endswith("/v1"):
        path += "/chat/completions"
    return urlunsplit((scheme, netloc, path, parts.query, "")).rstrip("/")


def _default_provider_map() -> Dict[str, Dict[str, Any]]:
    return {
        "groq": {
            "enabled": True,
            "api_key": "",
            "api_keys": [],
            "model": "llama-3.3-70b-versatile",
            "models": [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
            ],
            "base_url": "https://api.groq.com/openai/v1/chat/completions",
            "priority": 10,
            "type": "openai_compatible",
        },
        "gemini": {
            "enabled": True,
            "api_key": "",
            "api_keys": [],
            "model": "gemini-3.8-flash",
            "models": [
                "gemini-3.8-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            ],
            "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
            "priority": 20,
            "type": "gemini",
        },
        "openai": {
            "enabled": False,
            "api_key": "",
            "api_keys": [],
            "model": "gpt-4o-mini",
            "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o3-mini"],
            "base_url": "https://api.openai.com/v1/chat/completions",
            "priority": 30,
            "type": "openai_compatible",
        },
        "anthropic": {
            "enabled": False,
            "api_key": "",
            "api_keys": [],
            "model": "claude-sonnet-4-20250514",
            "models": ["claude-sonnet-4-20250514", "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022"],
            "base_url": "https://api.anthropic.com/v1/messages",
            "priority": 40,
            "type": "anthropic",
        },
        "mistral": {
            "enabled": False,
            "api_key": "",
            "api_keys": [],
            "model": "mistral-small-latest",
            "models": ["mistral-small-latest", "mistral-large-latest", "pixtral-large-latest"],
            "base_url": "https://api.mistral.ai/v1/chat/completions",
            "priority": 50,
            "type": "openai_compatible",
        },
        "deepseek": {
            "enabled": False,
            "api_key": "",
            "api_keys": [],
            "model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-v3", "deepseek-r1"],
            "base_url": "https://api.deepseek.com/v1/chat/completions",
            "priority": 60,
            "type": "openai_compatible",
        },
        "ollama": {
            "enabled": False,
            "api_key": "",
            "api_keys": [],
            "model": "llama3.1",
            "models": ["llama3.1", "qwen2.5:7b", "mistral:7b", "phi3:mini"],
            "base_url": "http://localhost:11434/api/chat",
            "priority": 999,
            "type": "ollama",
        },
    }


class AIProviderManager:
    """Gestión central de proveedores de IA por usuario.

    La idea es que cada lector del equipo pueda guardar sus propias API keys de forma local
    y que Jarvis use esas claves de forma modular, sin depender de un único proveedor ni de
    secretos en el repositorio.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._default_path()
        self.config = self.load()
        self.last_provider_name: Optional[str] = None
        self.last_model_name: Optional[str] = None

    @staticmethod
    def _default_path() -> str:
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        data_dir = os.path.join(local_appdata, "Jarvis")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "jarvis_ai_providers.json")

    def ensure_default(self) -> Dict[str, Any]:
        self.config = self.load()
        return self.config

    def _sanitize_loaded_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        providers = config.get("providers", {})
        if not isinstance(providers, dict):
            return config

        for provider_name, provider_cfg in list(providers.items()):
            if not isinstance(provider_cfg, dict):
                continue
            models = provider_cfg.get("models")
            cleaned_models = _sanitize_provider_models(provider_name, models if isinstance(models, list) else [])
            if isinstance(models, list):
                provider_cfg["models"] = cleaned_models
            provider_type = str(provider_cfg.get("type") or "openai_compatible")
            if provider_cfg.get("base_url"):
                provider_cfg["base_url"] = normalize_provider_url(provider_cfg["base_url"], provider_type)
            elif provider_name in _default_provider_map():
                provider_cfg["base_url"] = _default_provider_map()[provider_name]["base_url"]
            raw_keys = provider_cfg.get("api_keys")
            if isinstance(raw_keys, list):
                provider_cfg["api_keys"] = [
                    key for key in raw_keys
                    if isinstance(key, str) and key.strip() and "://" not in key
                ]
            raw_key = provider_cfg.get("api_key")
            if isinstance(raw_key, str) and "://" in raw_key:
                provider_cfg["api_key"] = ""
            current_model = str(provider_cfg.get("model") or "").strip()
            if provider_name == "gemini":
                current_model = {
                    "gemini 2.5 flash": "gemini-2.5-flash",
                    "gemini 2.5 pro": "gemini-2.5-pro",
                    "gemini 2.0 flash": "gemini-3.8-flash",
                    "gemini-2.0-flash": "gemini-3.8-flash",
                    "gemini 2.0 flash lite": "gemini-3.5-flash-lite",
                    "gemini-2.0-flash-lite": "gemini-3.5-flash-lite",
                }.get(current_model.lower(), current_model)
            if current_model and cleaned_models and current_model not in cleaned_models:
                provider_cfg["model"] = ""
        return config

    def load(self) -> Dict[str, Any]:
        default = {
            "version": 1,
            "selected_provider": "",
            "providers": {},
        }
        try:
            if not os.path.exists(self.config_path):
                self.config = default
                self.save()
                return self.config

            with open(self.config_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError("Formato inválido")

            providers = loaded.get("providers", {})
            merged = {}
            for key, value in providers.items():
                if isinstance(value, dict):
                    merged[key] = dict(value)

            self.config = {
                "version": int(loaded.get("version", 1)),
                "selected_provider": loaded.get("selected_provider", ""),
                "providers": merged,
            }
            self.config = self._sanitize_loaded_config(self.config)
            self.save()
            return self.config
        except Exception:
            self.config = default
            self.config = self._sanitize_loaded_config(self.config)
            self.save()
            return self.config

    def save(self) -> str:
        directory = os.path.dirname(self.config_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.config, fh, indent=2, ensure_ascii=False)
        return self.config_path

    def list_providers(self) -> List[str]:
        return list(self.config.get("providers", {}).keys())

    def provider_names(self) -> List[str]:
        return self.list_providers()

    def get_provider(self, provider_name: str) -> Dict[str, Any]:
        provider = self.config.get("providers", {}).get(provider_name, {})
        if not isinstance(provider, dict):
            return {}
        api_keys = provider.get("api_keys")
        if api_keys is None:
            api_keys = [provider.get("api_key", "")] if provider.get("api_key") else []
        if isinstance(api_keys, str):
            api_keys = [api_keys]
        cleaned = [str(k).strip() for k in api_keys if isinstance(k, str) and str(k).strip()]
        if not cleaned and provider.get("api_key"):
            cleaned = [str(provider.get("api_key")).strip()]
        provider["api_keys"] = cleaned
        provider["api_key"] = cleaned[0] if cleaned else ""
        provider["enabled"] = bool(cleaned) or provider.get("enabled", False)
        return provider

    def provider_api_keys(self, provider_name: str) -> List[str]:
        provider = self.get_provider(provider_name)
        return list(provider.get("api_keys", [provider.get("api_key", "")]))

    def set_provider_keys(self, provider_name: str, api_keys: Iterable[str]) -> Dict[str, Any]:
        provider = self.config.setdefault("providers", {}).setdefault(provider_name, {})
        cleaned = []
        for raw in api_keys or []:
            value = str(raw or "").strip()
            if value and value not in cleaned:
                cleaned.append(value)
        provider["api_keys"] = cleaned
        provider["api_key"] = cleaned[0] if cleaned else ""
        provider["enabled"] = bool(cleaned) or provider.get("enabled", False)
        self.save()
        return provider

    def set_provider_key(self, provider_name: str, api_key: str) -> Dict[str, Any]:
        provider = self.get_provider(provider_name)
        current = provider.get("api_keys", [])
        next_keys = []
        if isinstance(api_key, str):
            value = api_key.strip()
            if value:
                next_keys = [value] + [k for k in current if k != value]
        else:
            next_keys = [str(k).strip() for k in (api_key or []) if str(k).strip()]
        return self.set_provider_keys(provider_name, next_keys)

    def add_provider_key(self, provider_name: str, api_key: str) -> Dict[str, Any]:
        value = str(api_key or "").strip()
        if not value:
            return self.get_provider(provider_name)
        provider = self.get_provider(provider_name)
        keys = list(provider.get("api_keys", []))
        if value not in keys:
            keys.append(value)
        return self.set_provider_keys(provider_name, keys)

    def remove_provider_key(self, provider_name: str, api_key: str) -> Dict[str, Any]:
        value = str(api_key or "").strip()
        if not value:
            return self.get_provider(provider_name)
        provider = self.get_provider(provider_name)
        keys = [str(k).strip() for k in provider.get("api_keys", []) if str(k).strip() and str(k).strip() != value]
        return self.set_provider_keys(provider_name, keys)

    def get_provider_api_key(self, provider_name: str, index: int = 0) -> str:
        keys = self.provider_api_keys(provider_name)
        if not keys:
            return ""
        return keys[index % len(keys)]

    def set_provider_config(self, provider_name: str, **kwargs: Any) -> Dict[str, Any]:
        provider = self.config.setdefault("providers", {}).setdefault(provider_name, {})
        if "base_url" in kwargs:
            kwargs["base_url"] = normalize_provider_url(
                kwargs.get("base_url", ""), str(provider.get("type") or "openai_compatible")
            )
        provider.update(kwargs)
        self.save()
        return provider

    def get_enabled_providers(self) -> List[str]:
        enabled = []
        selected = self.config.get("selected_provider")
        for name, config in self.config.get("providers", {}).items():
            provider = self.get_provider(name)
            has_key = bool(provider.get("api_keys") or str(provider.get("api_key") or "").strip())
            is_selected = name == selected
            if (provider.get("enabled") or is_selected) and has_key:
                enabled.append(name)
        return sorted(enabled, key=lambda x: self.config["providers"].get(x, {}).get("priority", 999))

    def get_fallback_chain(self, preferred: Optional[str] = None) -> List[str]:
        enabled = self.get_enabled_providers()
        if preferred and preferred in enabled:
            enabled = [preferred] + [p for p in enabled if p != preferred]
        return enabled

    def set_selected_provider(self, provider_name: str) -> str:
        if provider_name in self.config.get("providers", {}):
            self.config["selected_provider"] = provider_name
            self.save()
        return self.config.get("selected_provider", "groq")

    def add_custom_provider(self, provider_name: str, *, model: Optional[str] = None, base_url: Optional[str] = None, provider_type: Optional[str] = "openai_compatible", enabled: bool = True, api_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        normalized = str(provider_name or "").strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("El nombre del proveedor no puede estar vacío.")
        provider = self.config.setdefault("providers", {}).setdefault(normalized, {})
        provider.setdefault("enabled", bool(enabled))
        provider.setdefault("type", provider_type or "openai_compatible")
        if base_url is not None:
            provider.setdefault("base_url", normalize_provider_url(base_url, provider_type or "openai_compatible"))
        else:
            provider.setdefault("base_url", "")
        provider.setdefault("model", str(model or "").strip())
        provider.setdefault("models", [])
        if isinstance(provider.get("models"), list):
            models = [str(m).strip() for m in provider["models"] if str(m).strip()]
            if model and model not in models:
                models.insert(0, str(model).strip())
            provider["models"] = models
        if api_keys is not None:
            self.set_provider_keys(normalized, api_keys)
        self.save()
        return provider

    def get_provider_models(self, provider_name: str) -> List[str]:
        provider = self.get_provider(provider_name)
        models = provider.get("models") or []
        models = [m for m in models if isinstance(m, str) and m.strip()]
        if not models and str(provider.get("model") or "").strip():
            models = [str(provider.get("model"))]
        return models

    def discover_provider_models(self, provider_name: str, timeout: int = 8) -> List[str]:
        """Obtiene IDs desde ``/models`` cuando el endpoint del proveedor lo permite."""
        if requests is None:
            return []
        provider = self.get_provider(provider_name)
        if str(provider.get("type") or "openai_compatible").lower() != "openai_compatible":
            return []
        base_url = normalize_provider_url(provider.get("base_url", ""), "openai_compatible")
        if not base_url:
            return []
        models_url = base_url.removesuffix("/chat/completions").rstrip("/") + "/models"
        headers = {}
        api_key = self.get_provider_api_key(provider_name)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = requests.get(models_url, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            discovered = [
                str(item.get("id", "")).strip()
                for item in (data.get("data") or [])
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
        except Exception:
            return []
        if not discovered:
            return []
        self.set_provider_models(provider_name, discovered)
        return discovered

    def _provider_model_candidates(self, provider_name: str, provider: Optional[Dict[str, Any]] = None) -> List[str]:
        provider = provider or self.get_provider(provider_name)
        models = list(provider.get("models") or []) if isinstance(provider.get("models"), list) else []
        current_model = str(provider.get("model") or "").strip()
        # Primero respeta la elección del usuario; si el endpoint rechaza ese ID,
        # conserva el comportamiento tolerante y prueba los modelos de la misma key.
        candidates = [current_model] if current_model else []
        candidates.extend(str(model).strip() for model in models if str(model).strip())
        candidates = list(dict.fromkeys(candidates))
        if candidates:
            return candidates
        return [str(model).strip() for model in models if str(model).strip()]

    def set_provider_model(self, provider_name: str, model_name: str) -> Dict[str, Any]:
        provider = self.config.setdefault("providers", {}).setdefault(provider_name, {})
        if model_name:
            provider["model"] = str(model_name).strip()
            models = provider.get("models") or []
            if isinstance(models, list):
                if str(model_name).strip() not in models:
                    models.append(str(model_name).strip())
                provider["models"] = models
        self.save()
        return provider

    def set_provider_models(self, provider_name: str, models: Iterable[str]) -> Dict[str, Any]:
        provider = self.config.setdefault("providers", {}).setdefault(provider_name, {})
        cleaned = _sanitize_provider_models(provider_name, models)
        provider["models"] = cleaned
        current = str(provider.get("model") or "").strip()
        provider["model"] = current if current in cleaned else ""
        self.save()
        return provider

    def remove_provider_model(self, provider_name: str, model_name: str) -> Dict[str, Any]:
        provider = self.config.setdefault("providers", {}).setdefault(provider_name, {})
        target = str(model_name or "").strip()
        models = [str(model).strip() for model in provider.get("models", []) if str(model).strip() and str(model).strip() != target]
        provider["models"] = models
        if str(provider.get("model") or "").strip() == target:
            provider["model"] = models[0] if models else ""
        self.save()
        return provider

    def remove_provider(self, provider_name: str) -> bool:
        providers = self.config.setdefault("providers", {})
        if provider_name not in providers:
            return False
        del providers[provider_name]
        if self.config.get("selected_provider") == provider_name:
            self.config["selected_provider"] = next(iter(providers), "")
        self.save()
        return True

    def mask_key(self, api_key: str) -> str:
        if not api_key:
            return ""
        key = str(api_key).strip()
        if len(key) <= 8:
            return "***"
        return f"{key[:3]}...{key[-3:]}"

    def _call_openai_compatible(self, provider_name: str, prompt: str, system_prompt: Optional[str] = None, timeout: int = 30, api_key: Optional[str] = None) -> Optional[str]:
        if requests is None:
            return None

        provider = self.get_provider(provider_name)
        api_key = (api_key or self.get_provider_api_key(provider_name) or str(provider.get("api_key") or "")).strip()
        if not api_key:
            return None

        base_url = str(provider.get("base_url", "") or "").rstrip("/")
        if str(provider.get("type") or "").lower() == "openai_compatible":
            if base_url.endswith("/v1"):
                base_url = f"{base_url}/chat/completions"

        last_exc = None
        for model_name in self._provider_model_candidates(provider_name, provider):
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt or "Eres Jarvis, un asistente útil."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            try:
                response = requests.post(base_url, headers=headers, json=payload, timeout=timeout)
                if response.status_code in (401, 403):
                    raise PermissionError(f"{provider_name} key inválida o sin permisos ({response.status_code})")
                if response.status_code == 404:
                    last_exc = RuntimeError(f"{provider_name} no soporta el modelo {model_name} (404)")
                    continue
                if response.status_code >= 400:
                    body = _redact_sensitive_text(response.text[:400].replace("\n", " "))
                    print(f"[AI Provider] {provider_name} HTTP {response.status_code} con modelo {model_name}: {body}")
                    last_exc = RuntimeError(f"{provider_name} devolvió HTTP {response.status_code} para {model_name}: {body}")
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    raise ValueError(f"No response content for {provider_name}")
                self.last_model_name = model_name
                return choices[0].get("message", {}).get("content", "")
            except Exception as exc:  # pragma: no cover - robust fallback
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError(f"No se pudo obtener respuesta de {provider_name}")

    def _call_gemini(self, provider_name: str, prompt: str, system_prompt: Optional[str] = None, timeout: int = 30, api_key: Optional[str] = None) -> Optional[str]:
        if requests is None:
            return None

        provider = self.get_provider(provider_name)
        api_key = (api_key or self.get_provider_api_key(provider_name) or str(provider.get("api_key") or "")).strip()
        if not api_key:
            return None

        last_exc = None
        for model_name in self._provider_model_candidates(provider_name, provider):
            url = f"{provider.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/models')}/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "system_instruction": {"parts": [{"text": system_prompt or "Eres Jarvis."}]},
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
            }
            try:
                response = requests.post(url, json=payload, timeout=timeout)
                if response.status_code in (401, 403):
                    raise PermissionError(f"{provider_name} key inválida o sin permisos ({response.status_code})")
                if response.status_code == 404:
                    last_exc = RuntimeError(f"{provider_name} no soporta el modelo {model_name} (404)")
                    continue
                if response.status_code >= 400:
                    body = _redact_sensitive_text(response.text[:400].replace("\n", " "))
                    print(f"[AI Provider] {provider_name} HTTP {response.status_code} con modelo {model_name}: {body}")
                    last_exc = RuntimeError(f"{provider_name} devolvió HTTP {response.status_code} para {model_name}: {body}")
                    continue
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    raise ValueError(f"No candidates for {provider_name}")
                parts = candidates[0].get("content", {}).get("parts", [])
                text_parts = []
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                self.last_model_name = model_name
                return "".join(text_parts)
            except Exception as exc:  # pragma: no cover - robust fallback
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError(f"No se pudo obtener respuesta de {provider_name}")

    def _call_anthropic(self, provider_name: str, prompt: str, system_prompt: Optional[str] = None, timeout: int = 30, api_key: Optional[str] = None) -> Optional[str]:
        if requests is None:
            return None

        provider = self.get_provider(provider_name)
        api_key = (api_key or self.get_provider_api_key(provider_name) or str(provider.get("api_key") or "")).strip()
        if not api_key:
            return None

        last_exc = None
        for model_name in self._provider_model_candidates(provider_name, provider):
            payload = {
                "model": model_name,
                "max_tokens": 1500,
                "system": system_prompt or "Eres Jarvis, un asistente útil.",
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            try:
                response = requests.post(provider.get("base_url", "https://api.anthropic.com/v1/messages"), headers=headers, json=payload, timeout=timeout)
                if response.status_code in (401, 403):
                    raise PermissionError(f"{provider_name} key inválida o sin permisos ({response.status_code})")
                if response.status_code == 404:
                    last_exc = RuntimeError(f"{provider_name} no soporta el modelo {model_name} (404)")
                    continue
                response.raise_for_status()
                data = response.json()
                content = data.get("content") or []
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                self.last_model_name = model_name
                return "".join(parts)
            except Exception as exc:  # pragma: no cover - robust fallback
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError(f"No se pudo obtener respuesta de {provider_name}")

    def _call_ollama(self, provider_name: str, prompt: str, system_prompt: Optional[str] = None, timeout: int = 30, api_key: Optional[str] = None) -> Optional[str]:
        if requests is None:
            return None

        provider = self.get_provider(provider_name)
        model = provider.get("model", "llama3.1")
        url = provider.get("base_url", "http://localhost:11434/api/chat")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt or "Eres Jarvis."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        message = (data.get("message") or {}).get("content")
        self.last_model_name = str(model)
        return message

    def _invoke_provider(self, provider_name: str, prompt: str, system_prompt: Optional[str] = None, timeout: int = 30) -> Optional[str]:
        provider = self.get_provider(provider_name)
        provider_type = str(provider.get("type") or "openai_compatible").lower()
        keys = self.provider_api_keys(provider_name)

        last_exc = None
        for api_key in keys or [""]:
            try:
                if provider_type == "gemini":
                    result = self._call_gemini(provider_name, prompt, system_prompt=system_prompt, timeout=timeout, api_key=api_key)
                elif provider_type == "anthropic":
                    result = self._call_anthropic(provider_name, prompt, system_prompt=system_prompt, timeout=timeout, api_key=api_key)
                elif provider_type == "ollama":
                    result = self._call_ollama(provider_name, prompt, system_prompt=system_prompt, timeout=timeout, api_key=api_key)
                else:
                    result = self._call_openai_compatible(provider_name, prompt, system_prompt=system_prompt, timeout=timeout, api_key=api_key)
                if result and str(result).strip():
                    return result
            except Exception as exc:  # pragma: no cover - robust fallback
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return None

    def generate(self, prompt: str, preferred: Optional[str] = None, system_prompt: Optional[str] = None, timeout: int = 30) -> str:
        """Usa fallback automático entre proveedores disponibles."""
        self.last_model_name = None
        provider_chain = self.get_fallback_chain(preferred)
        if not provider_chain:
            raise RuntimeError("No hay ningún proveedor activo y con API key disponible.")
        for provider_name in provider_chain:
            try:
                result = self._invoke_provider(provider_name, prompt, system_prompt=system_prompt, timeout=timeout)
                if result and str(result).strip():
                    self.last_provider_name = provider_name
                    print(f"[IA] Respuesta generada con: {provider_name} | modelo={self.last_model_name or 'desconocido'}")
                    return result.strip()
            except Exception as exc:  # pragma: no cover - robust fallback
                print(f"[AI Provider] {provider_name} falló: {_redact_sensitive_text(exc)}")
        raise RuntimeError("No hay ningún proveedor activo y con API key disponible.")

    def normalized_config(self) -> Dict[str, Any]:
        return {
            "selected_provider": self.config.get("selected_provider", "groq"),
            "providers": {
                name: {
                    "enabled": config.get("enabled", False),
                    "api_key": self.mask_key(config.get("api_key", "")),
                    "model": config.get("model"),
                    "type": config.get("type"),
                    "priority": config.get("priority", 999),
                }
                for name, config in self.config.get("providers", {}).items()
            },
        }


if __name__ == "__main__":
    manager = AIProviderManager()
    print(json.dumps(manager.normalized_config(), indent=2, ensure_ascii=False))
