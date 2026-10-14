"""LLM client with first-class presets for Groq and xAI (Grok), plus NVIDIA, OpenAI, Ollama and custom endpoints.

Every preset speaks the OpenAI chat-completions wire format. Presets differ in base URL, default model,
the name of the token-limit field, and whether JSON mode / reasoning effort apply.

Provider selection (first match wins):
  1. LLM_PROVIDER=groq|xai|nvidia|openai|ollama|custom
  2. whichever of GROQ_API_KEY, XAI_API_KEY (or GROK_API_KEY), NVIDIA_API_KEY, OPENAI_API_KEY is set
  3. LLM_BASE_URL set -> custom
  4. groq
"""
import logging
import os

import requests

log = logging.getLogger("sharpen.llm")

PROVIDERS = {
    "groq": {
        "label": "Groq",
        "base": "https://api.groq.com/openai/v1",
        # llama-3.3-70b-versatile was retired on 2026-08-16; the gpt-oss models are Groq's production text models.
        "models": ("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
        "keys": ("GROQ_API_KEY",),
        "token_param": "max_completion_tokens",
        "json_mode": True,
    },
    "xai": {
        "label": "xAI Grok",
        "base": "https://api.x.ai/v1",
        "models": ("grok-4.7", "grok-4.3"),
        "keys": ("XAI_API_KEY", "GROK_API_KEY"),
        "token_param": "max_completion_tokens",
        "json_mode": True,
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base": "https://integrate.api.nvidia.com/v1",
        "models": ("meta/llama-3.1-70b-instruct",),
        "keys": ("NVIDIA_API_KEY",),
        "token_param": "max_tokens",
        "json_mode": False,
    },
    "openai": {
        "label": "OpenAI",
        "base": "https://api.openai.com/v1",
        "models": ("gpt-4.1-mini",),
        "keys": ("OPENAI_API_KEY",),
        "token_param": "max_completion_tokens",
        "json_mode": True,
    },
    "ollama": {
        "label": "Ollama (local)",
        "base": "http://localhost:11434/v1",
        "models": ("llama3.1",),
        "keys": (),
        "token_param": "max_tokens",
        "json_mode": False,
    },
    "custom": {
        "label": "Custom endpoint",
        "base": "",
        "models": (),
        "keys": (),
        "token_param": "max_tokens",
        "json_mode": False,
    },
}
AUTODETECT = ("groq", "xai", "nvidia", "openai")


_last_ok = {"model": None}   # model that most recently answered (shown in the UI)


class LLMError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _env(*names):
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def provider_name():
    explicit = _env("LLM_PROVIDER").lower()
    if explicit in PROVIDERS:
        return explicit
    if explicit:
        log.warning("unknown LLM_PROVIDER %r; falling back to auto-detection", explicit)
    for name in AUTODETECT:
        if _env(*PROVIDERS[name]["keys"]):
            return name
    return "custom" if _env("LLM_BASE_URL") else "groq"


def settings():
    name = provider_name()
    p = PROVIDERS[name]
    chain = []
    if _env("LLM_MODEL"):
        chain.append(_env("LLM_MODEL"))
    chain += [m.strip() for m in _env("LLM_FALLBACK_MODELS").split(",") if m.strip()]
    # preset models are the last resort, so a retired LLM_MODEL in an old .env doesn't take the app down
    chain += [m for m in p["models"] if m not in chain]
    return {
        "provider": name,
        "label": p["label"],
        "key": _env("LLM_API_KEY", *p["keys"]),
        "base": (_env("LLM_BASE_URL") or p["base"]).rstrip("/"),
        "models": chain,
        "token_param": p["token_param"],
        "json_mode": p["json_mode"],
    }


def configured():
    s = settings()
    if not s["base"] or not s["models"]:
        return False
    return bool(s["key"]) or s["provider"] in ("ollama", "custom")


def _is_reasoning(model):
    return model.startswith("openai/gpt-oss") or model.startswith(("grok-4", "o1", "o3", "o4", "gpt-5"))


def _error_text(resp):
    try:
        err = resp.json().get("error", {})
        return (err.get("message", "") if isinstance(err, dict) else str(err)).lower()
    except (ValueError, AttributeError):
        return ""


def _model_is_gone(resp):
    text = _error_text(resp)
    return resp.status_code in (400, 404) and "model" in text and any(
        w in text for w in ("not exist", "not found", "decommission", "deprecat", "no access", "unknown model"))


def chat(messages, max_tokens=2048, temperature=0.5, json_mode=False):
    """Return the assistant text. Falls through the model chain when a model has been retired."""
    s = settings()
    headers = {"Content-Type": "application/json"}
    if s["key"]:
        headers["Authorization"] = f"Bearer {s['key']}"
    timeout = int(os.getenv("LLM_TIMEOUT", "90"))

    last_gone = False
    for model in s["models"]:
        reasoning = _is_reasoning(model)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            # reasoning models spend part of the budget thinking, so give them headroom
            s["token_param"]: max_tokens + (2500 if reasoning else 0),
        }
        if json_mode and s["json_mode"]:
            payload["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = os.getenv("LLM_REASONING_EFFORT", "low")

        resp = _post(s["base"], headers, payload, timeout)
        # some models reject response_format: retry once without it
        if resp.status_code == 400 and "response_format" in payload and "response_format" in _error_text(resp):
            payload.pop("response_format")
            resp = _post(s["base"], headers, payload, timeout)

        log.info("provider=%s model=%s status=%s", s["provider"], model, resp.status_code)  # never log bodies/keys
        if _model_is_gone(resp):
            log.warning("model %s is unavailable on %s; trying the next one", model, s["provider"])
            last_gone = True
            continue
        text = _read(resp)
        _last_ok["model"] = model
        return text

    if last_gone:
        raise LLMError(f"None of the configured models exist on {s['label']}. Set LLM_MODEL to a current model id.", 502)
    raise LLMError("No model is configured. Set LLM_MODEL.", 503)


def _post(base, headers, payload, timeout):
    try:
        return requests.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        raise LLMError("The model took too long to answer. Try again.", 504)
    except requests.exceptions.RequestException as exc:
        log.error("provider unreachable: %s", exc)
        raise LLMError("Could not reach the model provider.", 502)


def _read(resp):
    if resp.status_code == 429:
        wait = resp.headers.get("retry-after", "")
        hint = f" Try again in about {int(float(wait))} seconds." if wait.replace(".", "", 1).isdigit() else " Try again in a moment."
        raise LLMError("The model provider is rate limiting requests." + hint, 429)
    if resp.status_code in (401, 403):
        log.error("provider rejected the request (status %s)", resp.status_code)
        raise LLMError("The model provider rejected the request. Check the API key, its credits and model access.", 502)
    if not resp.ok:
        raise LLMError("The model provider returned an error. Try again.", 502)
    try:
        return resp.json()["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise LLMError("The model provider sent an unreadable response.", 502)


def active_model():
    s = settings()
    last = _last_ok["model"]
    return last if last in s["models"] else (s["models"][0] if s["models"] else None)
