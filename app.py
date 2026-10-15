import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

import engine
import llm

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("sharpen")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app = Flask(__name__, static_folder=None)          # only STATIC_DIR is ever served, explicitly
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
if os.getenv("TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)


def demo_mode():
    return os.getenv("DEMO_MODE") == "1"


# ------------------------------------------------------------ rate limit + cache
_hits, _hits_lock = defaultdict(deque), threading.Lock()
_cache, _cache_lock = OrderedDict(), threading.Lock()
CACHE_MAX = 200


def over_limit(ip, weight=1):
    limit = int(os.getenv("RATE_LIMIT_PER_MIN", "12"))
    now = time.monotonic()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + weight > limit:
            return True
        q.extend([now] * weight)
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60]:
                del _hits[k]
        return False


def cache_get(key):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]


def cache_put(key, value):
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def fail(message, status):
    return jsonify(error=message), status


def guard(weight=1):
    """Common pre-flight checks. Returns (body, error_response)."""
    if not demo_mode() and not llm.configured():
        return None, fail("Server is not configured: set GROQ_API_KEY or XAI_API_KEY (see .env.example).", 503)
    if over_limit(request.remote_addr or "unknown", weight):
        return None, fail("Too many requests. Wait a minute and try again.", 429)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, fail("Request body must be JSON.", 400)
    return body, None


def text_field(body, name, limit):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        return None, fail(f"'{name}' is required.", 400)
    v = v.strip()
    if len(v) > limit:
        return None, fail(f"'{name}' is too long (max {limit} characters).", 400)
    return v, None


def choice(body, name, allowed, default):
    v = body.get(name, default)
    return v if v in allowed else None


# ------------------------------------------------------------ routes
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:filename>")
def assets(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.get("/api/status")
def status():
    cfg = llm.settings()
    return jsonify(ok=True, demo=demo_mode(), configured=demo_mode() or llm.configured(),
                   provider=cfg["label"], model=llm.active_model())


@app.post("/api/sharpen")
def sharpen():
    body, err = guard()
    if err:
        return err
    prompt, err = text_field(body, "prompt", engine.MAX_PROMPT)
    if err:
        return err
    mode, target = choice(body, "mode", engine.MODES, "general"), choice(body, "target", engine.TARGETS, "any")
    if mode is None or target is None:
        return fail("Unknown mode or target.", 400)

    if demo_mode():
        return jsonify({**engine.demo_sharpen(prompt, mode, target), "demo": True})

    key = hashlib.sha256(f"{mode}|{target}|{prompt}".encode()).hexdigest()
    if (hit := cache_get(key)):
        return jsonify(hit)
    messages = engine.sharpen_messages(prompt, mode, target)
    try:
        for _ in range(2):  # one retry when the model returns malformed JSON
            try:
                result = engine.normalize_sharpen(engine.extract_json(llm.chat(messages, 2400, 0.4, json_mode=True)))
                cache_put(key, result)
                return jsonify(result)
            except ValueError as exc:
                log.warning("unusable model output: %s", exc)
        return fail("The model gave an unusable answer. Try again.", 502)
    except llm.LLMError as exc:
        return fail(str(exc), exc.status)


@app.post("/api/refine")
def refine():
    body, err = guard()
    if err:
        return err
    text, err = text_field(body, "text", engine.MAX_TEXT)
    if err:
        return err
    instruction = choice(body, "instruction", engine.REFINEMENTS, None)
    mode, target = choice(body, "mode", engine.MODES, "general"), choice(body, "target", engine.TARGETS, "any")
    if instruction is None or mode is None or target is None:
        return fail("Unknown instruction, mode or target.", 400)

    if demo_mode():
        label = engine.REFINEMENTS[instruction][0].lower()
        return jsonify(text=f"{text}\n\n(Demo: '{label}' refinement would be applied here.)", demo=True)
    try:
        raw = llm.chat(engine.refine_messages(text, instruction, mode, target), 2400, 0.5)
        return jsonify(text=engine.clean_text(raw))
    except ValueError:
        return fail("The model gave an unusable answer. Try again.", 502)
    except llm.LLMError as exc:
        return fail(str(exc), exc.status)


@app.post("/api/compare")
def compare():
    """Run the original and the sharpened prompt, so the person can judge the difference."""
    body, err = guard(weight=2)
    if err:
        return err
    original, err = text_field(body, "original", engine.MAX_PROMPT)
    if err:
        return err
    sharpened, err = text_field(body, "sharpened", engine.MAX_TEXT)
    if err:
        return err

    if demo_mode():
        return jsonify(original="(Demo) A short, generic answer.",
                       sharpened="(Demo) A structured answer that follows your role, format and constraints.", demo=True)

    def run(prompt):
        return llm.chat([{"role": "system", "content": "You are a helpful assistant."},
                         {"role": "user", "content": prompt}], 700, 0.7).strip()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(run, original), pool.submit(run, sharpened)
            return jsonify(original=a.result(), sharpened=b.result())
    except llm.LLMError as exc:
        return fail(str(exc), exc.status)


@app.errorhandler(404)
def not_found(_):
    return fail("Not found.", 404)


@app.errorhandler(413)
def too_large(_):
    return fail("Request too large.", 413)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    app.run(host=host, port=int(os.getenv("PORT", 8000)))
