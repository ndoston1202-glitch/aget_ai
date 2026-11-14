"""Agent sozlamalari."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", BASE_DIR / "data"))
WORKSPACE_DIR = Path(os.environ.get("AGENT_WORKSPACE", BASE_DIR / "workspace"))

MEMORY_FILE = DATA_DIR / "memory.json"
TASKS_FILE = DATA_DIR / "tasks.json"
LOG_DIR = DATA_DIR / "logs"

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("AGENT_EFFORT", "high")  # low | medium | high | xhigh | max
MAX_TOKENS = 16000
MAX_STEPS = 30  # bitta vazifada eng ko'p nechta qadam
SHELL_TIMEOUT = 120  # sekund

# Rad etilganda boshqa modelda qayta urinish (server-side fallback)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

for d in (DATA_DIR, WORKSPACE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)
