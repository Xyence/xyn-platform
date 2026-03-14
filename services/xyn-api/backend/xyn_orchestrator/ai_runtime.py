import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from cryptography.fernet import Fernet

from .ai_compat import compute_effective_params
from .models import (
    AgentDefinition,
    AgentDefinitionPurpose,
    AgentPurpose,
    ContextPack,
    ModelConfig,
    ModelProvider,
    OpenAIConfig,
    ProviderCredential,
    SecretRef,
    SecretStore,
)
from .oidc import resolve_secret_ref
from .secret_stores import normalize_secret_logical_name, write_secret_value

logger = logging.getLogger(__name__)

DEFAULT_ASSISTANT_PROMPT = ""

PROVIDER_ENV_API_KEY = {
    "openai": ["XYN_OPENAI_API_KEY", "OPENAI_API_KEY"],
    "anthropic": ["XYN_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"],
    "google": ["XYN_GEMINI_API_KEY", "XYN_GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
}
PROVIDER_MODEL_DEFAULTS = {
    "openai": "gpt-5-mini",
    "google": "gemini-2.0-flash",
    "anthropic": "claude-3-7-sonnet-latest",
}
BOOTSTRAP_ROLE_ENV_PREFIX = {
    "planning": "XYN_AI_PLANNING",
    "coding": "XYN_AI_CODING",
}
BOOTSTRAP_ROLE_AGENT_META = {
    "default": {
        "slug": "default-assistant",
        "name": "Xyn Default Assistant",
        "purposes": ("coding", "planning", "documentation"),
        "is_default": True,
    },
    "planning": {
        "slug": "planning-assistant",
        "name": "Xyn Planning Assistant",
        "purposes": ("planning",),
        "is_default": False,
    },
    "coding": {
        "slug": "coding-assistant",
        "name": "Xyn Coding Assistant",
        "purposes": ("coding",),
        "is_default": False,
    },
}
BOOTSTRAP_CONTEXT_PACK_SPECS = {
    "planning": {
        "name": "xyn-planner-canon",
        "purpose": "planner",
        "filename": "xyn-planner-canon.md",
        "version": "1.0.0",
    },
    "coding": {
        "name": "xyn-coder-canon",
        "purpose": "coder",
        "filename": "xyn-coder-canon.md",
        "version": "1.0.0",
    },
}


class AiConfigError(RuntimeError):
    pass


class AiInvokeError(RuntimeError):
    pass


def _extract_openai_response_text(data: Dict[str, Any]) -> str:
    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct
    chunks: List[str] = []
    output_items = data.get("output") if isinstance(data.get("output"), list) else []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        content_items = item.get("content") if isinstance(item.get("content"), list) else []
        for content in content_items:
            if not isinstance(content, dict):
                continue
            part_type = str(content.get("type") or "").strip().lower()
            text_value = str(content.get("text") or content.get("output_text") or "").strip()
            if text_value:
                chunks.append(text_value)
                continue
            # Some responses return structured text payloads.
            text_obj = content.get("text")
            if isinstance(text_obj, dict):
                nested = str(text_obj.get("value") or "").strip()
                if nested:
                    chunks.append(nested)
                    continue
            if part_type == "refusal":
                refusal = str(content.get("refusal") or "").strip()
                if refusal:
                    chunks.append(f"Model refusal: {refusal}")
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def assemble_system_prompt(agent_prompt: Optional[str], purpose_preamble: Optional[str]) -> str:
    preamble = str(purpose_preamble or "").strip()
    prompt = str(agent_prompt or "").strip()
    if preamble and prompt:
        return f"{preamble}\n\n{prompt}"
    return preamble or prompt


def _fernet() -> Fernet:
    raw = str(os.environ.get("XYN_CREDENTIALS_ENCRYPTION_KEY") or os.environ.get("XYN_SECRET_KEY") or "").strip()
    if not raw:
        raise AiConfigError("Missing XYN_CREDENTIALS_ENCRYPTION_KEY")
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    value = str(api_key or "").strip()
    if not value:
        raise AiConfigError("api_key is required")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    value = str(ciphertext or "").strip()
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise AiConfigError("Credential decryption failed") from exc


def mask_secret(secret: str) -> Dict[str, Any]:
    value = str(secret or "")
    if not value:
        return {"has_value": False, "masked": None, "last4": None}
    last4 = value[-4:] if len(value) >= 4 else value
    return {"has_value": True, "masked": "***" + last4, "last4": last4}


def _read_provider_env_key(provider_slug: str) -> str:
    for key in PROVIDER_ENV_API_KEY.get(provider_slug, []):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_provider_slug(provider_slug: str) -> str:
    raw = str(provider_slug or "").strip().lower()
    if raw in {"gemini", "google"}:
        return "google"
    if raw in {"openai", "anthropic"}:
        return raw
    return ""


def _bootstrap_context_pack_root() -> Path:
    return Path(__file__).resolve().parents[1] / "context_packs"


def _serialize_context_pack_ref(pack: Optional[ContextPack]) -> Optional[Dict[str, Any]]:
    if pack is None:
        return None
    return {
        "id": str(pack.id),
        "name": pack.name,
        "purpose": pack.purpose,
        "scope": pack.scope,
        "version": pack.version,
    }


def _ensure_bootstrap_context_pack(role_slug: str) -> List[Dict[str, Any]]:
    spec = BOOTSTRAP_CONTEXT_PACK_SPECS.get(role_slug)
    if not spec:
        return []
    pack = (
        ContextPack.objects.filter(
            name=spec["name"],
            purpose=spec["purpose"],
            scope="global",
            version=spec["version"],
            namespace="",
            project_key="",
        )
        .order_by("-is_active", "-updated_at")
        .first()
    )
    content_path = _bootstrap_context_pack_root() / spec["filename"]
    content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""
    defaults = {
        "purpose": spec["purpose"],
        "scope": "global",
        "namespace": "",
        "project_key": "",
        "version": spec["version"],
        "is_active": True,
        "is_default": True,
        "content_markdown": content,
    }
    if pack is None:
        if not content:
            return []
        pack = ContextPack.objects.create(name=spec["name"], **defaults)
    else:
        update_fields: List[str] = []
        for field, value in defaults.items():
            if getattr(pack, field) != value and (field != "content_markdown" or content):
                setattr(pack, field, value)
                update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            pack.save(update_fields=update_fields)
    ref = _serialize_context_pack_ref(pack)
    return [ref] if ref else []


def _read_bootstrap_role_spec(role_slug: str) -> Optional[Dict[str, str]]:
    if role_slug == "default":
        provider_slug = _normalize_provider_slug(
            os.environ.get("XYN_AI_PROVIDER")
            or os.environ.get("XYN_DEFAULT_MODEL_PROVIDER")
            or "openai"
        )
        if not provider_slug:
            provider_slug = "openai"
        model_name = str(
            os.environ.get("XYN_AI_MODEL")
            or os.environ.get("XYN_DEFAULT_MODEL_NAME")
            or PROVIDER_MODEL_DEFAULTS.get(provider_slug, "gpt-5-mini")
        ).strip()
        api_key = _read_provider_env_key(provider_slug)
        if not api_key and provider_slug == "openai":
            legacy = OpenAIConfig.objects.first()
            api_key = str(legacy.api_key if legacy else "").strip()
        if not api_key:
            return None
        return {
            "role": role_slug,
            "provider_slug": provider_slug,
            "model_name": model_name,
            "api_key": api_key,
        }

    prefix = BOOTSTRAP_ROLE_ENV_PREFIX[role_slug]
    raw_provider = str(os.environ.get(f"{prefix}_PROVIDER") or "").strip()
    raw_model = str(os.environ.get(f"{prefix}_MODEL") or "").strip()
    raw_key = str(os.environ.get(f"{prefix}_API_KEY") or "").strip()
    if not raw_provider and not raw_model and not raw_key:
        return None
    if not raw_provider or not raw_model or not raw_key:
        raise AiConfigError(
            f"{prefix}_PROVIDER, {prefix}_MODEL, and {prefix}_API_KEY are required when configuring the {role_slug} bootstrap agent."
        )
    provider_slug = _normalize_provider_slug(raw_provider)
    if not provider_slug:
        raise AiConfigError(f"Unsupported provider '{raw_provider}' for {role_slug} bootstrap agent.")
    return {
        "role": role_slug,
        "provider_slug": provider_slug,
        "model_name": raw_model,
        "api_key": raw_key,
    }


def _bootstrap_secret_logical_name(provider_slug: str, api_key: str) -> str:
    fingerprint = hashlib.sha256(f"{provider_slug}:{api_key}".encode("utf-8")).hexdigest()[:12]
    return normalize_secret_logical_name(f"ai/{provider_slug}/bootstrap/{fingerprint}/api_key")


def _ensure_bootstrap_credential(
    *,
    provider: ModelProvider,
    api_key: str,
    credential_cache: Dict[tuple[str, str], ProviderCredential],
) -> ProviderCredential:
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    cache_key = (str(provider.id), fingerprint)
    cached = credential_cache.get(cache_key)
    if cached:
        return cached

    for credential in ProviderCredential.objects.filter(provider=provider, enabled=True).order_by("-is_default", "name", "-updated_at"):
        if _credential_api_key(credential, provider.slug) == api_key:
            credential_cache[cache_key] = credential
            return credential

    store = SecretStore.objects.filter(is_default=True).first()
    if not store:
        credential = ProviderCredential.objects.create(
            provider=provider,
            name=f"{provider.slug}-bootstrap-{fingerprint[:8]}",
            auth_type="api_key",
            api_key_encrypted=encrypt_api_key(api_key),
            is_default=False,
            enabled=True,
        )
        credential_cache[cache_key] = credential
        return credential

    logical = _bootstrap_secret_logical_name(provider.slug, api_key)
    secret_ref = SecretRef.objects.filter(scope_kind="platform", scope_id__isnull=True, name=logical).first()
    if not secret_ref:
        secret_ref = SecretRef.objects.create(
            name=logical,
            scope_kind="platform",
            scope_id=None,
            store=store,
            external_ref="pending",
            type="secrets_manager",
            description=f"{provider.slug} bootstrap AI API key",
        )
    try:
        external_ref, metadata = write_secret_value(
            store,
            logical_name=logical,
            scope_kind="platform",
            scope_id=None,
            scope_path_id=None,
            secret_ref_id=str(secret_ref.id),
            value=api_key,
            description=f"{provider.slug} bootstrap AI API key",
        )
        secret_ref.external_ref = external_ref
        secret_ref.metadata_json = {**(secret_ref.metadata_json or {}), **metadata}
        secret_ref.save(update_fields=["external_ref", "metadata_json", "updated_at"])
        credential = ProviderCredential.objects.create(
            provider=provider,
            name=f"{provider.slug}-bootstrap-{fingerprint[:8]}",
            auth_type="api_key",
            secret_ref=secret_ref,
            is_default=False,
            enabled=True,
        )
    except Exception:
        credential = ProviderCredential.objects.create(
            provider=provider,
            name=f"{provider.slug}-bootstrap-{fingerprint[:8]}",
            auth_type="env_ref",
            env_var_name=PROVIDER_ENV_API_KEY.get(provider.slug, [""])[0] or "",
            is_default=False,
            enabled=True,
        )
    credential_cache[cache_key] = credential
    return credential


def _ensure_bootstrap_model_config(*, provider: ModelProvider, model_name: str, credential: ProviderCredential) -> ModelConfig:
    existing = (
        ModelConfig.objects.filter(provider=provider, model_name=model_name, credential=credential)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if existing:
        return existing
    return ModelConfig.objects.create(
        provider=provider,
        credential=credential,
        model_name=model_name,
        temperature=float(os.environ.get("XYN_DEFAULT_MODEL_TEMPERATURE") or 0.2),
        max_tokens=int(os.environ.get("XYN_DEFAULT_MODEL_MAX_TOKENS") or 1200),
        top_p=float(os.environ.get("XYN_DEFAULT_MODEL_TOP_P") or 1.0),
        enabled=True,
    )


def _resolve_runtime_agent_for_purpose(purpose_slug: str) -> Optional[AgentDefinition]:
    purpose = str(purpose_slug or "").strip().lower()
    if not purpose:
        return (
            AgentDefinition.objects.select_related("model_config__provider", "model_config__credential")
            .filter(enabled=True, is_default=True)
            .order_by("-updated_at", "slug")
            .first()
        )
    purpose_default = (
        AgentDefinitionPurpose.objects.select_related("agent_definition", "agent_definition__model_config__provider", "agent_definition__model_config__credential")
        .filter(purpose__slug=purpose, is_default_for_purpose=True, agent_definition__enabled=True)
        .order_by("agent_definition__slug")
        .first()
    )
    if purpose_default:
        return purpose_default.agent_definition
    purpose_specific = (
        AgentDefinition.objects.select_related("model_config__provider", "model_config__credential")
        .filter(enabled=True, purposes__slug=purpose, is_default=False)
        .order_by("-updated_at", "slug")
        .first()
    )
    if purpose_specific:
        return purpose_specific
    fallback_default = (
        AgentDefinition.objects.select_related("model_config__provider", "model_config__credential")
        .filter(enabled=True, is_default=True)
        .order_by("-updated_at", "slug")
        .first()
    )
    if fallback_default:
        return fallback_default
    return (
        AgentDefinition.objects.select_related("model_config__provider", "model_config__credential")
        .filter(enabled=True, purposes__slug=purpose)
        .order_by("-updated_at", "slug")
        .first()
    )


def _credential_api_key(credential: Optional[ProviderCredential], provider_slug: str) -> str:
    if credential is None:
        return ""
    if not credential.enabled:
        return ""
    if credential.auth_type == "api_key":
        if credential.secret_ref_id:
            ref = SecretRef.objects.select_related("store").filter(id=credential.secret_ref_id).first()
            if ref and ref.external_ref:
                resolved = resolve_secret_ref({"type": "aws.secrets_manager", "ref": ref.external_ref})
                return str(resolved or "").strip()
        return decrypt_api_key(str(credential.api_key_encrypted or ""))
    env_var = str(credential.env_var_name or "").strip()
    if not env_var:
        return ""
    return str(os.environ.get(env_var) or "").strip()


def _resolve_model_api_key(provider_slug: str, credential: Optional[ProviderCredential]) -> str:
    selected_credential = credential
    if selected_credential is None:
        selected_credential = (
            ProviderCredential.objects.filter(provider__slug=provider_slug, is_default=True, enabled=True)
            .order_by("-updated_at", "-created_at")
            .first()
        )
    api_key = _credential_api_key(selected_credential, provider_slug)
    if api_key:
        return api_key
    return _read_provider_env_key(provider_slug)


def _serialize_messages_for_provider(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cooked: List[Dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        content = str(message.get("content") or "")
        if role not in {"system", "user", "assistant"}:
            role = "user"
        cooked.append({"role": role, "content": content})
    return cooked


def resolve_ai_config(*, purpose_slug: Optional[str] = None, agent_slug: Optional[str] = None) -> Dict[str, Any]:
    purpose = str(purpose_slug or "").strip().lower()
    agent = None
    if agent_slug:
        agent = (
            AgentDefinition.objects.select_related("model_config__provider", "model_config__credential")
            .filter(slug=agent_slug, enabled=True)
            .first()
        )
    if agent is None:
        agent = _resolve_runtime_agent_for_purpose(purpose)
    if not purpose:
        if agent:
            first_purpose = agent.purposes.order_by("slug").first()
            purpose = str(first_purpose.slug if first_purpose else "coding")
        else:
            purpose = "coding"
    purpose_obj = AgentPurpose.objects.filter(slug=purpose).first()
    purpose_preamble = str(getattr(purpose_obj, "preamble", "") or "")
    if agent:
        model_config = purpose_obj.model_config if purpose_obj and purpose_obj.model_config_id else agent.model_config
        provider = model_config.provider
        credential = model_config.credential
        api_key = _resolve_model_api_key(provider.slug, credential)
        if not api_key:
            raise AiConfigError(
                f"No credential resolved for provider '{provider.slug}' on agent '{agent.slug}'."
            )
        return {
            "provider": provider.slug,
            "model_name": model_config.model_name,
            "model_config_id": str(model_config.id),
            "api_key": api_key,
            "temperature": model_config.temperature,
            "top_p": model_config.top_p,
            "max_tokens": model_config.max_tokens,
            "system_prompt": assemble_system_prompt(agent.system_prompt_text, purpose_preamble),
            "agent_slug": agent.slug,
            "agent_id": str(agent.id),
            "purpose": purpose,
            "purpose_default_context_pack_refs_json": (purpose_obj.default_context_pack_refs_json if purpose_obj else None) or [],
            "agent_context_pack_refs_json": agent.context_pack_refs_json or [],
        }

    provider_alias = str(
        os.environ.get("XYN_AI_PROVIDER")
        or os.environ.get("XYN_DEFAULT_MODEL_PROVIDER")
        or "openai"
    ).strip().lower()
    provider_slug = "google" if provider_alias in {"google", "gemini"} else provider_alias
    model_name = str(
        os.environ.get("XYN_AI_MODEL")
        or os.environ.get("XYN_DEFAULT_MODEL_NAME")
        or PROVIDER_MODEL_DEFAULTS.get(provider_slug, "gpt-5-mini")
    ).strip()
    provider = ModelProvider.objects.filter(slug=provider_slug).first() or ModelProvider.objects.filter(slug="openai").first()
    if provider:
        provider_slug = provider.slug

    api_key = _read_provider_env_key(provider_slug)
    if not api_key:
        raise AiConfigError(
            f"No agent configured for purpose '{purpose}' and no env key found for provider '{provider_slug}'."
        )

    return {
        "provider": provider_slug,
        "model_name": model_name,
        "model_config_id": str(purpose_obj.model_config_id) if purpose_obj and purpose_obj.model_config_id else None,
        "api_key": api_key,
        "temperature": float(os.environ.get("XYN_DEFAULT_MODEL_TEMPERATURE") or 0.2),
        "top_p": float(os.environ.get("XYN_DEFAULT_MODEL_TOP_P") or 1.0),
        "max_tokens": int(os.environ.get("XYN_DEFAULT_MODEL_MAX_TOKENS") or 1200),
        "system_prompt": "",
        "agent_slug": None,
        "agent_id": None,
        "purpose": purpose,
        "purpose_default_context_pack_refs_json": (purpose_obj.default_context_pack_refs_json if purpose_obj else None) or [],
        "agent_context_pack_refs_json": [],
    }


def invoke_model(*, resolved_config: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    provider = str(resolved_config.get("provider") or "").strip().lower()
    model_name = str(resolved_config.get("model_name") or "").strip()
    api_key = str(resolved_config.get("api_key") or "").strip()
    if not provider or not model_name or not api_key:
        raise AiInvokeError("provider/model/api_key are required")

    payload_messages = [msg for msg in _serialize_messages_for_provider(messages) if msg.get("role") != "system"]
    system_prompt = str(resolved_config.get("system_prompt") or "").strip()
    if system_prompt:
        payload_messages = [{"role": "system", "content": system_prompt}] + payload_messages

    base_params = {
        "temperature": resolved_config.get("temperature"),
        "top_p": resolved_config.get("top_p"),
        "max_tokens": resolved_config.get("max_tokens"),
    }
    effective_params, warnings = compute_effective_params(
        provider=provider,
        model_name=model_name,
        base_params=base_params,
        invocation_mode="chat",
    )
    temperature = effective_params.get("temperature")
    top_p = effective_params.get("top_p")
    max_tokens = effective_params.get("max_tokens")

    if provider == "openai":
        body: Dict[str, Any] = {
            "model": model_name,
            "input": payload_messages,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise AiInvokeError(f"OpenAI error ({response.status_code}): {response.text[:300]}")
        data = response.json()
        content = _extract_openai_response_text(data)
        return {
            "content": content,
            "provider": provider,
            "model": model_name,
            "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
            "effective_params": effective_params,
            "warnings": warnings,
            "raw": data,
        }

    if provider == "anthropic":
        system_text = ""
        anthro_messages: List[Dict[str, str]] = []
        for message in payload_messages:
            role = message.get("role")
            if role == "system":
                system_text = (system_text + "\n\n" + str(message.get("content") or "")).strip()
            else:
                anthro_messages.append({"role": role or "user", "content": str(message.get("content") or "")})
        body = {"model": model_name, "messages": anthro_messages, "max_tokens": int(max_tokens or 1200)}
        if system_text:
            body["system"] = system_text
        if temperature is not None:
            body["temperature"] = float(temperature)
        if top_p is not None:
            body["top_p"] = float(top_p)
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise AiInvokeError(f"Anthropic error ({response.status_code}): {response.text[:300]}")
        data = response.json()
        output_parts = data.get("content") if isinstance(data.get("content"), list) else []
        text_chunks: List[str] = []
        for part in output_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text_chunks.append(str(part.get("text") or ""))
        return {
            "content": "\n".join(chunk for chunk in text_chunks if chunk).strip(),
            "provider": provider,
            "model": model_name,
            "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
            "effective_params": effective_params,
            "warnings": warnings,
            "raw": data,
        }

    if provider == "google":
        # Gemini API
        user_parts: List[Dict[str, Any]] = []
        for message in payload_messages:
            user_parts.append({"text": str(message.get("content") or "")})
        body = {
            "contents": [{"role": "user", "parts": user_parts}],
            "generationConfig": {
                "temperature": float(temperature if temperature is not None else 0.2),
                "maxOutputTokens": int(max_tokens or 1200),
            },
        }
        if top_p is not None:
            body["generationConfig"]["topP"] = float(top_p)
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise AiInvokeError(f"Google error ({response.status_code}): {response.text[:300]}")
        data = response.json()
        candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        text = ""
        if candidates:
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
            parts = content.get("parts") if isinstance(content, dict) else []
            texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
            text = "\n".join(chunk for chunk in texts if chunk).strip()
        return {
            "content": text,
            "provider": provider,
            "model": model_name,
            "usage": None,
            "effective_params": effective_params,
            "warnings": warnings,
            "raw": data,
        }

    raise AiInvokeError(f"Unsupported provider '{provider}'")


def ensure_default_ai_seeds() -> None:
    ai_enabled_raw = str(os.environ.get("XYN_AI_ENABLED") or "").strip().lower()
    provider_env_raw = str(
        os.environ.get("XYN_AI_PROVIDER")
        or os.environ.get("XYN_DEFAULT_MODEL_PROVIDER")
        or ""
    ).strip().lower()
    if ai_enabled_raw in {"0", "false", "no"} or provider_env_raw in {"none", "disabled"}:
        logger.info("AI bootstrap skipped: provider disabled by runtime config")
        return

    provider_specs = [
        ("openai", "OpenAI", True),
        ("anthropic", "Anthropic", True),
        ("google", "Google", True),
    ]
    provider_map: Dict[str, ModelProvider] = {}
    for slug, name, enabled in provider_specs:
        provider, _ = ModelProvider.objects.get_or_create(slug=slug, defaults={"name": name, "enabled": enabled})
        provider_map[slug] = provider

    role_specs = {
        role: spec
        for role in ("default", "planning", "coding")
        for spec in [ _read_bootstrap_role_spec(role) ]
        if spec is not None
    }
    if "default" not in role_specs:
        return

    credential_cache: Dict[tuple[str, str], ProviderCredential] = {}
    role_models: Dict[str, ModelConfig] = {}
    for role, spec in role_specs.items():
        provider = provider_map.get(spec["provider_slug"])
        if not provider:
            continue
        credential = _ensure_bootstrap_credential(
            provider=provider,
            api_key=spec["api_key"],
            credential_cache=credential_cache,
        )
        model_config = _ensure_bootstrap_model_config(
            provider=provider,
            model_name=spec["model_name"],
            credential=credential,
        )
        role_models[role] = model_config

    default_model = role_models.get("default")

    coding, _ = AgentPurpose.objects.get_or_create(
        slug="coding",
        defaults={
            "name": "Coding",
            "description": "Code generation and development tasks",
            "status": "active",
            "enabled": True,
            "preamble": "Purpose: coding. Focus on production-ready implementation guidance.",
            "model_config": default_model,
        },
    )
    planning, _ = AgentPurpose.objects.get_or_create(
        slug="planning",
        defaults={
            "name": "Planning",
            "description": "Planning, decomposition, and implementation strategy tasks",
            "status": "active",
            "enabled": True,
            "preamble": "Purpose: planning. Focus on decomposition, sequencing, and implementation guidance.",
            "model_config": role_models.get("planning") or default_model,
        },
    )
    documentation, _ = AgentPurpose.objects.get_or_create(
        slug="documentation",
        defaults={
            "name": "Documentation",
            "description": "Documentation drafting and editing",
            "status": "active",
            "enabled": True,
            "preamble": "Purpose: documentation. Produce concise, accurate, publishable drafts.",
            "model_config": default_model,
        },
    )

    if not coding.name:
        coding.name = "Coding"
    if not coding.preamble:
        coding.preamble = "Purpose: coding. Focus on production-ready implementation guidance."
    if default_model and coding.model_config_id != default_model.id:
        coding.model_config = default_model
    coding.default_context_pack_refs_json = _ensure_bootstrap_context_pack("coding")
    coding.save(update_fields=["name", "preamble", "model_config", "default_context_pack_refs_json", "updated_at"])
    if not planning.name:
        planning.name = "Planning"
    if not planning.preamble:
        planning.preamble = "Purpose: planning. Focus on decomposition, sequencing, and implementation guidance."
    planning_model = role_models.get("planning") or default_model
    if planning_model and planning.model_config_id != planning_model.id:
        planning.model_config = planning_model
    planning.default_context_pack_refs_json = _ensure_bootstrap_context_pack("planning")
    planning.save(update_fields=["name", "preamble", "model_config", "default_context_pack_refs_json", "updated_at"])
    if not documentation.name:
        documentation.name = "Documentation"
    if not documentation.preamble:
        documentation.preamble = "Purpose: documentation. Produce concise, accurate, publishable drafts."
    if default_model and documentation.model_config_id != default_model.id:
        documentation.model_config = default_model
    documentation.save(update_fields=["name", "preamble", "model_config", "updated_at"])

    role_agents: Dict[str, AgentDefinition] = {}
    for role, meta in BOOTSTRAP_ROLE_AGENT_META.items():
        model_config = role_models.get(role)
        if model_config is None:
            continue
        agent, _ = AgentDefinition.objects.get_or_create(
            slug=meta["slug"],
            defaults={
                "name": meta["name"],
                "model_config": model_config,
                "system_prompt_text": DEFAULT_ASSISTANT_PROMPT if role == "default" else "",
                "context_pack_refs_json": _ensure_bootstrap_context_pack(role) if role in {"planning", "coding"} else [],
                "is_default": bool(meta["is_default"]),
                "enabled": True,
            },
        )
        update_fields = ["name", "model_config", "is_default", "enabled", "updated_at"]
        if role in {"planning", "coding"}:
            agent.context_pack_refs_json = _ensure_bootstrap_context_pack(role)
            update_fields.append("context_pack_refs_json")
        if role == "default" and DEFAULT_ASSISTANT_PROMPT and not str(agent.system_prompt_text or "").strip():
            agent.system_prompt_text = DEFAULT_ASSISTANT_PROMPT
            update_fields.append("system_prompt_text")
        agent.name = meta["name"]
        agent.model_config = model_config
        agent.is_default = bool(meta["is_default"])
        agent.enabled = True
        agent.save(update_fields=update_fields)
        desired_purposes = list(AgentPurpose.objects.filter(slug__in=meta["purposes"]))
        AgentDefinitionPurpose.objects.filter(agent_definition=agent).exclude(purpose__in=desired_purposes).delete()
        for purpose in desired_purposes:
            AgentDefinitionPurpose.objects.get_or_create(agent_definition=agent, purpose=purpose)
        role_agents[role] = agent
    if "default" in role_agents:
        AgentDefinition.objects.exclude(id=role_agents["default"].id).filter(is_default=True).update(is_default=False)
    for purpose_slug, owner_role in {
        "planning": "planning" if "planning" in role_agents else "default",
        "coding": "coding" if "coding" in role_agents else "default",
    }.items():
        AgentDefinitionPurpose.objects.filter(purpose__slug=purpose_slug, is_default_for_purpose=True).exclude(
            agent_definition=role_agents.get(owner_role)
        ).update(is_default_for_purpose=False)
        owner = role_agents.get(owner_role)
        if owner:
            link = AgentDefinitionPurpose.objects.filter(agent_definition=owner, purpose__slug=purpose_slug).first()
            if link and not link.is_default_for_purpose:
                link.is_default_for_purpose = True
                link.save(update_fields=["is_default_for_purpose"])
    # Remove the legacy bootstrap agent to keep a single canonical default assistant.
    if "default" in role_agents:
        AgentDefinition.objects.filter(slug="documentation-default").exclude(id=role_agents["default"].id).delete()
        AgentDefinition.objects.filter(name__iexact="Documentation Default").exclude(id=role_agents["default"].id).delete()


def get_default_agent_bootstrap_status() -> Dict[str, Any]:
    provider_alias = str(
        os.environ.get("XYN_AI_PROVIDER")
        or os.environ.get("XYN_DEFAULT_MODEL_PROVIDER")
        or ""
    ).strip().lower()
    if provider_alias in {"gemini", "google"}:
        provider_slug = "google"
        provider_label = "gemini"
    else:
        provider_slug = provider_alias
        provider_label = provider_alias
    model_name = str(
        os.environ.get("XYN_AI_MODEL")
        or os.environ.get("XYN_DEFAULT_MODEL_NAME")
        or PROVIDER_MODEL_DEFAULTS.get(provider_slug or "openai", "gpt-5-mini")
    ).strip()
    key_present = bool(_read_provider_env_key(provider_slug)) if provider_slug in PROVIDER_ENV_API_KEY else False
    agent = AgentDefinition.objects.select_related("model_config__provider").filter(slug="default-assistant").first()
    planning_agent = AgentDefinition.objects.select_related("model_config__provider").filter(slug="planning-assistant").first()
    coding_agent = AgentDefinition.objects.select_related("model_config__provider").filter(slug="coding-assistant").first()
    return {
        "provider": provider_label or "none",
        "model": model_name if provider_label else "none",
        "key_present": key_present,
        "default_agent_id": str(agent.id) if agent else None,
        "default_agent_slug": agent.slug if agent else None,
        "default_agent_updated_at": agent.updated_at if agent else None,
        "planning_agent_id": str(planning_agent.id) if planning_agent else None,
        "planning_agent_slug": planning_agent.slug if planning_agent else None,
        "coding_agent_id": str(coding_agent.id) if coding_agent else None,
        "coding_agent_slug": coding_agent.slug if coding_agent else None,
    }
