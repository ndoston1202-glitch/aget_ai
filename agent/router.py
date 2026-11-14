"""Bir nechta AI orasida avtomatik almashish.

Birinchi kaliti bor AI ishlatiladi (tartib: Groq -> Gemini -> Claude). Uning limiti tugasa,
kaliti noto'g'ri bo'lsa yoki javob bermasa, suhbat keyingi AI'ga o'tadi va o'sha joydan davom etadi.
Limiti tugagan AI bir muddat chetga qo'yiladi, keyin yana sinab ko'riladi.
"""
import time

from . import config
from .tools import Human

NAMES = {"groq": "Groq", "gemini": "Gemini", "claude": "Claude"}
# Qancha vaqt chetga qo'yiladi (soniya)
COOLDOWN = {"limit": 15 * 60, "auth": 24 * 3600, "unavailable": 5 * 60}
REASON = {"limit": "limiti tugadi", "auth": "kaliti ishlamadi", "unavailable": "javob bermadi"}
MAX_PAIRS = 30  # boshqa AI'ga o'tganda uzatiladigan suhbat (savol-javob juftlari)


def _new_agent(name: str, human: Human):
    if name == "groq":
        from .groq_core import GroqAgent
        return GroqAgent(human)
    if name == "gemini":
        from .gemini_core import GeminiAgent
        return GeminiAgent(human)
    from .core import Agent
    return Agent(human)


class Router:
    def __init__(self, human: Human):
        self.human = human
        self.agents: dict = {}
        self.history: list[list[str]] = []  # [savol, javob] - AI'lar orasida umumiy
        self.blocked_until: dict[str, float] = {}
        self.active: str | None = None
        self.on_switch = lambda label: None
        self.last_error = None

    # --- holat ---
    @property
    def model(self) -> str:
        if not self.active:
            return "AI ulanmagan"
        agent = self.agents.get(self.active)
        model = getattr(agent, "model", None) or (config.MODEL if self.active == "claude" else "")
        return f"{NAMES[self.active]} · {model}" if model else NAMES[self.active]

    def _agent(self, name: str):
        if name not in self.agents:
            agent = _new_agent(name, self.human)
            if hasattr(agent, "on_switch"):
                agent.on_switch = lambda m: self.on_switch(self.model)
            agent.load_text_history(self.history[-MAX_PAIRS:])
            self.agents[name] = agent
        return self.agents[name]

    def _order(self) -> list[str]:
        """Hozir ishlatsa bo'ladigan AI'lar: avval faoli, keyin tartib bo'yicha."""
        now = time.time()
        ready = [p for p in config.configured_providers() if self.blocked_until.get(p, 0) <= now]
        if self.active in ready:
            ready.remove(self.active)
            ready.insert(0, self.active)
        return ready

    def reset(self):
        self.history = []
        for a in self.agents.values():
            a.reset()

    def export_state(self) -> dict:
        state = {"active": self.active, "history": self.history[-200:], "agents": {}}
        for name, agent in self.agents.items():
            try:
                state["agents"][name] = agent.export_state()
            except Exception as e:
                config.log_error(f"router export {name}: {e}")
        return state

    def load_state(self, data) -> None:
        if not isinstance(data, dict):
            return  # eski versiya formati
        self.history = data.get("history", [])
        self.active = data.get("active")
        for name, st in (data.get("agents") or {}).items():
            if name in config.configured_providers():
                try:
                    self._agent(name).load_state(st)
                except Exception as e:
                    config.log_error(f"router load {name}: {e}")

    # --- ishlash ---
    def run(self, user_text: str, on_event=print, learn: bool = True) -> str:
        self.last_error = None
        order = self._order()
        if not order:
            if config.configured_providers():
                return ("Barcha AI'larning limiti vaqtincha tugagan. Bir necha daqiqadan keyin qayta "
                        "urinib ko'ring yoki Sozlamalarda yana bitta AI kalitini qo'shing.")
            return "Hech qanday AI kaliti kiritilmagan. Sozlamalarda kamida bitta kalit kiriting."
        answer = ""
        for i, name in enumerate(order):
            agent = self._agent(name)
            if self.active != name:
                # Boshqa AI'dan o'tdik: suhbatni umumiy tarixdan yangilaymiz
                agent.load_text_history(self.history[-MAX_PAIRS:])
                self.active = name
                self.on_switch(self.model)
            answer = agent.run(user_text, on_event=on_event, learn=learn)
            err = getattr(agent, "last_error", None)
            if not err:
                self.history.append([user_text, answer])
                return answer
            # Bu AI ishlamadi - chetga qo'yib, keyingisiga o'tamiz
            agent.undo_turn()
            self.blocked_until[name] = time.time() + COOLDOWN.get(err, 300)
            config.log_error(f"router: {name} {err}: {answer}")
            nxt = next((p for p in order[i + 1:]), None)
            if nxt:
                on_event(f"ℹ️ {NAMES[name]} {REASON.get(err, 'ishlamadi')}, {NAMES[nxt]} ga o'tdim.")
            self.last_error = err
        return answer
