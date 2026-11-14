"""Agentning asosiy sikli: o'ylaydi -> amal bajaradi -> natijani ko'radi -> davom etadi."""
import json
import anthropic

from . import config, memory
from .tools import SERVER_TOOLS, TOOL_DEFS, Human, execute, system_context

SYSTEM_PROMPT = """Sen foydalanuvchining shaxsiy ovozli yordamchisisan. Sen faqat suhbatlashmaysan - \
buyruqni tushunib, uni vositalar (tools) yordamida o'zing bajarasan.

Muloqot:
- Javoblaring ko'pincha ovoz chiqarib o'qiladi. Shuning uchun qisqa, jonli, tabiiy gapir; \
keraksiz ro'yxat, jadval va belgilardan qoch. Foydalanuvchi qaysi tilda gapirsa, o'sha tilda javob ber.
- Foydalanuvchini yaxshi tushunishga harakat qil: qiziqishlari (musiqa, mavzular, ish), odatlari va \
afzalliklarini sezsang, remember bilan saqla va keyingi safar hisobga ol.
- Oddiy suhbatda biror narsa noaniq bo'lsa (masalan "musiqa qo'y" desa, lekin qanday musiqa ekani \
noma'lum va xotirada ham yo'q bo'lsa), aniqlashtiruvchi savolni javobingning o'zida ber. ask_user ni \
faqat vazifa bajarilayotgan o'rtada javob kerak bo'lganda ishlat.
- Musiqa yoki video so'ralsa - play_youtube; sayt so'ralsa - open_url. Musiqani to'xtatish, keyingisi,
ovoz balandligi so'ralsa - media_control. Brauzer yoki boshqa dasturni yopish so'ralsa - close_program.
- Faqat vosita haqiqatan bajargan ishni "qildim" de. Qila olmasang, ochiq ayt.
- Tarjima so'ralsa, o'zing tarjima qil. Matnni o'qib berish so'ralsa - speak_text.

Ish tartibi:
1. Reja tuz va qadamma-qadam bajar. Har bir natijani tekshir; xato bo'lsa boshqa yo'l bilan urin.
2. Buyruq ishga tushirish va fayl yozish foydalanuvchi ruxsati bilan bo'ladi. Ruxsat berilmasa, \
boshqa yo'l taklif qil yoki to'xta.
3. Takrorlanuvchi ish so'ralsa ("har kuni", "har soatda") schedule_task bilan vazifa yarat.
4. Dasturlash loyihasi (kod, sayt, bot, skript) yaratishdan oldin ask_user bilan so'ra: \
"Loyihani GitHub'da repo ochib yuklaymi?". Har ikki holatda ham fayllarni project_folder papkasiga yoz. \
"Ha" desa, ishni tugatgach github_create_repo bilan yukla (GitHub tokeni kiritilmagan bo'lsa, \
Sozlamalardan kiritishni so'ra). "Yo'q" desa, loyiha papkada qoladi - uning yo'lini ayt.
5. Bajarmagan ishingni bajardim dema."""


class Agent:
    def __init__(self, human: Human, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic(timeout=180.0, max_retries=2)
        self.human = human
        self.messages: list = []

    def reset(self):
        self.messages = []

    def undo_turn(self):
        """Muvaffaqiyatsiz tugagan oxirgi navbatni olib tashlaydi."""
        del self.messages[getattr(self, "_turn_start", len(self.messages)):]

    def load_text_history(self, pairs: list) -> None:
        """Boshqa AI'dan o'tganda suhbatni oddiy matn ko'rinishida yuklaydi."""
        self.messages = []
        for user, answer in pairs:
            self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]

    MAX_SAVED = 80

    def export_state(self) -> list:
        """Suhbatni diskka saqlash uchun JSON ko'rinishiga o'tkazadi."""
        out = []
        for m in self.messages:
            content = m["content"]
            if not isinstance(content, str):
                content = [b.model_dump(mode="json", exclude_none=True) if hasattr(b, "model_dump") else b
                           for b in content]
            out.append({"role": m["role"], "content": content})
        if len(out) > self.MAX_SAVED:
            start = len(out) - self.MAX_SAVED
            while start < len(out) and not (out[start]["role"] == "user" and isinstance(out[start]["content"], str)):
                start += 1
            out = out[start:]
        return out

    def load_state(self, data: list) -> None:
        self.messages = list(data)

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
        self.last_error = None  # "limit" | "auth" | "unavailable" - boshqa AI'ga o'tish uchun
        self._turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        transcript = [f"USER: {user_text}"]
        used_tools = False
        final = ""

        for _ in range(config.MAX_STEPS):
            try:
                resp = self._call()
            except anthropic.RateLimitError:
                final = "Claude limitiga yetildi, birozdan keyin qayta urinib ko'ring."
                self.last_error = "limit"
                break
            except anthropic.APIStatusError as e:
                final = f"Claude xatosi ({e.status_code}): {e.message}"
                self.last_error = error_kind(e.status_code)
                if "credit balance" in str(e.message).lower():
                    self.last_error = "limit"
                break
            except anthropic.APIConnectionError:
                final = "Claude serveriga ulanib bo'lmadi."
                self.last_error = "unavailable"
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


def error_kind(code) -> str:
    """API xatosini turkumlaydi: limit (429), auth (kalit), unavailable (boshqa)."""
    if code == 429:
        return "limit"
    if code in (401, 403):
        return "auth"
    return "unavailable"


def make_agent(human: Human):
    """Agent yaratadi. Sukut bo'yicha - barcha ulangan AI'lar orasida avtomatik almashuvchi Router."""
    prov = config.provider()
    if prov == "gemini":
        from .gemini_core import GeminiAgent
        return GeminiAgent(human)
    if prov == "groq":
        from .groq_core import GroqAgent
        return GroqAgent(human)
    if prov == "claude":
        return Agent(human)
    from .router import Router
    return Router(human)
