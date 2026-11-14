"""Agent sozlamalari."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# O'rnatish papkasi: C:\AI Agent
INSTALL_DIR = Path(os.environ.get("AGENT_INSTALL_DIR",
                                  Path(os.environ.get("SystemDrive", "C:") + "\\") / "AI Agent"))
# Eski versiyalar ma'lumotni shu yerda saqlagan (o'rnatishda ko'chiriladi)
LEGACY_DIR = Path.home() / "aget_ai"


def is_installed() -> bool:
    """Dastur C:\\AI Agent papkasidan ishlayaptimi."""
    if not FROZEN:
        return False
    try:
        return Path(sys.executable).resolve().parent == INSTALL_DIR.resolve()
    except OSError:
        return False


if not FROZEN:
    BASE_DIR = Path(__file__).resolve().parent.parent  # dasturchi rejimi: repo papkasi
elif is_installed():
    BASE_DIR = INSTALL_DIR  # hamma narsa C:\AI Agent ichida
else:
    BASE_DIR = LEGACY_DIR  # hali o'rnatilmagan
DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", BASE_DIR / "data"))
WORKSPACE_DIR = Path(os.environ.get("AGENT_WORKSPACE", BASE_DIR / "workspace"))
PROJECTS_DIR = Path(os.environ.get("AGENT_PROJECTS", BASE_DIR / "projekt"))
CHATS_DIR = DATA_DIR / "chats"

MEMORY_FILE = DATA_DIR / "memory.json"
TASKS_FILE = DATA_DIR / "tasks.json"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"

# Qaysi AI xizmati: "gemini" (bepul tarif bor) yoki "claude".
# Ko'rsatilmasa: GEMINI_API_KEY o'rnatilgan bo'lsa gemini, aks holda claude.
def provider() -> str:
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    return os.environ.get("AGENT_PROVIDER", "gemini" if has_gemini_key else "claude").lower()


MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")  # Claude uchun
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # Gemini uchun
# Gemini qancha "o'ylasin": MINIMAL | LOW | MEDIUM | HIGH (pastrog'i tezroq javob beradi)
GEMINI_THINKING = os.environ.get("GEMINI_THINKING", "LOW").upper()
EFFORT = os.environ.get("AGENT_EFFORT", "high")  # low | medium | high | xhigh | max
MAX_TOKENS = 16000
MAX_STEPS = 30  # bitta vazifada eng ko'p nechta qadam
SHELL_TIMEOUT = 120  # sekund

# Rad etilganda boshqa modelda qayta urinish (server-side fallback)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

for d in (DATA_DIR, WORKSPACE_DIR, LOG_DIR, PROJECTS_DIR, CHATS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def log_error(msg: str) -> None:
    """Xatolarni data/logs/agent.log ga yozadi (muammoni aniqlash uchun)."""
    from datetime import datetime
    try:
        with (LOG_DIR / "agent.log").open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass
