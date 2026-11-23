"""24/7 Drama Bots: local server.

Stdlib only. Your AI key stays in .env on this computer and is never sent to the browser.
Only pages served from this computer (localhost) can use the API.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import drama_prompts as DP
import media as M

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PROJECTS = ROOT / "projects"
TRASH = PROJECTS / ".trash"
ENV = ROOT / ".env"
UA = "drama-bots/1.0"  # Groq sits behind Cloudflare, which blocks the default Python-urllib agent
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "openai": ("https://api.openai.com/v1", ""),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-oss-120b"),
}


def load_env():
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
PORT = int(os.environ.get("PORT", "4247"))
MOCK = os.environ.get("DRAMA_MOCK", "") == "1"


# One saved key per provider, so switching provider never sends a key to the wrong company.
KEYVARS = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "custom": "CUSTOM_API_KEY"}


def conf():
    base = (os.environ.get("AI_BASE_URL") or PRESETS["groq"][0]).rstrip("/")
    key = os.environ.get(KEYVARS[provider_of(base)], "")
    model = os.environ.get("AI_MODEL") or os.environ.get("GROQ_CHAT_MODEL") or PRESETS["groq"][1]
    return key, base, model


def saved_keys():
    return {p: bool(os.environ.get(v)) for p, v in KEYVARS.items()}


def migrate_legacy_key():
    """Older versions saved every key as AI_API_KEY: move it to the provider it belongs to."""
    legacy = os.environ.get("AI_API_KEY", "")
    if legacy:
        var = KEYVARS[provider_of(os.environ.get("AI_BASE_URL") or PRESETS["groq"][0])]
        upd = {"AI_API_KEY": ""}
        if not os.environ.get(var):
            upd[var] = legacy
        set_env(upd)


def provider_of(base):
    host = (urlsplit(base).hostname or "").lower()
    if host.endswith("groq.com"):
        return "groq"
    if host.endswith("openai.com"):
        return "openai"
    if host.endswith("openrouter.ai"):
        return "openrouter"
    return "custom"


def set_env(updates):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.strip().startswith("#") else None
        if k in updates:
            out.append("%s=%s" % (k, updates[k]))
            seen.add(k)
        else:
            out.append(ln)
    for k, v in updates.items():
        if k not in seen:
            out.append("%s=%s" % (k, v))
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass
    for k, v in updates.items():
        os.environ[k] = v


# ------------------------------------------------------------------------------------------
# AI calls
# ------------------------------------------------------------------------------------------
class AIError(Exception):
    def __init__(self, msg, code=502, retry_after=0):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after


_hits = []
LEARNED = {}  # (base, model) -> parameters that model rejected, so we stop sending them


def rate_ok():
    now = time.time()
    _hits[:] = [t for t in _hits if now - t < 60]
    if len(_hits) >= 40:
        return False
    _hits.append(now)
    return True


def parse_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    for cand in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t else ""):
        if not cand:
            continue
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    return None


def retry_seconds(e, msg):
    ra = e.headers.get("retry-after") if e.headers else None
    try:
        if ra:
            return max(1, int(float(ra)))
    except ValueError:
        pass
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", msg or "")
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0 for x in m.groups())
        return max(1, int(h * 3600 + mi * 60 + s + 0.99))
    return 20


def err_text(e):
    try:
        raw = e.read().decode("utf-8", "ignore")
        j = json.loads(raw)
        er = j.get("error")
        return str(er.get("message") if isinstance(er, dict) else er or raw)[:500]
    except Exception:
        return ""


def chat_json(system, user, max_tokens, temperature):
    key, base, model = conf()
    prov = provider_of(base)
    if not key and prov != "custom":
        raise AIError("No AI key saved for %s yet. Click ⚙ AI key and paste it." % prov, 400)
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    learned = LEARNED.setdefault((base, model), set())
    tok = "max_completion_tokens" if prov == "openai" or "max_tokens" in learned else "max_tokens"
    body[tok] = max_tokens
    if "gpt-oss" in model or prov == "openai":
        body["reasoning_effort"] = os.environ.get("AI_REASONING", "low")
    for p in learned - {"max_tokens"}:
        body.pop(p, None)
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if key:
        headers["Authorization"] = "Bearer " + key
    attempt, shrunk, fmt_tries = 0, False, 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=240) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            msg = err_text(e)
            low = msg.lower()
            if e.code in (402, 429) and any(w in low for w in ("insufficient_quota", "exceeded your current quota", "no credits",
                                                                "add credits", "credit balance", "insufficient credits", "out of credits")):
                raise AIError("Your %s account has no API credit for this key. New credit can take a few minutes to arrive, and it must be "
                              "added to the same organization/project as the key. (%s said: %s)" % (prov, prov, msg[:160]), 402)
            if e.code == 429:
                daily = "per day" in low or "(tpd)" in low or "(rpd)" in low
                raise AIError(("Daily limit of your AI plan reached. " if daily else "") + "Rate limited: " + msg[:160], 429, retry_seconds(e, msg))
            m = re.search(r"Limit (\d+), Requested (\d+)", msg)
            if (e.code == 413 or m) and not shrunk and m:
                over = int(m.group(2)) - int(m.group(1))
                if body[tok] - over - 150 >= 1200:
                    body[tok] = body[tok] - over - 150
                    shrunk = True
                    continue
            if e.code == 413 or m:
                raise AIError("This step needs more tokens per minute than your AI plan allows. Use shorter episodes, "
                              "turn off storyboard prompts, or pick another model in ⚙ AI key.", 413)
            # Some models (e.g. OpenAI reasoning models) reject parameters other models accept: drop or rename and retry.
            bad = re.search(r"unsupported (?:parameter|value)[^']*'([a-z_]+)'", low)
            if e.code == 400 and attempt < 6 and bad and bad.group(1) in ("temperature", "reasoning_effort", "response_format", "max_tokens"):
                if bad.group(1) == "max_tokens":
                    body["max_completion_tokens"] = body.pop("max_tokens", max_tokens)
                    tok = "max_completion_tokens"
                else:
                    body.pop(bad.group(1), None)
                learned.add(bad.group(1))  # remember for the next calls with this model
                continue
            if e.code == 400 and attempt < 3 and ("json" in low or "response_format" in low or "failed_generation" in low):
                body.pop("response_format", None)
                continue
            if e.code in (401, 403):
                raise AIError("Your AI key was rejected (%d). Open ⚙ AI key and paste it again." % e.code, 401)
            if e.code == 404:
                raise AIError("Model or address not found: %s. Check it in ⚙ AI key." % model, 400)
            if e.code >= 500 and attempt < 3:
                time.sleep(2 * attempt)
                continue
            raise AIError("AI error %d: %s" % (e.code, msg[:200]), 502)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2)
                continue
            raise AIError("Could not reach the AI service. Check your internet connection.", 502)
        ch = (out.get("choices") or [{}])[0]
        data = parse_json((ch.get("message") or {}).get("content") or "")
        if data is not None:
            return data
        fmt_tries += 1
        if fmt_tries >= 3:
            raise AIError("The AI answered in a broken format. Press the button again to retry.", 502)
        if ch.get("finish_reason") == "length":
            body[tok] = min(16000, int(body[tok] * 1.5))
        if "temperature" in body:
            body["temperature"] = max(0.3, temperature - 0.3)


MODEL_SKIP = re.compile(r"embed|whisper|tts|dall-e|image|audio|realtime|transcribe|moderation|search|davinci|babbage|computer-use|guard", re.I)


def list_models(prov, key):
    """Chat models this key can use, straight from the provider's /models list."""
    base = PRESETS.get(prov, (conf()[1],))[0] if prov != "custom" else conf()[1]
    headers = {"User-Agent": UA}
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/models", headers=headers), timeout=20) as r:
            data = json.load(r).get("data") or []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AIError("That key was rejected by %s. Copy it again." % prov, 401)
        raise AIError("Could not list models (%d)." % e.code, 502)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise AIError("Could not reach %s to list models." % prov, 502)
    ids = sorted({str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id") and not MODEL_SKIP.search(str(m.get("id")))})
    return ids[:300]


def run_task(task, inp):
    if task not in DP.TASKS:
        raise AIError("Unknown task.", 400)
    build, clean = DP.TASKS[task]
    if MOCK:
        time.sleep(0.6)
        return clean(DP.mock(task, inp), inp)
    system, user, max_tokens, temperature = build(inp)
    last = None
    for _ in range(2):
        data = chat_json(system, user, max_tokens, temperature)
        try:
            return clean(data, inp)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            last = e
            temperature = max(0.4, temperature - 0.2)
    raise AIError("The AI's answer was missing parts (%s). Press the button again to retry." % last, 502)


# ------------------------------------------------------------------------------------------
# Projects (saved as JSON files in ./projects)
# ------------------------------------------------------------------------------------------
def proj_path(pid):
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise ValueError("bad id")
    return PROJECTS / (pid + ".json")


def list_projects():
    out = []
    if PROJECTS.is_dir():
        for f in PROJECTS.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            eps = d.get("eps") or []
            b = d.get("bible") or {}
            out.append({"id": f.stem, "title": (b.get("title") or (d.get("premise") or {}).get("idea") or "Untitled")[:80],
                        "updated": d.get("updated", 0), "total": d.get("total") or len(eps),
                        "done": sum(1 for e in eps if isinstance(e, dict) and e.get("status") == "produced")})
    out.sort(key=lambda x: x["updated"] or 0, reverse=True)
    return out


class H(BaseHTTPRequestHandler):
    server_version = "DramaBots/1.0"

    def log_message(self, *a):
        pass

    def send_json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def guard(self):
        # Only this page may call the API: a localhost Host header (blocks DNS rebinding) and a custom
        # header that other websites cannot send without a CORS preflight, which this server never allows.
        host = (self.headers.get("Host") or "").lower()
        host = host[1:host.find("]")] if host.startswith("[") else host.split(":")[0]
        return host in ("localhost", "127.0.0.1") and self.headers.get("X-Drama") == "1"

    def body_json(self, limit):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            self.rfile.read(min(n, limit))
            raise OverflowError
        d = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(d, dict):
            raise ValueError
        return d

    def do_GET(self):
        u = urlsplit(self.path)
        p = u.path
        if p.startswith("/api/"):
            if not self.guard():
                return self.send_json(403, {"error": "forbidden"})
            q = parse_qs(u.query)
            if p == "/api/status":
                key, base, model = conf()
                return self.send_json(200, {"keySet": bool(key) or MOCK or provider_of(base) == "custom", "mock": MOCK,
                                            "provider": provider_of(base), "model": model, "base": base, "keys": saved_keys()})
            if p == "/api/projects":
                return self.send_json(200, {"projects": list_projects()})
            if p == "/api/project":
                try:
                    f = proj_path((q.get("id") or [""])[0])
                except ValueError:
                    return self.send_json(400, {"error": "Bad project id."})
                if not f.is_file():
                    return self.send_json(404, {"error": "Project not found."})
                return self.send_json(200, {"project": json.loads(f.read_text(encoding="utf-8"))})
            if p == "/api/media/status":
                return self.send_json(200, {"key": bool(M.key()) or MOCK, "mock": MOCK, "models": M.models()})
            return self.send_json(404, {"error": "not found"})
        if p.startswith("/media/"):
            return self.serve_media(p)
        f = STATIC / ("index.html" if p == "/" else p.lstrip("/"))
        try:
            ok = f.resolve().is_relative_to(STATIC.resolve()) and f.is_file()
        except (OSError, ValueError):
            ok = False
        if not ok:
            return self.send_json(404, {"error": "not found"})
        b = f.read_bytes()
        ct = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml", "png": "image/png",
              "webp": "image/webp", "json": "application/json", "ico": "image/x-icon"}.get(f.suffix[1:].lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ct + ("; charset=utf-8" if ct.startswith(("text", "application/json", "image/svg")) else ""))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def serve_media(self, p):
        # /media/<project-id>/<file>. <img>/<video> tags can't send custom headers, so only the Host is checked here.
        host = (self.headers.get("Host") or "").lower().split(":")[0]
        parts = p.split("/")
        if host not in ("localhost", "127.0.0.1") or len(parts) != 4:
            return self.send_json(404, {"error": "not found"})
        try:
            proj_path(parts[2])
            f = M.media_dir(PROJECTS, parts[2]) / M.safe_file(parts[3])
        except (ValueError, M.MediaError):
            return self.send_json(404, {"error": "not found"})
        if not f.is_file():
            return self.send_json(404, {"error": "not found"})
        size, ctype = f.stat().st_size, M.MIME[f.suffix[1:]]
        start, end, status = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):  # videos need byte ranges to seek
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        if not self.guard():
            return self.send_json(403, {"error": "forbidden"})
        try:
            if self.path == "/api/media/key":
                k = str(self.body_json(5000).get("key") or "").strip()
                if not re.fullmatch(r"[A-Za-z0-9_\-]{20,200}", k):
                    return self.send_json(400, {"error": "That doesn't look like a Gemini API key. Copy it again from Google AI Studio."})
                M.test_key(k)
                set_env({"GEMINI_API_KEY": k})
                return self.send_json(200, {"key": True, "models": M.models()})
            if self.path in ("/api/media/image", "/api/media/tts", "/api/media/video"):
                d = self.body_json(200000)
                pid = str(d.get("pid") or "")
                proj_path(pid)  # validates the id
                if self.path == "/api/media/image":
                    r = M.make_image(PROJECTS, pid, d.get("file"), d.get("prompt", ""), d.get("refs") or [], str(d.get("aspect") or "9:16"), str(d.get("quality") or "standard"))
                elif self.path == "/api/media/tts":
                    r = M.make_tts(PROJECTS, pid, d.get("file"), d.get("text", ""), d.get("voice"), d.get("style", ""))
                else:
                    r = M.make_video(PROJECTS, pid, d.get("file"), d.get("prompt", ""), d.get("image"), d.get("duration", 6), str(d.get("resolution") or "720p"))
                r["url"] = "/media/%s/%s" % (pid, r["file"])
                return self.send_json(200, r)
            if self.path == "/api/ai":
                d = self.body_json(400000)
                if not rate_ok():
                    return self.send_json(429, {"error": "Too many requests. Wait a minute.", "retry_after": 30})
                inp = d.get("input") if isinstance(d.get("input"), dict) else {}
                return self.send_json(200, {"result": run_task(str(d.get("task", "")), inp)})
            if self.path == "/api/key":
                d = self.body_json(20000)
                prov = str(d.get("provider") or "groq")
                key = str(d.get("key") or "").strip()
                base = str(d.get("base") or "").strip().rstrip("/")
                model = str(d.get("model") or "").strip()
                if prov in PRESETS:
                    base = PRESETS[prov][0]
                    model = model or PRESETS[prov][1]
                u = urlsplit(base)
                local = (u.hostname or "") in ("localhost", "127.0.0.1")
                if not base or not (u.scheme == "https" or (u.scheme == "http" and local)):
                    return self.send_json(400, {"error": "The address must start with https:// (or http://localhost for a local model)."})
                if not model or not re.fullmatch(r"[A-Za-z0-9_./:@-]{1,120}", model):
                    return self.send_json(400, {"error": "Type the model name."})
                upd = {"AI_BASE_URL": base, "AI_MODEL": model}
                var = KEYVARS[provider_of(base)]
                if key:
                    if not re.fullmatch(r"[A-Za-z0-9_\-.:]{16,300}", key):
                        return self.send_json(400, {"error": "That does not look like a valid key. Copy it again."})
                    upd[var] = key
                elif not os.environ.get(var) and provider_of(base) != "custom":
                    return self.send_json(400, {"error": "Paste your key first."})
                set_env(upd)
                k2, b2, m2 = conf()
                return self.send_json(200, {"keySet": bool(k2) or provider_of(b2) == "custom", "provider": provider_of(b2), "model": m2,
                                            "base": b2, "keys": saved_keys()})
            if self.path == "/api/models":
                d = self.body_json(20000)
                prov = str(d.get("provider") or provider_of(conf()[1]))
                prov = prov if prov in KEYVARS else "custom"
                key = str(d.get("key") or "").strip() or os.environ.get(KEYVARS[prov], "")
                if not key and prov != "custom":
                    return self.send_json(400, {"error": "Paste your key first."})
                if MOCK:
                    return self.send_json(200, {"models": ["mock-model-a", "mock-model-b"]})
                return self.send_json(200, {"models": list_models(prov, key)})
            if self.path == "/api/test":
                key, base, model = conf()
                t0 = time.time()
                if MOCK:
                    return self.send_json(200, {"ok": True, "ms": 5, "provider": "mock", "model": model})
                try:
                    reply = chat_json('You are a connection test. Answer ONLY with JSON: {"ok": true, "line": "<one dramatic sentence of 8 words or fewer>"}',
                                      "Test the connection.", 1500, 0.7)
                    return self.send_json(200, {"ok": True, "ms": int((time.time() - t0) * 1000), "provider": provider_of(base), "model": model,
                                                "line": str(reply.get("line", ""))[:120]})
                except AIError as e:
                    out = {"ok": False, "error": str(e), "provider": provider_of(base), "model": model}
                    if e.code in (400, 404, 502):
                        try:
                            out["models"] = list_models(provider_of(base), key)
                        except AIError:
                            pass
                    return self.send_json(200, out)
            if self.path == "/api/project":
                d = self.body_json(12 * 1024 * 1024)
                proj = d.get("project")
                if not isinstance(proj, dict):
                    return self.send_json(400, {"error": "No project."})
                f = proj_path(proj.get("id"))
                PROJECTS.mkdir(exist_ok=True)
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, f)
                return self.send_json(200, {"ok": True})
            if self.path == "/api/project/delete":
                f = proj_path(self.body_json(2000).get("id"))
                if f.is_file():
                    TRASH.mkdir(parents=True, exist_ok=True)
                    stamp = int(time.time())
                    os.replace(f, TRASH / ("%s-%d.json" % (f.stem, stamp)))
                    md = M.media_dir(PROJECTS, f.stem)
                    if md.is_dir():  # its images, voices and clips go to the trash too
                        os.replace(md, TRASH / ("%s-%d_media" % (f.stem, stamp)))
                return self.send_json(200, {"ok": True})
            return self.send_json(404, {"error": "not found"})
        except (AIError, M.MediaError) as e:
            return self.send_json(e.code, {"error": str(e), "retry_after": e.retry_after})
        except OverflowError:
            return self.send_json(413, {"error": "That is too big."})
        except ValueError:
            return self.send_json(400, {"error": "Could not read that request."})
        except Exception as e:  # keep the server alive, tell the page what happened
            return self.send_json(500, {"error": "Server error: %s" % type(e).__name__})


if __name__ == "__main__":
    migrate_legacy_key()
    key, base, model = conf()
    # On Windows, address reuse lets a second copy silently share the port and answer half the requests: refuse instead.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        print("Port %d is busy. Is 24/7 Drama Bots already open? Close it, or set PORT=another number in .env." % PORT)
        sys.exit(1)
    print("24/7 Drama Bots, created by John Wayne Maquinta")
    print("Studio open on http://localhost:%d   (AI: %s, model %s, key set: %s%s)"
          % (PORT, provider_of(base), model, bool(key), ", MOCK MODE" if MOCK else ""))
    srv.serve_forever()
