"""AI agent - ishga tushirish.

    python main.py           # suhbat + fon rejimida takrorlanuvchi vazifalar
    python main.py --daemon  # faqat takrorlanuvchi vazifalar (server uchun)
"""
import sys
import threading
import time

from agent import memory, scheduler
from agent.core import Agent
from agent.tools import AutoHuman, ConsoleHuman

HELP = """Buyruqlar:
  /tasks            takrorlanuvchi vazifalar ro'yxati
  /stop <id>        vazifani o'chirish
  /memory           agent xotirasi (saboqlar va afzalliklar)
  /forget <tur> <n> xotiradan o'chirish (tur: lessons yoki preferences)
  /new              yangi suhbat boshlash
  /exit             chiqish
Qolgan har qanday matn - agentga topshiriq."""

print_lock = threading.Lock()


def log(msg: str):
    with print_lock:
        print(msg, flush=True)


def run_scheduled(task: dict) -> str:
    agent = Agent(AutoHuman(task["allow_actions"]))
    log(f"\n⏰ Avtomatik vazifa [{task['id']}]: {task['prompt']}")
    result = agent.run(
        f"(Bu avtomatik takrorlanuvchi vazifa, foydalanuvchi hozir yonida emas.)\n{task['prompt']}",
        on_event=lambda m: log(f"   [{task['id']}] {m}"),
    )
    log(f"✅ [{task['id']}] natija: {result}\n")
    return result


def interactive():
    sched = scheduler.Scheduler(run_scheduled)
    sched.start()
    agent = Agent(ConsoleHuman())
    print("🤖 AI agent tayyor. Topshiriq yozing (/help - yordam).")

    while True:
        try:
            text = input("\nSiz: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        cmd, _, arg = text.partition(" ")
        if cmd == "/exit":
            break
        elif cmd == "/help":
            print(HELP)
        elif cmd == "/new":
            agent.reset()
            print("Yangi suhbat boshlandi.")
        elif cmd == "/memory":
            print(memory.show())
        elif cmd == "/forget":
            kind, _, idx = arg.partition(" ")
            print(memory.remove(kind, int(idx)) if idx.isdigit() else "Masalan: /forget lessons 0")
        elif cmd == "/tasks":
            tasks = scheduler.list_tasks()
            print("\n".join(f"{t['id']}: har {t['every_minutes']} daq - {t['prompt']}\n"
                            f"    keyingi: {t['next_run']} | oxirgi natija: {t['last_result']}"
                            for t in tasks) or "Vazifalar yo'q.")
        elif cmd == "/stop":
            print("O'chirildi." if scheduler.remove_task(arg) else "Topilmadi.")
        else:
            answer = agent.run(text, on_event=log)
            log(f"\nAgent: {answer}")

    sched.stop()
    print("Xayr!")


def daemon():
    sched = scheduler.Scheduler(run_scheduled)
    sched.start()
    log("🤖 Agent fon rejimida ishlayapti (Ctrl+C - to'xtatish).")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sched.stop()


if __name__ == "__main__":
    daemon() if "--daemon" in sys.argv else interactive()
