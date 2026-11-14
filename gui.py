"""aget_ai - oynali dastur (terminalsiz). .exe shu fayldan yasaladi."""
import json
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from agent import config, memory, scheduler, updater
from agent.tools import AutoHuman, Human

KEY_URLS = {
    "gemini": "https://aistudio.google.com/apikey",
    "claude": "https://console.anthropic.com/settings/keys",
}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


# ---------- sozlamalar (API kaliti) ----------

def load_settings() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def apply_settings(s: dict) -> bool:
    """Sozlamalarni muhit o'zgaruvchilariga yozadi. Kalit bo'lsa True."""
    prov = s.get("provider", "gemini")
    key = s.get("api_key", "").strip()
    if not key:
        return False
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(env, None)
    os.environ["AGENT_PROVIDER"] = prov
    os.environ[KEY_ENV[prov]] = key
    return True


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, current: dict):
        super().__init__(master)
        self.title("Sozlamalar")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both")
        ttk.Label(frm, text="AI xizmati:").grid(row=0, column=0, sticky="w")
        self.prov = tk.StringVar(value=current.get("provider", "gemini"))
        ttk.Radiobutton(frm, text="Gemini (Google) — bepul", value="gemini",
                        variable=self.prov).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(frm, text="Claude (Anthropic) — pullik, kuchliroq", value="claude",
                        variable=self.prov).grid(row=2, column=0, sticky="w")

        ttk.Label(frm, text="API kaliti:").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.key = tk.StringVar(value=current.get("api_key", ""))
        ttk.Entry(frm, textvariable=self.key, width=60, show="•").grid(row=4, column=0, sticky="we")

        link = ttk.Label(frm, text="Kalitni qayerdan olaman? (bosing)", foreground="blue", cursor="hand2")
        link.grid(row=5, column=0, sticky="w", pady=(4, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(KEY_URLS[self.prov.get()]))

        ttk.Button(frm, text="Saqlash", command=self._save).grid(row=6, column=0, sticky="e", pady=(16, 0))
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        if not self.key.get().strip():
            messagebox.showwarning("Kalit kerak", "API kalitini kiriting.", parent=self)
            return
        self.result = {"provider": self.prov.get(), "api_key": self.key.get().strip()}
        config.SETTINGS_FILE.write_text(json.dumps(self.result), encoding="utf-8")
        self.destroy()


# ---------- agent <-> oyna aloqasi ----------

class GuiHuman(Human):
    """Agent fon oqimida ishlaydi; savol/ruxsat oynalari asosiy oqimda ochiladi."""

    def __init__(self, app: "App"):
        self.app = app

    def _ask_main(self, fn):
        done, box = threading.Event(), {}

        def task():
            box["v"] = fn()
            done.set()
        self.app.events.put(("call", task))
        done.wait()
        return box["v"]

    def approve(self, action: str) -> bool:
        return self._ask_main(lambda: messagebox.askyesno(
            "Agent ruxsat so'rayapti", f"{action}\n\nRuxsat berasizmi?", parent=self.app.root))

    def ask(self, question: str) -> str:
        ans = self._ask_main(lambda: simpledialog.askstring(
            "Agent savoli", question, parent=self.app.root))
        return ans or "(javob berilmadi)"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.agent = None
        self.busy = False
        root.title("aget_ai — shaxsiy AI agent")
        self.updating = False
        root.geometry("820x600")

        menu = tk.Menu(root)
        menu.add_command(label="Yangi suhbat", command=self.new_chat)
        menu.add_command(label="Vazifalar", command=self.show_tasks)
        menu.add_command(label="Xotira", command=self.show_memory)
        menu.add_command(label="Sozlamalar", command=self.open_settings)
        menu.add_command(label="Yangilash", command=lambda: self.check_update(manual=True))
        root.config(menu=menu)

        self.chat = scrolledtext.ScrolledText(root, wrap="word", state="disabled",
                                              font=("Segoe UI", 11), padx=10, pady=10)
        self.chat.pack(fill="both", expand=True)
        for tag, color in (("user", "#0b5394"), ("agent", "#000000"), ("event", "#777777"),
                           ("error", "#b00020"), ("task", "#6a1b9a")):
            self.chat.tag_config(tag, foreground=color)
        self.chat.tag_config("user", font=("Segoe UI", 11, "bold"))

        bottom = ttk.Frame(root, padding=8)
        bottom.pack(fill="x")
        self.entry = ttk.Entry(bottom, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send())
        self.send_btn = ttk.Button(bottom, text="Yuborish", command=self.send)
        self.send_btn.pack(side="left", padx=(8, 0))
        self.status = ttk.Label(root, text="", padding=(8, 0, 8, 6))
        self.status.pack(fill="x")

        root.after(100, self._poll)
        root.after(200, self._startup)

    # --- yordamchi ---
    def write(self, text: str, tag: str = "agent"):
        self.chat.config(state="normal")
        self.chat.insert("end", text + "\n\n", tag)
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "call":
                    data()
                elif kind == "done":
                    self.write(f"🤖 {data}", "agent")
                    self._set_busy(False)
                else:
                    self.write(data, kind)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.send_btn.config(state="disabled" if busy else "normal")
        self.status.config(text="⏳ Agent ishlayapti..." if busy else "")

    # --- ishga tushish ---
    def _startup(self):
        scheduler.Scheduler(self.run_scheduled).start()
        self._auto_update_loop()
        if not apply_settings(load_settings()):
            self.write("Xush kelibsiz! Avval API kalitini kiriting (Gemini bepul).", "event")
            if not self.open_settings():
                self.write("Kalit kiritilmadi. Yuqoridagi \"Sozlamalar\" menyusidan kiriting.", "error")
                return
        self._create_agent()
        self.write("Tayyor! Topshiriq yozing. Masalan: \"workspace papkasida eslatma.txt yarat\" "
                   "yoki \"har 60 daqiqada dollar kursini topib menga xabar ber\".", "event")
        self.entry.focus()

    def _create_agent(self):
        from agent.core import make_agent
        self.agent = make_agent(GuiHuman(self))
        self.root.title(f"aget_ai — shaxsiy AI agent ({config.provider()}) — v{updater.current_version()}")

    # --- yangilanish ---
    def _auto_update_loop(self):
        """Ishga tushganda va har 6 soatda yangi versiyani tekshiradi."""
        self.check_update(manual=False)
        self.root.after(6 * 3600 * 1000, self._auto_update_loop)

    def check_update(self, manual: bool):
        if self.updating:
            return
        if not updater.can_update():
            if manual:
                messagebox.showinfo("Yangilash", "Yangilash faqat Windows .exe versiyasida ishlaydi.",
                                    parent=self.root)
            return

        def work():
            try:
                info = updater.check()
            except Exception as e:
                if manual:
                    self.events.put(("call", lambda: messagebox.showerror(
                        "Yangilash", f"Tekshirib bo'lmadi: {e}", parent=self.root)))
                return
            if info:
                self.events.put(("call", lambda: self._offer_update(info)))
            elif manual:
                self.events.put(("call", lambda: messagebox.showinfo(
                    "Yangilash", f"Sizda eng so'nggi versiya (v{updater.current_version()}).",
                    parent=self.root)))
        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, info: dict):
        if self.updating:
            return
        mb = info["size"] / 1_048_576
        if not messagebox.askyesno(
                "Yangi versiya chiqdi",
                f"aget_ai ning yangi versiyasi bor (v{info['sha'][:7]}, {mb:.0f} MB).\n"
                "Hozir yangilansinmi? Dastur yopilib, o'zi qayta ochiladi.", parent=self.root):
            return
        if self.busy and not messagebox.askyesno(
                "Diqqat", "Agent hozir ishlayapti. Baribir yangilansinmi?", parent=self.root):
            return
        self.updating = True
        self.send_btn.config(state="disabled")

        def work():
            try:
                new = updater.download(info, on_progress=lambda pct: self.events.put(
                    ("call", lambda: self.status.config(text=f"⬇️ Yangilanish yuklanmoqda... {pct}%"))))
                self.events.put(("call", lambda: updater.install_and_restart(new)))
            except Exception as e:
                def fail():
                    self.updating = False
                    self._set_busy(self.busy)
                    messagebox.showerror("Yangilash", f"Yangilab bo'lmadi: {e}", parent=self.root)
                self.events.put(("call", fail))
        threading.Thread(target=work, daemon=True).start()

    def open_settings(self) -> bool:
        dlg = SettingsDialog(self.root, load_settings())
        self.root.wait_window(dlg)
        if dlg.result and apply_settings(dlg.result):
            if self.agent is not None:
                self._create_agent()
                self.write("Sozlamalar saqlandi, yangi suhbat boshlandi.", "event")
            return True
        return False

    # --- harakatlar ---
    def send(self):
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        if self.agent is None:
            self.open_settings() and self._create_agent()
            if self.agent is None:
                return
        self.entry.delete(0, "end")
        self.write(f"Siz: {text}", "user")
        self._set_busy(True)

        def work():
            try:
                ans = self.agent.run(text, on_event=lambda m: self.events.put(("event", m)))
            except Exception as e:
                ans = f"Kutilmagan xato: {e}"
            self.events.put(("done", ans))
        threading.Thread(target=work, daemon=True).start()

    def run_scheduled(self, task: dict) -> str:
        from agent.core import make_agent
        self.events.put(("task", f"⏰ Avtomatik vazifa: {task['prompt']}"))
        agent = make_agent(AutoHuman(task["allow_actions"]))
        result = agent.run(
            f"(Bu avtomatik takrorlanuvchi vazifa, foydalanuvchi hozir yonida emas.)\n{task['prompt']}",
            on_event=lambda m: self.events.put(("event", f"   [{task['id']}] {m}")))
        self.events.put(("task", f"✅ Vazifa [{task['id']}] natijasi: {result}"))
        return result

    def new_chat(self):
        if self.agent and not self.busy:
            self.agent.reset()
            self.chat.config(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.config(state="disabled")
            self.write("Yangi suhbat boshlandi.", "event")

    def show_memory(self):
        win = tk.Toplevel(self.root)
        win.title("Agent xotirasi")
        txt = scrolledtext.ScrolledText(win, wrap="word", width=80, height=20)
        txt.pack(fill="both", expand=True)
        txt.insert("end", memory.show())
        txt.config(state="disabled")

        def clear():
            if messagebox.askyesno("Tasdiqlang", "Butun xotira o'chirilsinmi?", parent=win):
                config.MEMORY_FILE.unlink(missing_ok=True)
                win.destroy()
        ttk.Button(win, text="Xotirani tozalash", command=clear).pack(pady=6)

    def show_tasks(self):
        win = tk.Toplevel(self.root)
        win.title("Takrorlanuvchi vazifalar")
        lb = tk.Listbox(win, width=100, height=12)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        tasks = scheduler.list_tasks()
        for t in tasks:
            lb.insert("end", f"[{t['id']}] har {t['every_minutes']} daq — {t['prompt']} "
                             f"| keyingi: {t['next_run']}")
        if not tasks:
            lb.insert("end", "Vazifalar yo'q. Agentga \"har ... daqiqada ...\" deb yozing.")

        def delete():
            sel = lb.curselection()
            if sel and tasks:
                scheduler.remove_task(tasks[sel[0]]["id"])
                win.destroy()
                self.show_tasks()
        ttk.Button(win, text="Tanlanganini o'chirish", command=delete).pack(pady=(0, 8))


def selftest() -> int:
    """CI uchun: barcha modullar .exe ichida yuklanishini tekshiradi."""
    import agent.core  # noqa: F401
    import agent.gemini_core  # noqa: F401
    from agent import updater
    return 0 if updater.BUILD_SHA != "dev" else 3


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    root = tk.Tk()
    App(root)
    root.mainloop()
