# Sharpen

**Turn a rough prompt into a precise one, and see exactly what changed.**

Paste a prompt like *"Write an email about the meeting"*. Sharpen rewrites it, marks every edit as a blue-pencil redline, and scores both versions against eight checks, so you learn what makes a prompt work instead of just copying a result.

![Redline view: additions underlined in blue, removals struck through, review notes in the margin](docs/redline.png)

Works with **Groq** and **xAI Grok** out of the box, plus NVIDIA NIM, OpenAI, Ollama and any OpenAI-compatible endpoint. No framework, no build step, no database.

> Inspired by the open-source [Prompt Forge](https://github.com/Divyansh0208/Prompt_Forge). Rebuilt from scratch with a different interface, backend and feature set.

**Contents:** [Quick start](#quick-start) · [Features](#features) · [Choose a model provider](#choose-a-model-provider) · [Configuration](#configuration) · [How scoring works](#how-scoring-works) · [Deploy](#deploy) · [API](#api) · [Security and privacy](#security-and-privacy) · [Troubleshooting](#troubleshooting) · [Development](#development) · [License](#license)

---

## Quick start

Requires Python 3.10 or newer.

```bash
git clone <your-repo-url> sharpen && cd sharpen
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Try the interface first, no key needed:**

```bash
DEMO_MODE=1 python app.py          # Windows (PowerShell): $env:DEMO_MODE=1; python app.py
```

Open <http://localhost:8000>. Demo mode returns canned results, so you can explore every screen.

**Then connect a real model:**

```bash
cp .env.example .env               # then add GROQ_API_KEY or XAI_API_KEY
python app.py
```

Get a key from [console.groq.com/keys](https://console.groq.com/keys) or [console.x.ai](https://console.x.ai).

---

## Features

![The sharpened prompt with fill-in-the-blank fields and adjustment chips](docs/prompt.png)

| Feature | What it does |
|---|---|
| **Redline** | Word-level diff of your original against the rewrite. Additions are underlined, removals struck through. Your own words stay plain. |
| **Review notes** | Eight checks scored 0 to 3 before and after, plus a list of what your prompt lacked and what changed. |
| **Fill in the blanks** | Missing details come back as `[PLACEHOLDERS]`. Fill them in a form and the prompt updates live. Copy and download use your filled values. |
| **Adjust** | Shorter, more detailed, more formal, friendlier, add examples, simpler. Each adjustment is a new version you can switch back to. |
| **Compare answers** | Runs your original and the sharpened prompt through the model so you can read both answers side by side. |
| **Task and target** | Task: general, writing, coding, analysis, image generation. Optimise for: any assistant, ChatGPT, Claude (XML tags), Gemini, or a small local model. |
| **Share link** | The whole result is encoded in the URL fragment. Nothing is stored on the server. |
| **Recent** | Your last 12 prompts, stored in your browser only. |
| **Accessibility** | Light and dark themes, keyboard-navigable tabs, visible focus, reduced-motion support. |

---

## Choose a model provider

Set **one** key and Sharpen detects the provider.

| Provider | Key | Default model | Backup |
|---|---|---|---|
| **Groq** | `GROQ_API_KEY` | `openai/gpt-oss-120b` | `openai/gpt-oss-20b` |
| **xAI Grok** | `XAI_API_KEY` (or `GROK_API_KEY`) | `grok-4.7` | `grok-4.3` |
| NVIDIA NIM | `NVIDIA_API_KEY` | `meta/llama-3.1-70b-instruct` | none |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1-mini` | none |
| Ollama (local, no key) | `LLM_PROVIDER=ollama` | `llama3.1` | none |
| Any OpenAI-compatible API | `LLM_PROVIDER=custom`, `LLM_BASE_URL`, `LLM_MODEL` | none | none |

How the provider layer behaves:

- **Several keys set?** Pick with `LLM_PROVIDER`.
- **Models get retired.** If a model returns "does not exist", Sharpen moves to the next one in the list and logs a warning. Groq retired Llama 3.3 70B on 2026-08-16, so older tutorials that use it will fail. Set your own list with `LLM_MODEL` and `LLM_FALLBACK_MODELS`.
- **Reasoning models** (Groq's gpt-oss, Grok 4.x) spend part of their token budget thinking. Sharpen adds headroom for that and sends `reasoning_effort: low` to gpt-oss.
- **JSON mode** (`response_format`) is used where the provider supports it, and dropped automatically if a model rejects it.
- **Model lists change often.** Check [Groq models](https://console.groq.com/docs/models) and [xAI models](https://docs.x.ai/developers/models) for current ids.

---

## Configuration

All settings are environment variables. Put them in `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY`, `XAI_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_API_KEY` | none | Provider key. The first one found selects the provider. |
| `LLM_PROVIDER` | auto | Force `groq`, `xai`, `nvidia`, `openai`, `ollama` or `custom`. |
| `LLM_MODEL` | provider default | Override the model id. |
| `LLM_FALLBACK_MODELS` | none | Comma-separated models to try if one no longer exists. |
| `LLM_BASE_URL` | provider default | Custom OpenAI-compatible endpoint. |
| `LLM_REASONING_EFFORT` | `low` | Groq gpt-oss only: `low`, `medium` or `high`. |
| `LLM_TIMEOUT` | `90` | Seconds to wait for the provider. |
| `RATE_LIMIT_PER_MIN` | `12` | Requests per client IP per minute. "Compare answers" counts as 2. |
| `TRUST_PROXY` | off | Set `1` behind Render, Heroku or nginx so rate limiting sees real client IPs. |
| `DEMO_MODE` | off | Set `1` for canned responses with no key. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Bind address and port. When `PORT` is set by a host, the address defaults to `0.0.0.0`. |

Limits: prompts up to 4,000 characters, refine and compare inputs up to 12,000.

---

## How scoring works

Each prompt is scored on eight checks, 0 to 3 each:

| Check | Asks |
|---|---|
| Clarity | Is there one clear task? |
| Context | Does it say who it is for and why? |
| Constraints | Are length, tone, scope and limits stated? |
| Output format | Is the shape of the answer specified? |
| Role | Does it tell the model who to be? |
| Examples | Does it show what good looks like? |
| Reasoning | Does it guide step-by-step thinking? |
| Guardrails | Does it say what to avoid or never invent? |

`0` absent, `1` implied or weak, `2` present, `3` precise and complete. The score out of 100 is the total divided by 24.

The model grades both versions, so treat the number as a **guide to compare drafts**, not a measurement. The per-check breakdown and the "what it lacked" list are the useful part. For an independent check, use **Compare answers** and judge the outputs yourself.

---

## Deploy

**Render, Heroku and similar:** the included `Procfile` runs gunicorn. Set your provider key and `TRUST_PROXY=1` in the platform's environment settings.

**Docker:**

```bash
docker build -t sharpen .
docker run -p 8000:8000 -e GROQ_API_KEY=your-key sharpen
```

**Scaling note:** the rate limiter and the response cache live in memory, per process. With two gunicorn workers each keeps its own counters, so the effective limit is roughly double. Move both to Redis if you run many workers or need strict limits.

---

## API

All endpoints return JSON. Errors look like `{"error": "message"}`.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/sharpen` | `{prompt, mode?, target?}` | `{title, sharpened, score:{before,after}, rubric, gaps, changes}` |
| `POST /api/refine` | `{text, instruction, mode?, target?}` | `{text}` |
| `POST /api/compare` | `{original, sharpened}` | `{original, sharpened}`: the two model answers |
| `GET /api/status` | none | `{ok, demo, configured, provider, model}` |

- `mode`: `general` (default), `writing`, `coding`, `analysis`, `image`.
- `target`: `any` (default), `chatgpt`, `claude`, `gemini`, `local`.
- `instruction`: `shorter`, `detailed`, `formal`, `friendly`, `examples`, `simpler`.
- Status codes: `400` bad input, `429` rate limited or provider busy, `502`/`504` provider problem, `503` not configured.

```bash
curl -s localhost:8000/api/sharpen -H 'Content-Type: application/json' \
  -d '{"prompt":"Explain machine learning","mode":"general"}'
```

---

## Security and privacy

- **Your prompts leave your machine.** They are sent to whichever provider you configure. Read that provider's data policy before pasting anything sensitive.
- **Recent prompts** are stored in your browser's localStorage. Clear them from the Recent dialog. **Share links** carry the full result in the URL, so anyone with the link can read it.
- The browser never sees the API key and cannot choose the model, token limits or system prompt.
- Only `static/` is served, so `.env` and the Python source are not reachable over HTTP.
- Your text is delimited and treated as data in the model prompt, which reduces (but cannot eliminate) prompt injection. Everything the model returns is rendered as plain text, never HTML.
- Strict Content Security Policy (no inline script or style), per-IP rate limiting, a 64 KB request cap, and an in-memory cache for repeated requests.
- Share links can be long (often 2 to 6 KB). Some chat apps truncate very long URLs.

---

## Troubleshooting

| You see | Cause and fix |
|---|---|
| "The server has no model API key yet" | No provider key is set. Add `GROQ_API_KEY` or `XAI_API_KEY` to `.env`, or use `DEMO_MODE=1`. |
| "The model provider rejected the request" | Wrong key, no credits (xAI needs credits on the account), or no access to that model. |
| "None of the configured models exist on Groq" | Your `LLM_MODEL` and the backups were all retired. Set `LLM_MODEL` to a current id from the provider's model list. |
| "The model provider is rate limiting requests" | The provider's own limit. Wait the number of seconds shown, or use a higher tier. |
| "Too many requests. Wait a minute" | Sharpen's per-IP limit. Raise `RATE_LIMIT_PER_MIN`. |
| "The model gave an unusable answer" | The model returned malformed JSON twice. Try again, or switch to a model that follows JSON instructions well. |
| Every request fails behind a proxy with 429 | Set `TRUST_PROXY=1` so clients are not all seen as one IP. |

---

## Development

```
app.py       Flask routes, validation, rate limiting, cache
engine.py    Prompts, JSON extraction, validation, scoring, demo engine (pure functions)
llm.py       Provider presets, model fallback, OpenAI-compatible client
static/      index.html, style.css, app.js (no framework, no build step)
tests/       Unit and API tests (standard library only)
docs/        README screenshots
```

```bash
python -m unittest discover -s tests -v
```

The suite covers parsing and scoring, request validation, rate limiting, caching, each provider's request shape, retired-model fallback, and a check that project files are never served. CI runs it on every push (`.github/workflows/ci.yml`).

**Ideas for contributors:** streaming output, a template library, Redis-backed limits, an evaluation mode that scores prompts against test cases.

---

## License

MIT. See [LICENSE](LICENSE).
