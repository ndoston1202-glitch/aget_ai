"""Takrorlanuvchi vazifalar: saqlash va vaqti kelganini aniqlash."""
import threading
import uuid
from datetime import datetime, timedelta

from . import config
from .storage import load_json, save_json


def _load() -> list[dict]:
    return load_json(config.TASKS_FILE, [])


def add_task(prompt: str, every_minutes: int, allow_actions: bool = False) -> dict:
    task = {
        "id": uuid.uuid4().hex[:6],
        "prompt": prompt,
        "every_minutes": max(1, int(every_minutes)),
        "allow_actions": bool(allow_actions),
        "enabled": True,
        "next_run": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
        "last_result": None,
    }
    tasks = _load()
    tasks.append(task)
    save_json(config.TASKS_FILE, tasks)
    return task


def remove_task(task_id: str) -> bool:
    tasks = _load()
    new = [t for t in tasks if t["id"] != task_id]
    save_json(config.TASKS_FILE, new)
    return len(new) != len(tasks)


def set_enabled(task_id: str, enabled: bool) -> bool:
    tasks = _load()
    for t in tasks:
        if t["id"] == task_id:
            t["enabled"] = enabled
            save_json(config.TASKS_FILE, tasks)
            return True
    return False


def list_tasks() -> list[dict]:
    return _load()


def _mark_done(task_id: str, result: str) -> None:
    tasks = _load()
    now = datetime.now()
    for t in tasks:
        if t["id"] == task_id:
            t["last_run"] = now.isoformat(timespec="seconds")
            t["next_run"] = (now + timedelta(minutes=t["every_minutes"])).isoformat(timespec="seconds")
            t["last_result"] = result[:500]
    save_json(config.TASKS_FILE, tasks)


def due_tasks() -> list[dict]:
    now = datetime.now()
    return [t for t in _load()
            if t["enabled"] and datetime.fromisoformat(t["next_run"]) <= now]


class Scheduler(threading.Thread):
    """Fon oqimi: har daqiqada vaqti kelgan vazifalarni bajaradi."""

    def __init__(self, run_fn, interval: int = 30):
        super().__init__(daemon=True)
        self.run_fn = run_fn  # run_fn(task) -> str
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            for task in due_tasks():
                # Avval keyingi vaqtni belgilaymiz, shunda uzoq vazifa ikki marta ishga tushmaydi
                _mark_done(task["id"], "(bajarilmoqda...)")
                try:
                    result = self.run_fn(task)
                except Exception as e:
                    result = f"Xato: {e}"
                _mark_done(task["id"], result)
                log = config.LOG_DIR / f"task_{task['id']}.log"
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M} ===\n{result}\n")
            self._stop_event.wait(self.interval)
