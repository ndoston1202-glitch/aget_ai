"""Agentning asosiy sikli: o'ylaydi -> amal bajaradi -> natijani ko'radi -> davom etadi."""
import json
import anthropic

from . import config, memory
from .tools import SERVER_TOOLS, TOOL_DEFS, Human, execute, system_context

SYSTEM_PROMPT = """Sen foydalanuvchining shaxsiy AI agentisan. Sen faqat suhbatlashmaysan - \
buyruqni tushunib, uni vositalar (tools) yordamida o'zing bajarasan.

Ish tartibi:
1. Vazifani tushun. Agar muhim tafsilot noaniq bo'lsa, ask_user bilan so'ra - taxmin qilma.
2. Reja tuz va qadamma-qadam bajar. Har bir natijani tekshir; xato bo'lsa sababini topib, boshqa yo'l bilan urin.
3. Buyruq ishga tushirish va fayl yozish foydalanuvchi ruxsati bilan bo'ladi. Ruxsat berilmasa, \
boshqa yo'l taklif qil yoki to'xta.
4. Foydalanuvchi takrorlanuvchi ish so'rasa (masalan "har kuni", "har soatda"), schedule_task bilan vazifa yarat.
5. Foydalanuvchi o'zi yoki ish uslubi haqida doimiy narsa aytsa, remember bilan saqla.
6. Oxirida qisqa hisobot ber: nima qilindi, natija qanday, nima qoldi.

Foydalanuvchi bilan o'zbek tilida, qisqa va aniq gaplash. Bajarmagan ishingni bajardim dema."""


class Agent:
    def __init__(self, human: Human, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic(timeout=180.0, max_retries=2)
        self.human = human
        self.messages: list = []

    def reset(self):
        self.messages = []

    def _system(self) -> list[dict]:
        return [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system_context()},
        ]

    def _complete_json(self, prompt: str, schema: dict) -> str:
        resp = self.client.messages.create(
            model=config.MODEL,
            max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason != "end_turn":
            return ""
        return next(b.text for b in resp.content if b.type == "text")

    def _call(self):
        return self.client.beta.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=self._system(),
            tools=TOOL_DEFS + SERVER_TOOLS,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": config.EFFORT},
            # Model so'rovni rad etsa, server avtomatik ravishda mos zaxira modelda qayta urinadi
            betas=[config.FALLBACK_BETA],
            fallbacks="default",
        )

    def run(self, user_text: str, on_event=print, learn: bool = True) -> str:
        """Bitta vazifani oxirigacha bajaradi va yakuniy javobni qaytaradi."""
        self.messages.append({"role": "user", "content": user_text})
        transcript = [f"USER: {user_text}"]
        used_tools = False
        final = ""

        for _ in range(config.MAX_STEPS):
            try:
                resp = self._call()
            except anthropic.RateLimitError:
                final = "API limitiga yetildi, birozdan keyin qayta urinib ko'ring."
                break
            except anthropic.APIStatusError as e:
                final = f"API xatosi ({e.status_code}): {e.message}"
                break
            except anthropic.APIConnectionError:
                final = "Internetga ulanib bo'lmadi."
                break

            self.messages.append({"role": "assistant", "content": resp.content})
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if text:
                transcript.append(f"AGENT: {text}")

            if resp.stop_reason == "refusal":
                final = "Agent bu so'rovni bajara olmaydi."
                break
            if resp.stop_reason == "pause_turn":
                continue  # server vositasi (qidiruv) davom etmoqda
            if resp.stop_reason != "tool_use":
                final = text or "(javob bo'sh)"
                if resp.stop_reason == "max_tokens":
                    final += "\n(Javob uzunlik chegarasiga yetib to'xtadi.)"
                break

            if text:
                on_event(f"💭 {text}")
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                used_tools = True
                on_event(f"🔧 {block.name}({_short(block.input)})")
                output, is_error = execute(block.name, block.input, self.human)
                if block.name == "generate_image" and not is_error:
                    on_event("🖼 " + output.split(": ", 1)[-1])
                transcript.append(f"TOOL {block.name}({_short(block.input)}) -> "
                                  f"{'XATO: ' if is_error else ''}{output[:1500]}")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})
        else:
            final = f"{config.MAX_STEPS} qadamdan keyin to'xtadim - vazifa juda uzun bo'lib ketdi."

        # O'zini mukammallashtirish: murakkab vazifadan keyin saboq chiqarish
        if learn and used_tools:
            transcript.append(f"YAKUN: {final}")
            for lesson in memory.reflect(self._complete_json, user_text, "\n".join(transcript)):
                on_event(f"🧠 Yangi saboq: {lesson}")
        return final


def _short(data: dict, limit: int = 120) -> str:
    s = json.dumps(data, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "..."


def make_agent(human: Human):
    """Sozlamaga qarab Claude yoki Gemini agentini yaratadi."""
    if config.provider() == "gemini":
        from .gemini_core import GeminiAgent
        return GeminiAgent(human)
    return Agent(human)
