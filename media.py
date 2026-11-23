"""24/7 Drama Bots: images, voices and video clips with the Gemini API (Interactions endpoint).

Everything is saved next to the project, in projects/<project-id>_media/.
Models (override in .env):
  MEDIA_IMAGE_MODEL  gemini-nano-banana-2.1   (shot images, character references)
  MEDIA_TTS_MODEL    gemini-3.8-flash-tts     (character voices, 130+ languages incl. Filipino)
  MEDIA_VIDEO_MODEL  gemini-omni-1.2-flash    (3-15 s vertical clips with native audio)
"""
import base64
import io
import json
import math
import os
import re
import struct
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

GEM = "https://generativelanguage.googleapis.com/v1beta"
UA = "drama-bots/1.0"
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,90}\.(jpg|png|svg|wav|mp4)$")
IMAGE_MODELS = {"fast": "gemini-3.1-flash-lite-image", "standard": "gemini-nano-banana-2.1", "best": "gemini-3-pro-image"}
MIME = {"jpg": "image/jpeg", "png": "image/png", "svg": "image/svg+xml", "wav": "audio/wav", "mp4": "video/mp4"}


class MediaError(Exception):
    def __init__(self, msg, code=502, retry_after=0):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after


def key():
    return os.environ.get("GEMINI_API_KEY", "")


def mock():
    return os.environ.get("DRAMA_MOCK", "") == "1"


def models():
    return {"image": os.environ.get("MEDIA_IMAGE_MODEL") or IMAGE_MODELS["standard"],
            "tts": os.environ.get("MEDIA_TTS_MODEL") or "gemini-3.8-flash-tts",
            "video": os.environ.get("MEDIA_VIDEO_MODEL") or "gemini-omni-1.2-flash"}


def media_dir(projects, pid, create=False):
    d = Path(projects) / (pid + "_media")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def safe_file(name):
    name = str(name or "").lower()
    if not FILE_RE.match(name):
        raise MediaError("Bad media file name.", 400)
    return name


# ------------------------------------------------------------------------------------------ Gemini calls
def _err_text(e):
    try:
        raw = e.read().decode("utf-8", "ignore")
        j = json.loads(raw)
        er = j.get("error")
        return str(er.get("message") if isinstance(er, dict) else er or raw)[:500]
    except Exception:
        return ""


def _retry_seconds(e, msg):
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


def _raise_http(e, model):
    msg = _err_text(e)
    low = msg.lower()
    if any(w in low for w in ("billing", "no credits", "add credits", "insufficient_quota", "exceeded your current quota", "paid tier", "free tier")):
        raise MediaError("Your Gemini key needs billing turned on for this (Google AI Studio → Billing). Google said: " + msg[:160], 402)
    if e.code in (401, 403):
        raise MediaError("Google rejected your Gemini key (%d). Open ⚙ AI key and paste it again. %s" % (e.code, msg[:120]), 401)
    if e.code == 404:
        raise MediaError("Gemini model not found: %s. Google may have renamed it; set the new name in .env. %s" % (model, msg[:120]), 400)
    if e.code == 429:
        raise MediaError("Gemini says slow down: " + msg[:160], 429, _retry_seconds(e, msg))
    raise MediaError("Gemini error %d: %s" % (e.code, msg[:240]), 400 if e.code == 400 else 502)


def gem_post(body, timeout):
    if not key():
        raise MediaError("Add your Gemini API key first: ⚙ AI key → Images, voices & video.", 400)
    headers = {"Content-Type": "application/json", "x-goog-api-key": key(), "User-Agent": UA, "Api-Revision": "2026-05-20"}
    for attempt in range(3):
        try:
            req = urllib.request.Request(GEM + "/interactions", data=json.dumps(body).encode(), method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400 and "Api-Revision" in headers:
                msg = _err_text(e)
                if "revision" in msg.lower():
                    headers.pop("Api-Revision")
                    continue
                e.read = lambda m=msg: json.dumps({"error": {"message": m}}).encode()  # already consumed: hand it back
            if e.code >= 500 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            _raise_http(e, body.get("model"))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 1:
                time.sleep(2)
                continue
            raise MediaError("Could not reach Google. Check your internet connection.", 502)
    raise MediaError("Gemini did not answer. Try again.", 502)


def _get(url, timeout=120, auth=True):
    h = {"User-Agent": UA}
    if auth:
        h["x-goog-api-key"] = key()
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def gem_download(uri):
    """Download a generated file given as a URI (polls until it's ACTIVE first)."""
    m = re.search(r"/files/([^/:?]+)", uri)
    url = uri
    if m:
        fid = m.group(1)
        for _ in range(150):  # up to ~12 minutes
            try:
                st = json.loads(_get("%s/files/%s" % (GEM, fid), 30))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                st = {}
            state = str(st.get("state", "")).upper()
            if state == "ACTIVE" or not st:
                break
            if state == "FAILED":
                raise MediaError("Google could not finish that clip. Try again.", 502)
            time.sleep(5)
        url = "%s/files/%s:download?alt=media" % (GEM, fid)
    try:
        return _get(url, 300)
    except urllib.error.HTTPError:
        sep = "&" if "?" in url else "?"
        return _get(url + sep + "key=" + key(), 300, auth=False)  # some download links only accept the key as a parameter


def gem_output(out, kind):
    """Find the generated image/audio/video in an Interactions response."""
    texts = []
    for st in out.get("steps") or []:
        if st.get("type") != "model_output":
            continue
        for c in st.get("content") or []:
            if c.get("type") == kind:
                if c.get("data"):
                    return base64.b64decode(c["data"])
                if c.get("uri"):
                    return gem_download(c["uri"])
            elif c.get("type") == "text" and c.get("text"):
                texts.append(c["text"])
    conv = out.get("output_" + kind)
    if isinstance(conv, dict):
        if conv.get("data"):
            return base64.b64decode(conv["data"])
        if conv.get("uri"):
            return gem_download(conv["uri"])
    why = " ".join(texts)[:220] or "It may have been blocked by Google's safety filters: soften the prompt (less violence) and try again."
    raise MediaError("Gemini made no %s. %s" % (kind, why), 502)


def test_key(k):
    try:
        urllib.request.urlopen(urllib.request.Request(GEM + "/models?pageSize=1", headers={"x-goog-api-key": k, "User-Agent": UA}), timeout=20).read()
        return True
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise MediaError("Google rejected that key. Copy it again from Google AI Studio → Get API key.", 401)
        raise MediaError("Google answered with error %d. Try again in a minute." % e.code, 502)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise MediaError("Could not reach Google to check the key. Check your internet connection.", 502)


# ------------------------------------------------------------------------------------------ the three makers
def _part_for(path):
    ext = path.suffix[1:].lower()
    if ext not in ("jpg", "png"):
        return None
    return {"type": "image", "mime_type": MIME[ext], "data": base64.b64encode(path.read_bytes()).decode()}


def make_image(projects, pid, file, prompt, refs=(), aspect="9:16", quality="standard"):
    d = media_dir(projects, pid, True)
    file = safe_file(file)
    if mock():
        file = re.sub(r"\.\w+$", ".svg", file)
        (d / file).write_text(mock_svg(prompt, aspect), encoding="utf-8")
        return {"file": file}
    model = os.environ.get("MEDIA_IMAGE_MODEL") if quality == "standard" and os.environ.get("MEDIA_IMAGE_MODEL") else IMAGE_MODELS.get(quality, IMAGE_MODELS["standard"])
    parts = [{"type": "text", "text": str(prompt)[:4000]}]
    for r in list(refs)[:4]:
        p = d / safe_file(r)
        part = _part_for(p) if p.is_file() else None
        if part:
            parts.append(part)
    body = {"model": model, "input": parts if len(parts) > 1 else parts[0]["text"],
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": aspect, "image_size": "1K"}}
    data = gem_output(gem_post(body, 240), "image")
    file = re.sub(r"\.\w+$", ".jpg", file)
    (d / file).write_bytes(data)
    return {"file": file}


def wav_seconds(data):
    try:
        with wave.open(io.BytesIO(data)) as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0


def pcm_to_wav(pcm, rate=24000):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def make_tts(projects, pid, file, text, voice, style=""):
    d = media_dir(projects, pid, True)
    file = re.sub(r"\.\w+$", ".wav", safe_file(file))
    if mock():
        data = mock_wav(max(0.8, len(str(text).split()) * 0.34))
    else:
        item = {"type": "text", "text": str(text)[:1500]}
        if style:
            item["annotations"] = [{"type": "speech_metadata", "style": str(style)[:200]}]
        body = {"model": models()["tts"], "input": [{"type": "user_input", "content": [item]}],
                "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": str(voice or "Kore")}]}}
        data = gem_output(gem_post(body, 120), "audio")
        if data[:4] != b"RIFF":
            data = pcm_to_wav(data)
    (d / file).write_bytes(data)
    return {"file": file, "dur": wav_seconds(data)}


def make_video(projects, pid, file, prompt, image=None, duration=6, resolution="720p"):
    d = media_dir(projects, pid, True)
    file = re.sub(r"\.\w+$", ".mp4", safe_file(file))
    if mock():
        raise MediaError("Mock mode can't make video clips (the episode uses the still image instead).", 400)
    parts = []
    if image:
        p = d / safe_file(image)
        part = _part_for(p) if p.is_file() else None
        if part:
            parts.append(part)
    parts.append({"type": "text", "text": str(prompt)[:3000]})
    duration = max(3, min(15, int(duration or 6)))
    body = {"model": models()["video"], "input": parts if len(parts) > 1 else parts[0]["text"],
            "response_format": {"type": "video", "aspect_ratio": "9:16", "duration": "%ds" % duration,
                                "resolution": resolution if resolution in ("360p", "720p", "1080p") else "720p", "delivery": "uri"}}
    try:
        out = gem_post(body, 900)
    except MediaError as e:
        if e.code != 400 or len(parts) < 2:
            raise
        body["generation_config"] = {"video_config": {"task": "image_to_video"}}  # documented fallback for first-frame clips
        out = gem_post(body, 900)
    data = gem_output(out, "video")
    (d / file).write_bytes(data)
    return {"file": file, "dur": duration}


# ------------------------------------------------------------------------------------------ mock mode (no key, no internet)
def mock_svg(prompt, aspect):
    w, h = (720, 1280) if aspect == "9:16" else (900, 1200)
    hue = sum(map(ord, str(prompt)[:60])) % 360
    words, lines, cur = str(prompt)[:220].split(), [], ""
    for wd in words:
        if len(cur) + len(wd) > 30:
            lines.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    lines.append(cur)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    txt = "".join('<text x="50%%" y="%d" text-anchor="middle" font-size="30" fill="#fff" font-family="sans-serif">%s</text>' % (h * 0.42 + i * 40, esc(l)) for i, l in enumerate(lines[:7]))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="hsl(%d,60%%,35%%)"/><stop offset="1" stop-color="hsl(%d,55%%,12%%)"/></linearGradient></defs>'
            '<rect width="100%%" height="100%%" fill="url(#g)"/><circle cx="50%%" cy="30%%" r="120" fill="rgba(255,255,255,.12)"/>'
            '<text x="50%%" y="%d" text-anchor="middle" font-size="26" fill="#ffd34d" font-family="sans-serif">MOCK IMAGE</text>%s</svg>'
            % (w, h, hue, (hue + 50) % 360, h * 0.36, txt))


def mock_wav(seconds, rate=24000):
    n = int(seconds * rate)
    out = bytearray()
    for i in range(n):
        t = i / rate
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 3.2 * t)  # syllable-ish pulses
        v = env * (0.5 * math.sin(2 * math.pi * 170 * t) + 0.3 * math.sin(2 * math.pi * 340 * t + 1) + 0.2 * math.sin(2 * math.pi * 510 * t))
        out += struct.pack("<h", int(max(-1, min(1, v * 0.35)) * 32767))
    return pcm_to_wav(bytes(out), rate)
