# LLM Provider Extension — Ollama / OpenAI-compat / Anthropic-compat

## Goal

Extend the install wizard so users can pick their LLM backend at setup time,
instead of being hard-wired to Ollama. Three options:

1. **Ollama** (local, default — unchanged)
2. **Custom API — OpenAI-compatible** (e.g. OpenAI, OpenRouter, Together, Groq, any service that exposes `/v1/chat/completions`)
3. **Custom API — Anthropic-compatible** (e.g. Anthropic direct, MiniMax, any service that exposes `/v1/messages` with `x-api-key` + `anthropic-version` headers)

The user enters the base URL, the model ID, and the API key in the wizard.
Everything else is wired automatically.

## Decisions

- **`LLM_PROVIDER` becomes an explicit choice** in `.env` (`ollama` | `openai_compat` | `anthropic_compat`). The current URL-heuristic dispatch in `score.py` is removed.
- **Prompts stay as user-messages.** No system/user split — the existing `abstract_score.txt` and `deep_score.txt` are sent wholesale as a single user-message to all three providers. This keeps the prompts portable and avoids an invasive rewrite. (The user explicitly chose option "alle als user-message" over "prompt aufteilen" when brainstorming this feature.)
- **`anthropic-version` header is hardcoded** to `2023-06-01`. No env var, no wizard prompt. It's been stable since mid-2023 and every Anthropic-compatible API accepts it. If a future API requires a different version, this is a one-line code change.
- **The Anthropic path is generic.** It's not tied to `api.anthropic.com`. Users can paste any Anthropic-format base URL (e.g. a proxy URL, a local MiniMax-compatible endpoint).

## Files to change

### `src/research_pipeline/config.py`

Add `anthropic_version` as a hardcoded constant (no env var):

```python
ANTHROPIC_VERSION = "2023-06-01"
```

Remove `LLM_PROVIDER`'s implicit default logic — make it required-but-defaulted
to `ollama`. The dataclass stays the same shape (we just change what the wizard writes):

```python
@dataclass(frozen=True)
class Config:
    llm_provider: str          # "ollama" | "openai_compat" | "anthropic_compat"
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    # (no anthropic_version field — hardcoded in score.py)
    # ... rest unchanged ...
```

`load_config()` adds a `_env` lookup for `LLM_PROVIDER` with default `"ollama"`.

### `src/research_pipeline/score.py`

Replace the URL-heuristic dispatch with explicit provider branching:

```python
def _chat_ollama(messages, *, model, base_url, ...) -> str:
    # unchanged — POST {base_url}/api/chat, Ollama schema
    ...

def _chat_openai_compat(messages, *, model, base_url, api_key, ...) -> str:
    # unchanged — POST {base_url}/chat/completions, OpenAI schema
    ...

def _chat_anthropic_compat(
    messages,
    *,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> str:
    """Call an Anthropic-format /v1/messages endpoint.

    Compatible with Anthropic direct, MiniMax, and any provider that follows
    the Anthropic Messages API schema.
    """
    from research_pipeline.config import ANTHROPIC_VERSION  # avoid circular at import

    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # Response shape: {"content": [{"type": "text", "text": "..."}, ...]}
        content_blocks = data.get("content") or []
        text_parts = [block["text"] for block in content_blocks if block.get("type") == "text"]
        return "".join(text_parts)


def _chat(messages, *, model, base_url, api_key, provider, ...):
    """Dispatch to the configured provider. Returns the assistant message content."""
    if provider == "ollama":
        return _chat_ollama(messages, model=model, base_url=base_url, ...)
    if provider == "openai_compat":
        return _chat_openai_compat(messages, model=model, base_url=base_url, api_key=api_key, ...)
    if provider == "anthropic_compat":
        return _chat_anthropic_compat(messages, model=model, base_url=base_url, api_key=api_key, ...)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")
```

`score_abstract` and `score_deep` pass `provider=cfg.llm_provider` into `_chat`.

### `src/research_pipeline/install/wizard.py`

Step [2] becomes a 3-option menu. Old Step [2] (Ollama model pull) becomes
part of the Ollama branch. Step [3] onwards renumbers (Telegram becomes [4],
features [5], schedule [6], .env [7], cron [8]).

```
[2/8] LLM Provider
  1) Ollama (local, recommended for first install)
  2) Custom API — OpenAI-compatible
  3) Custom API — Anthropic-compatible
Choice [1]: 1
```

Ollama branch (unchanged behavior):
```
[3/8] Ollama model
  Default: phi3.5:3.8b
  Model [phi3.5:3.8b]:
  Pull now? [Y/n]: Y
  ✓ Model pulled
```

OpenAI branch:
```
[3/8] OpenAI-compatible API
  Base URL (e.g. https://api.openai.com/v1): https://api.openai.com/v1
  Model ID (e.g. gpt-4o-mini): gpt-4o-mini
  API key: sk-***
  Validating with test call... ✓
```

Anthropic branch:
```
[3/8] Anthropic-compatible API
  Base URL [https://api.anthropic.com]: https://api.anthropic.com
  Model ID (e.g. claude-3-5-sonnet-20241022): claude-3-5-sonnet-20241022
  API key: sk-ant-***
  Validating with test call... ✓
```

Validation: a tiny test call (`_chat` with `max_tokens=10`, prompt "Reply with OK")
and check the response is non-empty. Reject and re-prompt on failure.

`install/wizard.py:install()` writes these into `.env`:

```
LLM_PROVIDER=anthropic_compat
LLM_BASE_URL=https://api.anthropic.com
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_API_KEY=sk-ant-...
```

(The install wizard still writes all the other unrelated keys; only the
LLM-related set changes.)

### `.env.example`

Replace the LLM section:

```bash
# === LLM ===
# Provider: ollama (local, default) | openai_compat | anthropic_compat
LLM_PROVIDER=ollama
# Model name. Examples:
#   Ollama: phi3.5:3.8b, qwen2.5:7b, llama3.2:3b
#   OpenAI-compat: gpt-4o-mini, anthropic/claude-3.5-sonnet (via OpenRouter)
#   Anthropic-compat: claude-3-5-sonnet-20241022, claude-3-haiku-20240307
LLM_MODEL=phi3.5:3.8b
# Base URL:
#   Ollama default: http://localhost:11434
#   OpenAI: https://api.openai.com/v1  (or OpenRouter, Together, Groq, etc.)
#   Anthropic: https://api.anthropic.com  (or any Anthropic-format API)
LLM_BASE_URL=http://localhost:11434
# API key — required for openai_compat and anthropic_compat, ignored for ollama
LLM_API_KEY=
```

### `tests/test_score.py`

Add coverage for `_chat_anthropic_compat` and the new dispatch:

- Mock `httpx.Client.post`. Verify URL is `{base_url}/v1/messages`, headers include `x-api-key` and `anthropic-version`, body includes `model`, `messages`, `max_tokens`, `temperature`.
- Verify response extraction: `data["content"][0]["text"]` for single block, joined text for multi-block.
- Verify `_chat` dispatches correctly for each `provider` value.
- Verify `_chat` raises `ValueError` for unknown provider.
- Verify that for `anthropic_compat`, the existing prompts (`abstract_score.txt`, `deep_score.txt`) are passed as-is (single user-message).

### `tests/test_install.py`

Add wizard tests:
- Mock `click.prompt` and `click.confirm`. Walk the wizard with provider=1 (Ollama) and assert `.env` written with `LLM_PROVIDER=ollama`.
- Same for provider=2 (OpenAI). Assert URL, model, key passed through.
- Same for provider=3 (Anthropic). Same asserts.
- Test `--yes` flag: provider defaults to 1 if no existing `LLM_PROVIDER` in `.env`.

### Docs

- **`README.md`**: add a "LLM Provider" section after the Quickstart with three short config examples (Ollama, OpenAI, Anthropic).
- **`docs/INSTALL.md`**: extend the "Switching LLM provider" section to cover all three. Add "Using MiniMax or another Anthropic-format proxy" subsection noting that `LLM_PROVIDER=anthropic_compat` with a custom `LLM_BASE_URL` works for any provider that speaks the Messages API.
- **`docs/ARCHITECTURE.md`**: update the score module row in the module map to mention three provider branches.

## Verification

```bash
cd /root/pipeline-public
.venv/bin/ruff check src/ tests/        # clean
.venv/bin/ruff format --check src/ tests/  # clean
.venv/bin/pytest -v --tb=short           # all existing 145 + ~12 new tests pass

# Manual smoke: spin up wizard in --yes mode after backing up .env
cp .env .env.bak
.venv/bin/research-pipeline-install install --yes
grep LLM_ .env
diff .env .env.bak                       # only LLM_* keys should differ
```

## Out of scope

- `system` prompt field for Anthropic. The user explicitly chose to keep
  prompts as single user-messages.
- Configurable `anthropic-version` header. Hardcoded to `2023-06-01`.
- Other Anthropic-specific features (tool use, vision, prompt caching).
  Just the Messages text completion endpoint.
- Migration of existing users. Users with `LLM_PROVIDER=ollama` in `.env`
  keep working unchanged. Users with the old `LLM_BASE_URL` heuristic also
  work because we add `LLM_PROVIDER` with a default of `ollama` and the
  new dispatch falls back to URL heuristics if `LLM_PROVIDER` is unset.
