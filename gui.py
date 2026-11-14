"""aget_ai - oynali dastur (terminalsiz). .exe shu fayldan yasaladi."""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from agent import config, memory, scheduler, server, updater
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


def save_settings(updates: dict) -> dict:
    """Sozlamalarni mavjudlari ustiga qo'shib saqlaydi (telefon kodi va boshqalar yo'qolmaydi)."""
    s = load_settings()
    s.update(updates)
    config.SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")
    return s


def apply_settings(s: dict) -> bool:
    """Sozlamalarni muhit o'zgaruvchilariga yozadi. Kalit bo'lsa True."""
    if s.get("gemini_model"):
        config.GEMINI_MODEL = s["gemini_model"]  # "Tekshirish" topgan model
    if s.get("github_token"):
        os.environ["GITHUB_TOKEN"] = s["github_token"]
    else:
        os.environ.pop("GITHUB_TOKEN", None)
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

        ttk.Label(frm, text="GitHub tokeni (ixtiyoriy, loyihalarni GitHub'ga yuklash uchun):").grid(
            row=6, column=0, sticky="w", pady=(16, 0))
        self.gh = tk.StringVar(value=current.get("github_token", ""))
        ttk.Entry(frm, textvariable=self.gh, width=60, show="•").grid(row=7, column=0, sticky="we")
        gh_link = ttk.Label(frm, text="GitHub tokenini olish (bosing, 'repo' belgilangan bo'lsin)",
                            foreground="blue", cursor="hand2")
        gh_link.grid(row=8, column=0, sticky="w", pady=(4, 0))
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(
            "https://github.com/settings/tokens/new?scopes=repo&description=AI%20Agent"))

        ttk.Button(frm, text="Saqlash", command=self._save).grid(row=9, column=0, sticky="e", pady=(16, 0))
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        if not self.key.get().strip():
            messagebox.showwarning("Kalit kerak", "API kalitini kiriting.", parent=self)
            return
        self.result = save_settings({"provider": self.prov.get(), "api_key": self.key.get().strip(),
                                     "github_token": self.gh.get().strip()})
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
        root.title("AI Agent")
        self.display: list = []  # ekrandagi suhbat (saqlash uchun)
        self.updating = False
        self.phone_server = None
        root.geometry("820x600")

        menu = tk.Menu(root)
        menu.add_command(label="Yangi suhbat", command=self.new_chat)
        menu.add_command(label="Tarix", command=self.show_history)
        menu.add_command(label="Vazifalar", command=self.show_tasks)
        menu.add_command(label="Xotira", command=self.show_memory)
        menu.add_command(label="Telefon", command=self.show_phone)
        menu.add_command(label="Sozlamalar", command=self.open_settings)
        menu.add_command(label="Yangilash", command=lambda: self.check_update(manual=True))
        menu.add_command(label="Tekshirish", command=self.run_diagnose)
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
        self.voice_btn = ttk.Button(bottom, text="🎤 Ovozli fayl", command=self.send_voice_file)
        self.voice_btn.pack(side="left", padx=(8, 0))
        self.send_btn = ttk.Button(bottom, text="Yuborish", command=self.send)
        self.send_btn.pack(side="left", padx=(8, 0))
        status_row = ttk.Frame(root, padding=(8, 0, 8, 6))
        status_row.pack(fill="x")
        self.status = ttk.Label(status_row, text="")
        self.status.pack(side="left")
        self.stop_btn = ttk.Button(status_row, text="⏹ To'xtatish", command=self.cancel)
        self.run_id = 0
        self.busy_since = 0.0

        root.after(100, self._poll)
        root.after(200, self._startup)

    # --- yordamchi ---
    def write(self, text: str, tag: str = "agent", record: bool = True):
        if record:
            self.display.append([tag, text])
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
                    run_id, ans = data
                    if run_id == self.run_id:  # to'xtatilgan ishning javobi e'tiborga olinmaydi
                        self.write(f"🤖 {ans}", "agent")
                        self._set_busy(False)
                        self.save_chat()
                elif kind == "event" and data.startswith("🖼 "):
                    self.show_image(data[2:].strip())
                else:
                    self.write(data, kind)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def show_image(self, path: str, record: bool = True):
        if record:
            self.display.append(["image", path])
        try:
            img = tk.PhotoImage(file=path)
            factor = max(1, img.width() // 420 + (1 if img.width() % 420 else 0))
            if factor > 1:
                img = img.subsample(factor, factor)
            self.images = getattr(self, "images", []) + [img]  # rasm o'chib ketmasligi uchun
            self.chat.config(state="normal")
            self.chat.image_create("end", image=img)
            self.chat.insert("end", f"\n{path}\n\n", "event")
            self.chat.config(state="disabled")
            self.chat.see("end")
        except Exception:
            self.write(f"🖼 Rasm saqlandi: {path}", "event", record=False)

    def send_voice_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Ovozli xabarni tanlang", parent=self.root,
            filetypes=[("Ovozli fayllar", "*.mp3 *.m4a *.ogg *.oga *.opus *.wav *.aac *.flac *.amr *.webm"),
                       ("Barcha fayllar", "*.*")])
        if not path:
            return
        self._set_busy(True)
        self.status.config(text="🎤 Ovoz matnga aylantirilmoqda...")

        def work():
            from agent.media import transcribe
            try:
                text = transcribe(path)
            except Exception as e:
                def fail():
                    self._set_busy(False)
                    self.write(f"Ovozni matnga aylantirib bo'lmadi: {e}", "error")
                self.events.put(("call", fail))
                return

            def ok():
                self._set_busy(False)
                self.write("🎤 Ovozli xabar matnga aylantirildi", "event")
                self.entry.delete(0, "end")
                self.entry.insert(0, text)
                self.send()
            self.events.put(("call", ok))
        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool):
        was_busy = self.busy
        self.busy = busy
        self.send_btn.config(state="disabled" if busy else "normal")
        self.voice_btn.config(state="disabled" if busy else "normal")
        if busy:
            self.stop_btn.pack(side="left", padx=(12, 0))
            if not was_busy:
                self.busy_since = time.time()
                self._tick()
        else:
            self.stop_btn.pack_forget()
            self.status.config(text="")

    def _tick(self):
        """Agent ishlayotganda o'tgan vaqtni ko'rsatadi."""
        if not self.busy or self.updating:
            return
        secs = int(time.time() - self.busy_since)
        self.status.config(text=f"⏳ Agent ishlayapti... {secs} s")
        self.root.after(1000, self._tick)

    def cancel(self):
        """Javob kutishni to'xtatadi va yangi suhbat boshlaydi."""
        if not self.busy:
            return
        self.run_id += 1
        self._set_busy(False)
        self._create_agent()  # oxirgi saqlangan holatdan davom etadi
        self.write("⏹ To'xtatildi. Topshiriqni qayta yozishingiz mumkin.", "event")
        self.save_chat()

    # --- ishga tushish ---
    def _startup(self):
        if self._offer_install():
            return
        scheduler.Scheduler(self.run_scheduled).start()
        self._auto_update_loop()
        self._start_phone_server()
        if not apply_settings(load_settings()):
            self.write("Xush kelibsiz! Avval API kalitini kiriting (Gemini bepul).", "event")
            if not self.open_settings():
                self.write("Kalit kiritilmadi. Yuqoridagi \"Sozlamalar\" menyusidan kiriting.", "error")
                return
        self._create_agent()
        if self.display:
            self.write("— Oldingi suhbat davom etmoqda. Yangisini boshlash uchun \"Yangi suhbat\" ni bosing —",
                       "event", record=False)
        else:
            self.write("Tayyor! Topshiriq yozing. Masalan: \"eslatma.txt fayl yarat\" "
                       "yoki \"har 60 daqiqada dollar kursini topib menga xabar ber\".", "event")
        self.entry.focus()

    def _offer_install(self) -> bool:
        """Birinchi ishga tushishda C:\\AI Agent ga o'rnatishni taklif qiladi. O'rnatilsa True."""
        from agent import installer
        if not installer.can_install() or load_settings().get("install_declined"):
            return False
        if not messagebox.askyesno(
                "AI Agent ni o'rnatish",
                f"AI Agent kompyuteringizga o'rnatilsinmi?\n\n"
                f"• Dastur {config.INSTALL_DIR} papkasiga joylashadi\n"
                f"• Ish stoli va Пуск menyusida \"AI Agent\" yorlig'i paydo bo'ladi\n"
                f"• Suhbatlar, xotira va loyihalar shu papkada saqlanadi\n\n"
                f"\"Нет\" desangiz, dastur o'rnatilmasdan shu joydan ishlayveradi.", parent=self.root):
            save_settings({"install_declined": True})
            return False
        try:
            installer.install()
        except Exception as e:
            config.log_error(f"install: {type(e).__name__}: {e}")
            messagebox.showerror("O'rnatish", f"O'rnatib bo'lmadi: {e}", parent=self.root)
            return False
        messagebox.showinfo("O'rnatildi", f"AI Agent {config.INSTALL_DIR} ga o'rnatildi va hozir ochiladi.\n"
                            "Keyingi safar Ish stolidagi \"AI Agent\" yorlig'idan oching.", parent=self.root)
        os._exit(0)

    def _create_agent(self):
        """Agent yaratadi va saqlangan suhbatni (agar shu AI xizmatiniki bo'lsa) yuklaydi."""
        from agent.core import make_agent
        self.agent = make_agent(GuiHuman(self))
        saved = self._load_chat_file()
        if saved and saved.get("provider") == config.provider():
            self.agent.load_state(saved.get("state", []))
            if not self.display:
                for tag, text in saved.get("display", []):
                    if tag == "image":
                        self.show_image(text)
                    else:
                        self.write(text, tag)
        self.root.title(f"AI Agent ({config.provider()}) — v{updater.current_version()}")

    # --- aloqani tekshirish ---
    def run_diagnose(self):
        if self.busy:
            return
        if config.provider() != "gemini":
            messagebox.showinfo("Tekshirish", "Tekshirish hozircha faqat Gemini uchun.", parent=self.root)
            return
        self._set_busy(True)
        self.write("🔎 Google Gemini bilan aloqa tekshirilmoqda (1-3 daqiqa)...", "event")

        def work():
            from agent.gemini_core import diagnose
            try:
                best = diagnose(on_line=lambda m: self.events.put(("event", m)))
            except Exception as e:
                config.log_error(f"diagnose: {type(e).__name__}: {e}")
                best = None

            def finish():
                self._set_busy(False)
                if best:
                    save_settings({"gemini_model": best})
                    config.GEMINI_MODEL = best
                    if self.agent is not None and hasattr(self.agent, "model"):
                        self.agent.model = best
                    self.write(f"✅ Tayyor: endi \"{best}\" modeli ishlatiladi. Topshiriq yozishingiz mumkin.", "event")
                else:
                    self.write("❌ Ishlaydigan model topilmadi. Natijalarni Claude'ga yuboring.", "error")
            self.events.put(("call", finish))
        threading.Thread(target=work, daemon=True).start()

    # --- suhbat tarixi ---
    CURRENT_CHAT = property(lambda self: config.CHATS_DIR / "current.json")

    def _load_chat_file(self):
        try:
            return json.loads(self.CURRENT_CHAT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save_chat(self):
        """Joriy suhbatni diskka yozadi (har javobdan keyin)."""
        if self.agent is None:
            return
        try:
            data = {"provider": config.provider(), "updated": time.strftime("%Y-%m-%d %H:%M"),
                    "display": self.display[-400:], "state": self.agent.export_state()}
            tmp = self.CURRENT_CHAT.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.CURRENT_CHAT)
        except Exception as e:
            config.log_error(f"save_chat: {type(e).__name__}: {e}")

    def _archive_chat(self):
        if self.CURRENT_CHAT.exists() and any(t == "user" for t, _ in self.display):
            self.CURRENT_CHAT.replace(config.CHATS_DIR / f"suhbat_{time.strftime('%Y-%m-%d_%H-%M-%S')}.json")
        else:
            self.CURRENT_CHAT.unlink(missing_ok=True)

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("Suhbatlar tarixi")
        win.geometry("760x480")
        files = sorted(config.CHATS_DIR.glob("suhbat_*.json"), reverse=True)
        pane = ttk.PanedWindow(win, orient="horizontal")
        pane.pack(fill="both", expand=True)
        lb = tk.Listbox(pane, width=26)
        txt = scrolledtext.ScrolledText(pane, wrap="word", state="disabled")
        pane.add(lb, weight=1)
        pane.add(txt, weight=3)
        if not files:
            lb.insert("end", "Hali eski suhbatlar yo'q")
        for f in files:
            lb.insert("end", f.stem.removeprefix("suhbat_").replace("_", "  "))

        def show(_e=None):
            sel = lb.curselection()
            if not sel or not files:
                return
            try:
                data = json.loads(files[sel[0]].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            txt.config(state="normal")
            txt.delete("1.0", "end")
            for tag, text in data.get("display", []):
                txt.insert("end", (f"[rasm] {text}" if tag == "image" else text) + "\n\n")
            txt.config(state="disabled")
        lb.bind("<<ListboxSelect>>", show)
        ttk.Label(win, text=f"Suhbatlar shu yerda saqlanadi: {config.CHATS_DIR}", foreground="#666").pack(
            anchor="w", padx=8, pady=4)

    # --- telefon ---
    def _start_phone_server(self):
        from agent.core import make_agent
        try:
            self.phone_server = server.start(make_agent, on_log=lambda m: self.events.put(("task", m)))
        except OSError as e:
            self.write(f"Telefon serveri ishga tushmadi: {e}", "error")

    def show_phone(self):
        win = tk.Toplevel(self.root)
        win.title("Telefondan ulanish")
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=20)
        frm.pack()
        if not self.phone_server:
            ttk.Label(frm, text="Telefon serveri ishlamayapti. Dasturni qayta oching.").pack()
            return
        addr = f"{server.lan_ip()}:{server.PORT}"
        rows = [
            ("1. Telefonga aget_ai ilovasini (APK) o'rnating.", None),
            ("2. Telefon shu kompyuter bilan bitta Wi-Fi'ga ulangan bo'lsin.", None),
            ("3. Ilovaga quyidagilarni kiriting:", None),
            ("Manzil:", addr),
            ("Kod:", server.get_token()),
        ]
        for text, value in rows:
            row = ttk.Frame(frm)
            row.pack(anchor="w", pady=3)
            ttk.Label(row, text=text, font=("Segoe UI", 11)).pack(side="left")
            if value:
                e = ttk.Entry(row, font=("Segoe UI", 16, "bold"), width=len(value) + 2)
                e.insert(0, value)
                e.config(state="readonly")
                e.pack(side="left", padx=8)
        apk = "https://github.com/ndoston1202-glitch/aget_ai/releases/download/latest/aget_ai.apk"
        link = ttk.Label(frm, text="APK ni yuklab olish havolasi (bosing)", foreground="blue", cursor="hand2")
        link.pack(anchor="w", pady=(10, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(apk))
        ttk.Label(frm, text="Brauzerda ham ochiladi: http://" + addr, foreground="#666").pack(anchor="w", pady=(6, 0))
        ttk.Label(frm, text="Windows \"Брандмауэр\" ruxsat so'rasa — \"Разрешить доступ\" ni bosing.",
                  foreground="#666").pack(anchor="w")

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
            if self.agent is not None and not self.busy:
                self.save_chat()
                self._create_agent()
                self.write("Sozlamalar saqlandi.", "event", record=False)
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
        self.run_id += 1
        run_id, agent = self.run_id, self.agent

        def work():
            def on_event(m):
                if run_id == self.run_id:
                    self.events.put(("event", m))
            try:
                ans = agent.run(text, on_event=on_event)
            except Exception as e:
                config.log_error(f"gui run: {type(e).__name__}: {e}")
                ans = f"Kutilmagan xato: {type(e).__name__}: {e}"
            self.events.put(("done", (run_id, ans)))
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
            self.save_chat()
            self._archive_chat()
            self.agent.reset()
            self.display = []
            self.chat.config(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.config(state="disabled")
            self.write("Yangi suhbat boshlandi. Oldingisi \"Tarix\" menyusida saqlandi.", "event", record=False)

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
    if "--spawn-test" in sys.argv:  # CI: qayta ishga tushish sinovi
        updater.spawn_self_test(sys.argv[sys.argv.index("--spawn-test") + 1])
    if "--install-silent" in sys.argv:  # CI: o'rnatish sinovi
        from agent import installer
        installer.install(sys.argv[sys.argv.index("--install-silent") + 1:])
        sys.exit(0)
    if "--write-marker" in sys.argv:
        with open(sys.argv[sys.argv.index("--write-marker") + 1], "w") as f:
            f.write(f"{config.is_installed()}|{config.BASE_DIR}")
        sys.exit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
