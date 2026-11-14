"""Gemini (Google) asosidagi agent - bepul tarif bilan ishlatish uchun.

Claude agenti (core.Agent) bilan bir xil ishlaydi: o'ylaydi -> amal bajaradi -> natijani ko'radi.
"""
import re

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


class GeminiAgent:
    def __init__(self, human: Human, client: genai.Client | None = None):
        # Kalit GEMINI_API_KEY (yoki GOOGLE_API_KEY) muhit o'zgaruvchisidan olinadi
        self.client = client or genai.Client()
        self.human = human
        self.contents: list[types.Content] = []
        self.model = config.GEMINI_MODEL

    def _generate(self, **kw):
        """So'rov yuboradi; model eskirgan bo'lsa (404), mavjud eng yangisiga o'tib qayta urinadi."""
        try:
            return self.client.models.generate_content(model=self.model, **kw)
        except errors.APIError as e:
            if e.code != 404:
                raise
            new = pick_model(self.client)
            if not new or new == self.model:
                raise
            self.model = new
            return self.client.models.generate_content(model=self.model, **kw)

    def reset(self):
        self.contents = []

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT + "\n\n" + system_context(),
            tools=_TOOLS,
            # Vositalarni SDK emas, o'zimiz chaqiramiz - ruxsat so'rash uchun
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
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
            except errors.APIError as e:
                if e.code == 429:
                    final = ("Bepul tarif limitiga yetildi (juda ko'p so'rov). "
                             "Bir daqiqa kutib qayta urinib ko'ring.")
                elif e.code in (400, 401, 403):
                    final = f"API kaliti yoki so'rovda muammo ({e.code}): {e.message}"
                else:
                    final = f"Gemini xatosi ({e.code}): {e.message}"
                break
            except OSError:
                final = "Internetga ulanib bo'lmadi."
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
