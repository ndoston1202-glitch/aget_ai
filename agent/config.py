"""Agent sozlamalari."""
import os
import sys
from pathlib import Path

# .exe holatida ma'lumotlar foydalanuvchi papkasida saqlanadi (C:\\Users\\<siz>\\aget_ai)
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path.home() / "aget_ai" if FROZEN else Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", BASE_DIR / "data"))
WORKSPACE_DIR = Path(os.environ.get("AGENT_WORKSPACE", BASE_DIR / "workspace"))

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
EFFORT = os.environ.get("AGENT_EFFORT", "high")  # low | medium | high | xhigh | max
MAX_TOKENS = 16000
MAX_STEPS = 30  # bitta vazifada eng ko'p nechta qadam
SHELL_TIMEOUT = 120  # sekund

# Rad etilganda boshqa modelda qayta urinish (server-side fallback)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

for d in (DATA_DIR, WORKSPACE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)
