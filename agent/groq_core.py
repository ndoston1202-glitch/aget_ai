"""Groq (bepul, juda tez) asosidagi agent. Groq OpenAI bilan mos API ishlatadi.

Boshqa agentlar (Claude, Gemini) bilan bir xil ishlaydi: o'ylaydi -> amal bajaradi -> natijani ko'radi.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from . import config, memory
from .core import SYSTEM_PROMPT, _short, error_kind
from .tools import FETCH_URL_DEF, TOOL_DEFS, Human, execute, system_context

API = "https://api.groq.com/openai/v1"
# Vositalar bilan yaxshi ishlaydigan modellar (birinchi mavjudi tanlanadi)
PREFERRED = [
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]
TOOLS = [{"type": "function", "function": {"name": d["name"], "description": d["description"],
                                            "parameters": d["input_schema"]}}
         for d in TOOL_DEFS + [FETCH_URL_DEF]]
_models_cache: list[str] | None = None


class GroqError(Exception):
    def __init__(self, code: int, message: str, retry_after: str = ""):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


def _key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise GroqError(401, "Groq API kaliti kiritilmagan (Sozlamalar).")
    return key


def request(path: str, body: dict | None = None, timeout: int = 60, raw: bytes | None = None,
            content_type: str = "application/json") -> dict:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(API + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Authorization": f"Bearer {_key()}", "Content-Type": content_type,
                                          "User-Agent": "AI-Agent"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            msg = json.loads(text).get("error", {}).get("message", text)
        except json.JSONDecodeError:
            msg = text
        raise GroqError(e.code, msg[:500], e.headers.get("retry-after", "")) from None


def available_models() -> list[str]:
    global _models_cache
    if _models_cache is None:
        data = request("/models", timeout=20).get("data", [])
        _models_cache = [m["id"] for m in data if m.get("active", True)]
    return _models_cache


def candidate_models() -> list[str]:
    """Kalit uchun mavjud modellar, yaxshisidan boshlab."""
    try:
        have = available_models()
    except Exception:
        return PREFERRED[:]
    ordered = [m for m in PREFERRED if m in have]
    ordered += [m for m in have if ("llama" in m or "qwen" in m) and m not in ordered
                and "guard" not in m and "whisper" not in m]
    return ordered or PREFERRED[:]


def describe_error(e: Exception) -> str:
    if isinstance(e, GroqError):
        if e.code == 429:
            wait = f" ({e.retry_after} soniyadan keyin)" if e.retry_after else ""
            return f"Groq limitiga yetildi. Biroz kutib qayta urinib ko'ring{wait}."
        if e.code == 401:
            return "Groq API kaliti noto'g'ri yoki kiritilmagan. Sozlamalarni tekshiring."
        return f"Groq xatosi ({e.code}): {e.message}"
    if "timed out" in str(e).lower() or "Timeout" in type(e).__name__:
        return "Groq serveri belgilangan vaqtda javob bermadi. Qayta urinib ko'ring."
    if isinstance(e, OSError):
        return "Groq serveriga ulanib bo'lmadi. Internetni tekshiring."
    return f"Kutilmagan xato: {type(e).__name__}: {e}"


def transcribe(path) -> str:
    """Ovozli faylni Groq Whisper bilan matnga aylantiradi (bepul)."""
    from pathlib import Path
    path = Path(path)
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("model", "whisper-large-v3-turbo"), ("response_format", "json")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    data = request("/audio/transcriptions", raw=b"".join(parts), timeout=120,
                   content_type=f"multipart/form-data; boundary={boundary}")
    text = (data.get("text") or "").strip()
    if not text:
        raise RuntimeError("Ovozdan matn chiqmadi.")
    return text


def diagnose(on_line=lambda s: None) -> str | None:
    t = time.time()
    try:
        models = candidate_models()
        available_models()
    except Exception as e:
        on_line(f"❌ Groq bilan aloqa yo'q: {describe_error(e)}")
        return None
    on_line(f"✅ Groq bilan aloqa bor ({time.time() - t:.1f} s).")
    best = None
    for name in models[:4]:
        t = time.time()
        try:
            r = request("/chat/completions", {"model": name, "max_completion_tokens": 50,
                                              "messages": [{"role": "user", "content": "Bitta so'z bilan: salom"}]},
                        timeout=40)
            text = (r["choices"][0]["message"].get("content") or "").strip()
            on_line(f"✅ {name}: {time.time() - t:.1f} s — \"{text[:40]}\"")
            best = best or name
        except Exception as e:
            on_line(f"❌ {name}: {describe_error(e)}")
    return best


class GroqAgent:
    MAX_SAVED = 80

    def __init__(self, human: Human):
        self.human = human
        self.messages: list[dict] = []
        saved = os.environ.get("GROQ_MODEL", "").strip()
        self._alts: list[str] | None = None
        self.model = saved or PREFERRED[0]
        self._resolved = bool(saved)  # mavjud modellar ro'yxati birinchi so'rovda olinadi (oyna qotmasin)
        self.on_switch = lambda model: None

    def reset(self):
        self.messages = []

    def undo_turn(self):
        del self.messages[getattr(self, "_turn_start", len(self.messages)):]

    def load_text_history(self, pairs: list) -> None:
        self.messages = []
        for user, answer in pairs:
            self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]

    def export_state(self) -> list:
        out = self.messages
        if len(out) > self.MAX_SAVED:
            start = len(out) - self.MAX_SAVED
            while start < len(out) and out[start]["role"] != "user":
                start += 1
            out = out[start:]
        return out

    def load_state(self, data: list) -> None:
        self.messages = list(data)

    def _alternatives(self) -> list[str]:
        if self._alts is None:
            self._alts = candidate_models()
        return self._alts

    def _chat(self, messages: list, tools: bool = True, **extra) -> dict:
        """So'rov yuboradi; model ishlamasa boshqasiga o'tib qayta urinadi."""
        if not self._resolved:
            self._resolved = True
            models = candidate_models()
            if models and self.model not in models:
                self.model = models[0]
        tried = set()
        while True:
            body = {"model": self.model, "messages": messages, "temperature": 0.5,
                    "max_completion_tokens": 4096, **extra}
            if tools:
                body["tools"] = TOOLS
                body["tool_choice"] = "auto"
            t = time.time()
            config.log_error(f"start groq model={self.model}")
            try:
                r = request("/chat/completions", body, timeout=60)
                config.log_error(f"ok groq model={self.model} {time.time() - t:.1f}s")
                return r
            except Exception as e:
                code = getattr(e, "code", None)
                config.log_error(f"fail groq model={self.model} {time.time() - t:.1f}s: {e}")
                msg = str(getattr(e, "message", "")).lower()
                switchable = (code in (404, 500, 502, 503, 504) or "timed out" in str(e).lower()
                              or (code == 400 and ("decommission" in msg or "not found" in msg
                                                   or "does not support" in msg or "tool" in msg)))
                tried.add(self.model)
                new = next((m for m in self._alternatives() if m not in tried), None)
                if not switchable or not new or len(tried) >= 4:
                    raise
                self.model = new
                self.on_switch(new)

    def _complete_json(self, prompt: str, schema: dict) -> str:
        r = self._chat([{"role": "user", "content": prompt}], tools=False,
                       response_format={"type": "json_object"})
        return r["choices"][0]["message"].get("content") or ""

    def run(self, user_text: str, on_event=print, learn: bool = True) -> str:
        self.last_error = None
        self._turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        transcript = [f"USER: {user_text}"]
        used_tools = False
        final = ""
        for _ in range(config.MAX_STEPS):
            system = {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + system_context()}
            try:
                r = self._chat([system] + self.messages)
            except Exception as e:
                final = describe_error(e)
                self.last_error = error_kind(getattr(e, "code", None))
                break
            msg = r["choices"][0]["message"]
            text = (msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                entry["tool_calls"] = [{"id": c["id"], "type": "function", "function": c["function"]}
                                       for c in calls]
            self.messages.append(entry)
            if text:
                transcript.append(f"AGENT: {text}")
            if not calls:
                final = text or "(javob bo'sh)"
                break
            if text:
                on_event(f"💭 {text}")
            for c in calls:
                used_tools = True
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments is not an object")
                except (json.JSONDecodeError, ValueError):
                    output, is_error = "Xato: vosita argumentlari noto'g'ri JSON. Qayta urin.", True
                else:
                    on_event(f"🔧 {name}({_short(args)})")
                    output, is_error = execute(name, args, self.human)
                    if name == "generate_image" and not is_error:
                        on_event("🖼 " + output.split(": ", 1)[-1])
                transcript.append(f"TOOL {name} -> {'XATO: ' if is_error else ''}{output[:1500]}")
                self.messages.append({"role": "tool", "tool_call_id": c["id"],
                                      "content": ("XATO: " if is_error else "") + output})
        else:
            final = f"{config.MAX_STEPS} qadamdan keyin to'xtadim - vazifa juda uzun bo'lib ketdi."

        if learn and used_tools:
            transcript.append(f"YAKUN: {final}")
            for lesson in memory.reflect(self._complete_json, user_text, "\n".join(transcript)):
                on_event(f"🧠 Yangi saboq: {lesson}")
        return final
