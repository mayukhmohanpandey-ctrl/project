# Sharpen

Paste a rough prompt. Sharpen rewrites it, marks every change as a blue-pencil redline, and scores it against eight checks.

Inspired by the open-source [Prompt Forge](https://github.com/Divyansh0208/Prompt_Forge), rebuilt from scratch with a different interface and a stronger feature set.

## What it does

- **Redline view**: a word-level diff of your original against the rewrite. Additions are underlined, removals struck through.
- **Review notes**: eight checks (clarity, context, constraints, output format, role, examples, reasoning, guardrails), each scored 0 to 3 before and after, plus a list of what the rough prompt lacked.
- **Fill in the blanks**: missing details come back as `[PLACEHOLDERS]`. Fill them in a form and the prompt updates live.
- **Adjust**: shorter, more detailed, more formal, friendlier, add examples, simpler. Every adjustment is a new version you can switch back to.
- **Compare answers**: runs your original and the sharpened prompt through the model so you can read both answers.
- **Optimise for**: Any assistant, ChatGPT, Claude (XML tags), Gemini, or a small local model. **Task** modes: general, writing, coding, analysis, image generation.
- **Share link**: the whole result is encoded in the URL fragment, so there is no database and nothing is stored server-side.
- **Recent**: the last 12 prompts, kept in your browser only.
- Light and dark themes, keyboard-navigable tabs, reduced-motion support.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add GROQ_API_KEY or XAI_API_KEY
python app.py                                          # http://localhost:8000
```

No key yet? `DEMO_MODE=1 python app.py` runs the full interface with canned responses.

### Providers

Set **one** key and Sharpen picks the provider automatically.

| Provider | Key | Default model |
|---|---|---|
| **Groq** | `GROQ_API_KEY` | `openai/gpt-oss-120b` (falls back to `openai/gpt-oss-20b`) |
| **xAI Grok** | `XAI_API_KEY` | `grok-4.7` (falls back to `grok-4.3`) |
| NVIDIA NIM | `NVIDIA_API_KEY` | `meta/llama-3.1-70b-instruct` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| Ollama (local, no key) | `LLM_PROVIDER=ollama` | `llama3.1` |
| Anything OpenAI-compatible | `LLM_PROVIDER=custom` + `LLM_BASE_URL` + `LLM_MODEL` | none |

Notes:

- Several keys set? Choose with `LLM_PROVIDER`.
- Override the model with `LLM_MODEL`, and add backups with `LLM_FALLBACK_MODELS`. If a model has been retired (Groq retired Llama 3.3 70B on 2026-08-16), Sharpen moves to the next model automatically and logs a warning.
- Groq's gpt-oss models are reasoning models. Sharpen sends `reasoning_effort: low` and adds token headroom for the thinking. Tune with `LLM_REASONING_EFFORT`.
- JSON mode (`response_format`) is used where the provider supports it, which makes rewrites far less likely to come back malformed.
- Model lineups change often. Check [Groq models](https://console.groq.com/docs/models) and [xAI models](https://docs.x.ai/developers/models) for current ids.

### Deploy

`Procfile` (Render, Heroku) and `Dockerfile` are included. Set `GROQ_API_KEY` (or `XAI_API_KEY`) and `TRUST_PROXY=1`.

```bash
docker build -t sharpen . && docker run -p 8000:8000 -e GROQ_API_KEY=... sharpen
```

## API

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/sharpen` | `{prompt, mode?, target?}` | `{title, sharpened, score:{before,after}, rubric, gaps, changes}` |
| `POST /api/refine` | `{text, instruction, mode?, target?}` | `{text}` |
| `POST /api/compare` | `{original, sharpened}` | `{original, sharpened}` (the two model answers) |
| `GET /api/status` | | `{ok, demo, configured, model}` |

Errors are `{error: "..."}` with 400 (bad input), 429 (rate limit or provider busy), 502/504 (provider problem) or 503 (not configured).

## Security and cost controls

- The browser never sees the API key, and cannot choose the model, token limits or system prompt.
- Only `static/` is served. User text is delimited and treated as data (prompt-injection mitigation). All model text is rendered with `textContent`.
- Strict CSP (no inline script or style), per-IP rate limiting, request-size cap, identical sharpen requests served from an in-memory cache.
- The rate limiter and cache are per process. Use Redis if you scale to many workers.

## Layout

```
app.py       Flask routes, validation, rate limit, cache
engine.py    Prompts, JSON extraction, validation, scoring, demo engine (pure, tested)
llm.py       Provider presets (Groq, xAI, ...), model fallback, OpenAI-compatible client
static/      index.html, style.css, app.js (no framework, no build step)
tests/       python -m unittest discover -s tests
```
