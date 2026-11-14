"""Gemini (Google) asosidagi agent - bepul tarif bilan ishlatish uchun.

Claude agenti (core.Agent) bilan bir xil ishlaydi: o'ylaydi -> amal bajaradi -> natijani ko'radi.
"""
import re
import time

from google import genai
from google.genai import errors, types

from . import config, memory
from .core import SYSTEM_PROMPT, _short
from .tools import FETCH_URL_DEF, TOOL_DEFS, Human, execute, system_context

_DEFS = TOOL_DEFS + [FETCH_URL_DEF]
_TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(name=d["name"], description=d["description"],
                              parameters_json_schema=d["input_schema"])
    for d in _DEFS
])]


def pick_model(client) -> str | None:
    """Kalit uchun mavjud eng yangi 'gemini-X-flash' modelini topadi."""
    best, best_ver = None, -1.0
    for m in client.models.list():
        name = (m.name or "").removeprefix("models/")
        match = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
        actions = m.supported_actions or []
        if match and (not actions or "generateContent" in actions):
            ver = float(match.group(1))
            if ver > best_ver:
                best, best_ver = name, ver
    return best


def _is_user_text(c) -> bool:
    return c.role == "user" and any(p.text for p in (c.parts or []))


def make_client(timeout_s: int = 60) -> genai.Client:
    """Kutish chegarasi bor Gemini mijozi (qayta urinishsiz - aks holda kutish uch barobar cho'ziladi)."""
    return genai.Client(http_options=types.HttpOptions(timeout=timeout_s * 1000))


def diagnose(on_line=lambda s: None) -> str | None:
    """Kalit uchun ochiq Flash modellarni qisqa so'rov bilan sinaydi; eng birinchi ishlaganini qaytaradi."""
    client = make_client(timeout_s=40)
    t = time.time()
    try:
        models = [(m.name or "").removeprefix("models/") for m in client.models.list()]
    except Exception as e:
        on_line(f"❌ Modellar ro'yxatini olib bo'lmadi: {describe_error(e)}")
        config.log_error(f"diagnose list: {type(e).__name__}: {e}")
        return None
    on_line(f"✅ Google bilan aloqa bor ({time.time() - t:.1f} s), {len(models)} ta model topildi.")

    def version(name):
        m = re.match(r"gemini-(\d+(?:\.\d+)?)", name)
        return float(m.group(1)) if m else 0.0
    flash = [n for n in models if re.fullmatch(r"gemini-[\d.]+-flash(-lite)?(-latest)?", n)]
    flash += [n for n in ("gemini-flash-latest", "gemini-flash-lite-latest") if n in models]
    flash = sorted(dict.fromkeys(flash), key=lambda n: (-version(n), "lite" in n))[:5]
    if not flash:
        on_line("❌ Flash modellar topilmadi. Mavjudlari: " + ", ".join(models[:15]))
        return None
    best = None
    for name in flash:
        t = time.time()
        try:
            r = client.models.generate_content(model=name, contents="Bitta so'z bilan javob ber: salom")
            took = time.time() - t
            on_line(f"✅ {name}: {took:.1f} s — \"{(r.text or '').strip()[:40]}\"")
            config.log_error(f"diagnose ok {name} {took:.1f}s")
            if best is None:
                best = name
        except Exception as e:
            msg = "40 soniya ichida javob bermadi" if "Timeout" in type(e).__name__ else describe_error(e)
            on_line(f"❌ {name}: {msg}")
            config.log_error(f"diagnose {name}: {type(e).__name__}: {e}")
    return best


def describe_error(e: Exception) -> str:
    """Xatoni foydalanuvchiga tushunarli qilib aytadi."""
    if isinstance(e, errors.APIError):
        if e.code == 429:
            return ("Bepul tarif limitiga yetildi (juda ko'p so'rov yoki kunlik limit tugadi). "
                    "Bir daqiqa kutib qayta urinib ko'ring.")
        if e.code in (400, 401, 403):
            return f"API kaliti yoki so'rovda muammo ({e.code}): {e.message}"
        return f"Gemini xatosi ({e.code}): {e.message}"
    name = type(e).__name__
    if "Timeout" in name:
        return ("Google serveri belgilangan vaqtda javob bermadi. Yuqoridagi \"Tekshirish\" menyusini "
                "bosing - dastur ishlaydigan modelni o'zi topadi.")
    if "Connect" in name or isinstance(e, OSError):
        return "Google serveriga ulanib bo'lmadi. Internet ulanishini tekshiring."
    return f"Kutilmagan xato: {name}: {e}"


class GeminiAgent:
    def __init__(self, human: Human, client: genai.Client | None = None):
        # Kalit GEMINI_API_KEY (yoki GOOGLE_API_KEY) muhit o'zgaruvchisidan olinadi
        self.client = client or make_client()
        self.human = human
        self.contents: list[types.Content] = []
        self.model = config.GEMINI_MODEL
        self._alts: list[str] | None = None
        self.on_switch = lambda model: None  # oyna yangi modelni eslab qolishi uchun
        self._thinking = types.ThinkingConfig(thinking_level=config.GEMINI_THINKING)

    def _generate(self, **kw):
        """So'rov yuboradi. Model ishlamasa (eskirgan, band, javob bermadi) boshqasiga o'tib qayta urinadi."""
        tried = set()
        while True:
            t = time.time()
            config.log_error(f"start model={self.model}")
            try:
                resp = self.client.models.generate_content(model=self.model, **kw)
                config.log_error(f"ok model={self.model} {time.time() - t:.1f}s")
                return resp
            except Exception as e:
                code = getattr(e, "code", None)
                config.log_error(f"fail model={self.model} {time.time() - t:.1f}s: {type(e).__name__}: {e}")
                # Model "o'ylash" sozlamasini qo'llamasa - sozlamasiz qayta urinamiz
                if code == 400 and "thinking" in str(getattr(e, "message", "")).lower() and self._thinking:
                    self._thinking = None
                    if kw.get("config") is not None:
                        kw["config"].thinking_config = None
                    continue
                retryable = code in (404, 500, 502, 503, 504) or "Timeout" in type(e).__name__
                tried.add(self.model)
                if not retryable or len(tried) >= 3:
                    raise
                new = next((m for m in self._alternatives() if m not in tried), None)
                if not new:
                    raise
                config.log_error(f"switch model {self.model} -> {new}")
                self.model = new
                self.on_switch(new)

    def _alternatives(self) -> list[str]:
        """Zaxira modellar: kalit uchun ochiq Flash modellar, yangisidan eskisiga."""
        if self._alts is None:
            try:
                names = [(m.name or "").removeprefix("models/") for m in self.client.models.list()]
            except Exception:
                names = []

            def ver(n):
                m = re.match(r"gemini-(\d+(?:\.\d+)?)", n)
                return float(m.group(1)) if m else 0.0
            flash = [n for n in names if re.fullmatch(r"gemini-[\d.]+-flash(-lite)?", n)]
            flash.sort(key=lambda n: (-ver(n), "lite" in n))
            extra = [n for n in ("gemini-flash-latest", "gemini-flash-lite-latest") if n in names]
            self._alts = flash + extra
        return self._alts

    def reset(self):
        self.contents = []

    MAX_SAVED = 80  # saqlanadigan xabarlar soni (eskilari tashlanadi)

    def export_state(self) -> list:
        """Suhbatni diskka saqlash uchun JSON ko'rinishiga o'tkazadi."""
        items = self.contents
        if len(items) > self.MAX_SAVED:
            # Faqat foydalanuvchining oddiy matnli xabaridan boshlab kesamiz (vosita juftliklari buzilmasin)
            start = len(items) - self.MAX_SAVED
            while start < len(items) and not _is_user_text(items[start]):
                start += 1
            items = items[start:]
        return [c.model_dump(mode="json", exclude_none=True) for c in items]

    def load_state(self, data: list) -> None:
        try:
            self.contents = [types.Content.model_validate(d) for d in data]
        except Exception as e:
            config.log_error(f"gemini load_state: {e}")
            self.contents = []

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT + "\n\n" + system_context(),
            tools=_TOOLS,
            # Vositalarni SDK emas, o'zimiz chaqiramiz - ruxsat so'rash uchun
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=self._thinking,
        )

    def _complete_json(self, prompt: str, schema: dict) -> str:
        resp = self._generate(
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               response_json_schema=schema),
        )
        return resp.text or ""

    def run(self, user_text: str, on_event=print, learn: bool = True) -> str:
        self.contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        transcript = [f"USER: {user_text}"]
        used_tools = False
        final = ""

        for _ in range(config.MAX_STEPS):
            try:
                resp = self._generate(contents=self.contents, config=self._config())
            except Exception as e:
                config.log_error(f"gemini model={self.model}: {type(e).__name__}: {e}")
                final = describe_error(e)
                break

            cand = resp.candidates[0] if resp.candidates else None
            if cand is None or cand.content is None or not cand.content.parts:
                reason = cand.finish_reason if cand else "javob yo'q"
                final = f"Model javob bermadi ({reason})."
                break

            self.contents.append(cand.content)
            text = "".join(p.text for p in cand.content.parts if p.text and not p.thought).strip()
            if text:
                transcript.append(f"AGENT: {text}")

            calls = [p.function_call for p in cand.content.parts if p.function_call]
            if not calls:
                final = text or "(javob bo'sh)"
                break

            if text:
                on_event(f"💭 {text}")
            parts = []
            for fc in calls:
                used_tools = True
                args = dict(fc.args or {})
                on_event(f"🔧 {fc.name}({_short(args)})")
                output, is_error = execute(fc.name, args, self.human)
                if fc.name == "generate_image" and not is_error:
                    on_event("🖼 " + output.split(": ", 1)[-1])
                transcript.append(f"TOOL {fc.name}({_short(args)}) -> "
                                  f"{'XATO: ' if is_error else ''}{output[:1500]}")
                parts.append(types.Part.from_function_response(
                    name=fc.name, response={"error": output} if is_error else {"result": output}))
            self.contents.append(types.Content(role="user", parts=parts))
        else:
            final = f"{config.MAX_STEPS} qadamdan keyin to'xtadim - vazifa juda uzun bo'lib ketdi."

        if learn and used_tools:
            transcript.append(f"YAKUN: {final}")
            for lesson in memory.reflect(self._complete_json, user_text, "\n".join(transcript)):
                on_event(f"🧠 Yangi saboq: {lesson}")
        return final
