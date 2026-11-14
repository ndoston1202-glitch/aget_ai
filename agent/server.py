"""Telefon uchun server: kompyuterdagi agentni telefon ilovasi (APK) yoki brauzer orqali boshqarish.

Telefon /api/... manzillariga so'rov yuboradi; har bir so'rov maxfiy kod (token) bilan tekshiriladi.
"""
import hmac
import json
import mimetypes
import re
import uuid
from pathlib import Path
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config
from .tools import Human
from .webui import INDEX_HTML

PORT = 8765
ANSWER_TIMEOUT = 600  # telefon 10 daqiqa javob bermasa - rad etilgan hisoblanadi


def get_token() -> str:
    """Telefon ulanishi uchun maxfiy kod (bir marta yaratilib, sozlamalarda saqlanadi)."""
    try:
        s = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        s = {}
    if not s.get("phone_token"):
        s["phone_token"] = secrets.token_hex(4).upper()  # masalan: 9F3A1C0B
        config.SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")
    return s["phone_token"]


def lan_ip() -> str:
    """Kompyuterning uy tarmog'idagi (Wi-Fi) IP manzili."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # paket yuborilmaydi, faqat yo'nalish aniqlanadi
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class PhoneSession:
    """Telefondagi suhbat: alohida agent, voqealar ro'yxati va kutilayotgan savollar."""

    def __init__(self, make_agent, on_log=lambda m: None):
        self.make_agent = make_agent
        self.on_log = on_log
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.next_id = 1
        self.pending: dict[int, dict] = {}
        self.busy = False
        self.agent = None

    def emit(self, kind: str, text: str, **extra) -> int:
        with self.lock:
            eid = self.next_id
            self.next_id += 1
            self.events.append({"id": eid, "type": kind, "text": text, **extra})
            self.events = self.events[-500:]
            return eid

    def wait_answer(self, kind: str, text: str):
        box = {"done": threading.Event(), "value": None}
        eid = self.emit(kind, text)
        with self.lock:
            self.pending[eid] = box
        box["done"].wait(ANSWER_TIMEOUT)
        with self.lock:
            self.pending.pop(eid, None)
        return box["value"]

    def answer(self, eid: int, value) -> bool:
        with self.lock:
            box = self.pending.get(eid)
        if not box:
            return False
        box["value"] = value
        box["done"].set()
        self.emit("answered", "", ref=eid)
        return True

    def send(self, text: str) -> bool:
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        if self.agent is None:
            self.agent = self.make_agent(PhoneHuman(self))
        self.emit("user", text)
        self.on_log(f"📱 Telefondan: {text}")

        def work():
            try:
                ans = self.agent.run(text, on_event=self._on_event)
            except Exception as e:
                ans = f"Kutilmagan xato: {e}"
            self.emit("agent", ans)
            self.on_log(f"📱 Agent telefonga javob berdi: {ans[:200]}")
            with self.lock:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def _on_event(self, m: str):
        if m.startswith("🖼 "):
            try:
                rel = Path(m[2:].strip()).resolve().relative_to(config.WORKSPACE_DIR.resolve())
                self.emit("image", rel.as_posix())
                return
            except ValueError:
                pass
        self.emit("event", m)

    def voice(self, data: bytes, filename: str) -> dict:
        """Ovozli xabarni saqlaydi, matnga aylantiradi va agentga topshiradi."""
        from .media import transcribe
        ext = (re.search(r"\.[A-Za-z0-9]{1,5}$", filename or "") or [".m4a"])[0].lower()
        path = config.WORKSPACE_DIR / "voice" / f"ovoz_{uuid.uuid4().hex[:8]}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        text = transcribe(path)
        self.emit("event", "🎤 Ovozli xabar matnga aylantirildi")
        if not self.send(text):
            return {"text": text, "sent": False, "error": "Agent hali oldingi ishni bajaryapti"}
        return {"text": text, "sent": True}

    def reset(self):
        with self.lock:
            if self.busy:
                return False
            self.events = []
        if self.agent:
            self.agent.reset()
        return True

    def snapshot(self, after: int) -> dict:
        with self.lock:
            return {
                "events": [e for e in self.events if e["id"] > after],
                "busy": self.busy,
                "pending": list(self.pending),
            }


class PhoneHuman(Human):
    def __init__(self, session: PhoneSession):
        self.session = session

    def approve(self, action: str) -> bool:
        return self.session.wait_answer("approve", action) is True

    def ask(self, question: str) -> str:
        ans = self.session.wait_answer("ask", question)
        return ans if isinstance(ans, str) and ans else "(javob berilmadi)"


def make_handler(session: PhoneSession, token: str):
    failures = {"count": 0, "locked_until": 0.0}
    fail_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # konsolga yozmaslik (.exe da konsol yo'q)
            pass

        def _authorized(self) -> bool:
            """Kodni tekshiradi; ko'p noto'g'ri urinishdan keyin vaqtincha bloklaydi."""
            with fail_lock:
                if time.time() < failures["locked_until"]:
                    return False
            q = parse_qs(urlparse(self.path).query)
            given = self.headers.get("X-Token") or (q.get("token") or [""])[0]
            ok = hmac.compare_digest(given.strip().upper().encode(), token.encode())
            with fail_lock:
                if ok:
                    failures["count"] = 0
                else:
                    failures["count"] += 1
                    if failures["count"] >= 10:
                        failures["locked_until"] = time.time() + 60
                        failures["count"] = 0
            return ok

        def _json(self, code: int, data: dict):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                body = INDEX_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authorized():
                return self._json(401, {"error": "Kod noto'g'ri"})
            if path == "/api/poll":
                after = int((parse_qs(urlparse(self.path).query).get("after") or ["0"])[0] or 0)
                return self._json(200, session.snapshot(after))
            if path == "/api/file":
                rel = (parse_qs(urlparse(self.path).query).get("p") or [""])[0]
                root = config.WORKSPACE_DIR.resolve()
                f = (root / rel).resolve()
                if not f.is_file() or not f.is_relative_to(root):
                    return self._json(404, {"error": "topilmadi"})
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/ping":
                return self._json(200, {"ok": True, "provider": config.provider()})
            self._json(404, {"error": "topilmadi"})

        def do_POST(self):
            if not self._authorized():
                return self._json(401, {"error": "Kod noto'g'ri"})
            path = urlparse(self.path).path
            if path == "/api/voice":
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 20_000_000:
                    return self._json(400, {"error": "Ovozli fayl bo'sh yoki juda katta"})
                try:
                    return self._json(200, session.voice(self.rfile.read(n), self.headers.get("X-Filename", "")))
                except Exception as e:
                    return self._json(500, {"error": f"Ovozni matnga aylantirib bo'lmadi: {e}"})
            data = self._body()
            if path == "/api/send":
                text = str(data.get("text", "")).strip()
                if not text:
                    return self._json(400, {"error": "Bo'sh xabar"})
                if not session.send(text):
                    return self._json(409, {"error": "Agent hali oldingi ishni bajaryapti"})
                return self._json(200, {"ok": True})
            if path == "/api/answer":
                ok = session.answer(int(data.get("id", 0)), data.get("value"))
                return self._json(200 if ok else 404, {"ok": ok})
            if path == "/api/new":
                ok = session.reset()
                return self._json(200 if ok else 409, {"ok": ok})
            self._json(404, {"error": "topilmadi"})

    return Handler


def start(make_agent, on_log=lambda m: None) -> ThreadingHTTPServer:
    session = PhoneSession(make_agent, on_log)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(session, get_token()))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
