"""AI Agent - oynali dastur (terminalsiz). .exe shu fayldan yasaladi."""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from agent import config, memory, scheduler, server, updater
from agent.tools import AutoHuman, Human

# Ulanadigan AI'lar: (nomi, sarlavha, izoh, kalit olish sahifasi)
AI_LIST = [
    ("groq", "Groq", "bepul, juda tez — tavsiya", "https://console.groq.com/keys"),
    ("gemini", "Google Gemini", "bepul, rasm yaratadi", "https://aistudio.google.com/apikey"),
    ("claude", "Claude (Anthropic)", "pullik, eng aqlli", "https://console.anthropic.com/settings/keys"),
]
KEY_ENV = dict(config.PROVIDERS)

# Ranglar: (yorug' mavzu, qorong'i mavzu)
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_HOVER = ("#1d4ed8", "#2563eb")
BG = ("#f3f5f9", "#0f141c")
PANEL = ("#ffffff", "#171d27")
BUBBLE_AGENT = ("#ffffff", "#1f2733")
BORDER = ("#e1e6ef", "#2a3342")
TEXT = ("#16202e", "#e7ecf4")
MUTED = ("#6b7587", "#8d97aa")
DANGER = ("#dc2626", "#ef4444")
TASK = ("#7c3aed", "#a78bfa")
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

GREETING = ("Assalomu alaykum! Men sizning shaxsiy yordamchingizman. Bugun nima qilamiz? "
            "Musiqa qo'yaymi, biror matnni tarjima qilaymi yoki boshqa ish bormi?")


# ---------- sozlamalar ----------

def load_settings() -> dict:
    try:
        s = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    # Eski format: bitta "provider" + "api_key" -> har bir AI uchun alohida kalit
    if "keys" not in s and s.get("api_key"):
        s["keys"] = {s.get("provider", "gemini"): s["api_key"]}
    return s


def save_settings(updates: dict) -> dict:
    """Sozlamalarni mavjudlari ustiga qo'shib saqlaydi (telefon kodi va boshqalar yo'qolmaydi)."""
    s = load_settings()
    s.update(updates)
    config.SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")
    return s


def apply_settings(s: dict) -> bool:
    """Sozlamalarni muhit o'zgaruvchilariga yozadi. Kalit bo'lsa True."""
    if s.get("gemini_model"):
        config.GEMINI_MODEL = s["gemini_model"]
    if s.get("github_token"):
        os.environ["GITHUB_TOKEN"] = s["github_token"]
    else:
        os.environ.pop("GITHUB_TOKEN", None)
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["AGENT_PROVIDER"] = "auto"  # kaliti bor AI'lar orasida avtomatik almashish
    keys = s.get("keys") or {}
    for name, env in config.PROVIDERS:
        if keys.get(name, "").strip():
            os.environ[env] = keys[name].strip()
        else:
            os.environ.pop(env, None)
    return bool(config.configured_providers())


def link_label(master, text, url):
    lbl = ctk.CTkLabel(master, text=text, text_color=ACCENT, cursor="hand2", font=(FONT, 12, "underline"))
    lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
    return lbl


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, current: dict):
        super().__init__(master)
        self.title("Sozlamalar")
        self.geometry("540x640")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.after(100, self.grab_set)

        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=24, pady=20)
        ctk.CTkLabel(f, text="Sozlamalar", font=(FONT, 20, "bold")).pack(anchor="w")

        ctk.CTkLabel(f, text="Kamida bitta AI kalitini kiriting. Bir nechtasini kiritsangiz, birining limiti "
                             "tugaganda agent o'zi keyingisiga o'tadi (yuqoridagisi birinchi ishlatiladi).",
                     text_color=MUTED, font=(FONT, 12), wraplength=470, justify="left").pack(anchor="w", pady=(6, 4))
        keys = current.get("keys") or {}
        self.keys = {}
        for name, title, note, url in AI_LIST:
            head = ctk.CTkFrame(f, fg_color="transparent")
            head.pack(fill="x", pady=(10, 2))
            ctk.CTkLabel(head, text=title, font=(FONT, 13, "bold")).pack(side="left")
            ctk.CTkLabel(head, text=f"  {note}", text_color=MUTED, font=(FONT, 12)).pack(side="left")
            link_label(head, "kalit olish", url).pack(side="right")
            e = ctk.CTkEntry(f, show="•", height=34, placeholder_text="kalitni shu yerga qo'ying")
            if keys.get(name):
                e.insert(0, keys[name])
            e.pack(fill="x")
            self.keys[name] = e

        ctk.CTkLabel(f, text="GitHub tokeni (ixtiyoriy)", font=(FONT, 13, "bold")).pack(anchor="w", pady=(14, 4))
        self.gh = ctk.CTkEntry(f, show="•", height=36)
        self.gh.insert(0, current.get("github_token", ""))
        self.gh.pack(fill="x")
        link_label(f, "Token olish ('repo' belgilangan bo'lsin)",
                   "https://github.com/settings/tokens/new?scopes=repo&description=AI%20Agent").pack(anchor="w")

        ctk.CTkLabel(f, text="Qo'shimcha", font=(FONT, 13, "bold")).pack(anchor="w", pady=(14, 4))
        self.voice = ctk.BooleanVar(value=current.get("voice_reply", True))
        ctk.CTkSwitch(f, text="Javoblarni ovoz chiqarib o'qish", variable=self.voice).pack(anchor="w", pady=2)
        self.autostart = ctk.BooleanVar(value=current.get("autostart", True))
        ctk.CTkSwitch(f, text="Kompyuter yonganda avtomatik ishga tushish",
                      variable=self.autostart).pack(anchor="w", pady=2)

        ctk.CTkButton(f, text="Saqlash", height=38, command=self._save,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(fill="x", pady=(20, 0))
        self.bind("<Return>", lambda e: self._save())

    def _save(self):
        keys = {name: e.get().strip() for name, e in self.keys.items()}
        if not any(keys.values()):
            messagebox.showwarning("Kalit kerak", "Kamida bitta AI kalitini kiriting.", parent=self)
            return
        self.result = save_settings({"keys": keys, "github_token": self.gh.get().strip(),
                                     "voice_reply": bool(self.voice.get()),
                                     "autostart": bool(self.autostart.get())})
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
        if self.app.voice_on():
            from agent import voice
            voice.speak_async(question)
        ans = self._ask_main(lambda: simpledialog.askstring(
            "Agent savoli", question, parent=self.app.root))
        return ans or "(javob berilmadi)"


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.agent = None
        self.busy = False
        self.updating = False
        self.recording = False
        self.phone_server = None
        self.display: list = []  # ekrandagi suhbat (saqlash uchun)
        self.bubbles: list = []  # (label, kind) - kenglik o'zgarganda qayta o'rash uchun
        self.images: list = []
        self.run_id = 0
        self.busy_since = 0.0

        root.title("AI Agent")
        root.geometry("980x720")
        root.minsize(460, 520)
        root.configure(fg_color=BG)

        # --- yuqori panel ---
        top = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=0, height=64)
        top.pack(fill="x")
        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=18, pady=10)
        self.dot = ctk.CTkLabel(brand, text="●", text_color="#22c55e", font=(FONT, 16))
        self.dot.pack(side="left", padx=(0, 8))
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        ctk.CTkLabel(names, text="AI Agent", font=(FONT, 18, "bold"), text_color=TEXT).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(names, text="shaxsiy yordamchi", font=(FONT, 11), text_color=MUTED)
        self.subtitle.pack(anchor="w")

        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.pack(side="right", padx=12)
        for text, cmd in (("＋ Yangi suhbat", self.new_chat), ("Tarix", self.show_history),
                          ("Sozlamalar", self.open_settings), ("⋯ Yana", self.show_more)):
            b = ctk.CTkButton(btns, text=text, command=cmd, height=34, width=110,
                              fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                              border_width=1, border_color=BORDER, font=(FONT, 13))
            b.pack(side="left", padx=4)
        self.more_btn = b
        self.more_menu = tk.Menu(root, tearoff=0)
        for label, cmd in (("Vazifalar", self.show_tasks), ("Xotira", self.show_memory),
                           ("Telefondan ulanish", self.show_phone), ("Ovozli fayl yuborish", self.send_voice_file),
                           ("Aloqani tekshirish", self.run_diagnose),
                           ("Yangilanishni tekshirish", lambda: self.check_update(manual=True))):
            self.more_menu.add_command(label=label, command=cmd)

        # --- suhbat ---
        self.chat = ctk.CTkScrollableFrame(root, fg_color=BG, corner_radius=0)
        self.chat.pack(fill="both", expand=True)
        self.chat.grid_columnconfigure(0, weight=1)
        self.chat.bind("<Configure>", lambda e: self._rewrap())
        self.row = 0

        # --- pastki panel ---
        bottom = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=0)
        bottom.pack(fill="x")
        bar = ctk.CTkFrame(bottom, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(12, 4))
        self.mic_btn = ctk.CTkButton(bar, text="🎙", width=48, height=48, corner_radius=24,
                                     font=(FONT, 20), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                     command=self.toggle_mic)
        self.mic_btn.pack(side="left")
        self.entry = ctk.CTkEntry(bar, height=48, corner_radius=24, font=(FONT, 14),
                                  placeholder_text="Xabar yozing yoki 🎙 ni bosib gapiring...",
                                  border_color=BORDER)
        self.entry.pack(side="left", fill="x", expand=True, padx=10)
        self.entry.bind("<Return>", lambda e: self.send())
        self.send_btn = ctk.CTkButton(bar, text="➤", width=48, height=48, corner_radius=24,
                                      font=(FONT, 18), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                      command=self.send)
        self.send_btn.pack(side="left")

        status_row = ctk.CTkFrame(bottom, fg_color="transparent")
        status_row.pack(fill="x", padx=20, pady=(0, 10))
        self.status = ctk.CTkLabel(status_row, text="", text_color=MUTED, font=(FONT, 12))
        self.status.pack(side="left")
        self.stop_btn = ctk.CTkButton(status_row, text="⏹ To'xtatish", width=100, height=26,
                                      fg_color="transparent", border_width=1, border_color=BORDER,
                                      text_color=TEXT, hover_color=BORDER, command=self.cancel)
        self.voice_var = ctk.BooleanVar(value=load_settings().get("voice_reply", True))
        ctk.CTkSwitch(status_row, text="🔊 Ovozli javob", variable=self.voice_var, font=(FONT, 12),
                      command=self._voice_toggled).pack(side="right")
        ctk.CTkButton(status_row, text="🔇 Jim", width=60, height=26, fg_color="transparent",
                      border_width=1, border_color=BORDER, text_color=TEXT, hover_color=BORDER,
                      command=self.stop_speaking).pack(side="right", padx=8)

        root.bind("<F2>", lambda e: self.toggle_mic())
        root.bind("<Escape>", lambda e: self.stop_speaking())
        root.after(100, self._poll)
        root.after(200, self._startup)

    # ---------- chat pufakchalari ----------
    def _wrap_width(self) -> int:
        return max(260, int(self.chat.winfo_width() * 0.68))

    def _rewrap(self):
        w = self._wrap_width()
        for lbl, kind in self.bubbles:
            try:
                lbl.configure(wraplength=w if kind in ("user", "agent", "error") else w + 120)
            except tk.TclError:
                pass

    def _scroll_end(self):
        """Chatni oxiriga aylantiradi (o'lcham hisoblangach - bir necha marta, ishonch uchun)."""
        def go():
            try:
                self.chat.update_idletasks()
                canvas = self.chat._parent_canvas
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.yview_moveto(1.0)
            except tk.TclError:
                pass
        for ms in (10, 120, 400):
            self.root.after(ms, go)

    def _copy_menu(self, widget, text):
        def popup(e):
            m = tk.Menu(self.root, tearoff=0)
            m.add_command(label="Nusxa olish", command=lambda: (self.root.clipboard_clear(),
                                                               self.root.clipboard_append(text)))
            m.add_command(label="🔈 O'qib berish", command=lambda: self.speak(text))
            m.tk_popup(e.x_root, e.y_root)
        widget.bind("<Button-3>", popup)

    def write(self, text: str, tag: str = "agent", record: bool = True):
        if record:
            self.display.append([tag, text])
        if tag == "user":
            text = text.removeprefix("Siz: ")
        if tag == "agent":
            text = text.removeprefix("🤖 ")
        holder = ctk.CTkFrame(self.chat, fg_color="transparent")
        holder.grid(row=self.row, column=0, sticky="ew", padx=16, pady=5)
        self.row += 1
        w = self._wrap_width()
        if tag == "user":
            lbl = ctk.CTkLabel(holder, text=text, fg_color=ACCENT, text_color="#ffffff", corner_radius=16,
                               font=(FONT, 14), justify="left", wraplength=w, padx=14, pady=10)
            lbl.pack(side="right")
        elif tag in ("agent", "error"):
            col = ctk.CTkFrame(holder, fg_color="transparent")
            col.pack(side="left")
            lbl = ctk.CTkLabel(col, text=text, fg_color=BUBBLE_AGENT, corner_radius=16,
                               text_color=DANGER if tag == "error" else TEXT,
                               font=(FONT, 14), justify="left", wraplength=w, padx=14, pady=10)
            lbl.pack(anchor="w")
            if tag == "agent":
                ctk.CTkButton(col, text="🔈 O'qib berish", width=10, height=22, font=(FONT, 11),
                              fg_color="transparent", hover_color=BORDER, text_color=MUTED,
                              command=lambda t=text: self.speak(t)).pack(anchor="w", padx=6)
        else:  # event / task
            lbl = ctk.CTkLabel(holder, text=text, text_color=TASK if tag == "task" else MUTED,
                               font=(FONT, 12), justify="left", wraplength=w + 120)
            lbl.pack(side="left", padx=6)
        self._copy_menu(lbl, text)
        self.bubbles.append((lbl, tag))
        self._scroll_end()

    def show_image(self, path: str, record: bool = True):
        if record:
            self.display.append(["image", path])
        try:
            from PIL import Image
            img = Image.open(path)
            scale = min(1.0, 380 / max(img.width, 1))
            cimg = ctk.CTkImage(light_image=img, dark_image=img,
                                size=(int(img.width * scale), int(img.height * scale)))
            self.images.append(cimg)
            holder = ctk.CTkFrame(self.chat, fg_color="transparent")
            holder.grid(row=self.row, column=0, sticky="ew", padx=16, pady=5)
            self.row += 1
            lbl = ctk.CTkLabel(holder, image=cimg, text="", cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e: os.startfile(path) if hasattr(os, "startfile") else None)
            self._scroll_end()
        except Exception:
            self.write(f"🖼 Rasm saqlandi: {path}", "event", record=False)

    def clear_chat(self):
        for child in self.chat.winfo_children():
            child.destroy()
        self.bubbles.clear()
        self.images.clear()
        self.row = 0

    # ---------- voqealar navbati ----------
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
                        from agent import voice
                        if self.voice_on() and not voice.spoke_during_run:
                            self.speak(ans)
                elif kind == "event" and data.startswith("🖼 "):
                    self.show_image(data[2:].strip())
                else:
                    self.write(data, kind)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy: bool):
        was_busy = self.busy
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.send_btn.configure(state=state)
        if not self.recording:
            self.mic_btn.configure(state=state)
        if busy:
            self.stop_btn.pack(side="left", padx=(12, 0))
            self.dot.configure(text_color="#f59e0b")
            if not was_busy:
                self.busy_since = time.time()
                self._tick()
        else:
            self.stop_btn.pack_forget()
            self.dot.configure(text_color="#22c55e")
            self.status.configure(text="")

    def _tick(self):
        if not self.busy or self.updating:
            return
        secs = int(time.time() - self.busy_since)
        self.status.configure(text=f"⏳ O'ylayapman... {secs} s")
        self.root.after(1000, self._tick)

    def cancel(self):
        if not self.busy:
            return
        self.run_id += 1
        self._set_busy(False)
        self._create_agent()
        self.write("⏹ To'xtatildi. Topshiriqni qayta yozishingiz mumkin.", "event")
        self.save_chat()

    # ---------- ovoz ----------
    def voice_on(self) -> bool:
        return bool(self.voice_var.get())

    def _voice_toggled(self):
        save_settings({"voice_reply": self.voice_on()})
        if not self.voice_on():
            self.stop_speaking()

    def speak(self, text: str):
        from agent import voice
        voice.speak_async(text, on_error=lambda e: self.events.put(
            ("event", "🔇 Ovoz chiqarib bo'lmadi (batafsil: data/logs/agent.log)")))

    def stop_speaking(self):
        from agent import voice
        voice.stop_speaking()

    def toggle_mic(self):
        from agent import voice
        if self.recording:
            self.recording = False
            self.mic_btn.configure(text="🎙", fg_color=ACCENT, hover_color=ACCENT_HOVER)
            try:
                path = voice.stop_recording()
            except Exception as e:
                self.write(str(e), "error", record=False)
                self._set_busy(False)
                return
            self._transcribe_and_send(str(path))
            return
        if self.busy:
            return
        try:
            voice.start_recording()
        except Exception as e:
            self.write(f"Mikrofonni yoqib bo'lmadi: {e}", "error", record=False)
            return
        self.recording = True
        self.mic_btn.configure(text="⏹", fg_color=DANGER, hover_color=DANGER)
        self.send_btn.configure(state="disabled")
        self.status.configure(text="🔴 Tinglayapman... gapirib bo'lgach ⏹ ni (yoki F2) bosing")

    def _transcribe_and_send(self, path: str):
        self._set_busy(True)
        self.status.configure(text="🎙 Gapingiz matnga aylantirilmoqda...")

        def work():
            from agent.media import transcribe
            try:
                text = transcribe(path)
            except Exception as e:
                config.log_error(f"transcribe: {type(e).__name__}: {e}")

                def fail():
                    self._set_busy(False)
                    self.write(f"Gapingizni tushunib bo'lmadi: {e}", "error", record=False)
                self.events.put(("call", fail))
                return

            def ok():
                self._set_busy(False)
                self.entry.delete(0, "end")
                self.entry.insert(0, text)
                self.send()
            self.events.put(("call", ok))
        threading.Thread(target=work, daemon=True).start()

    def send_voice_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Ovozli xabarni tanlang", parent=self.root,
            filetypes=[("Ovozli fayllar", "*.mp3 *.m4a *.ogg *.oga *.opus *.wav *.aac *.flac *.amr *.webm"),
                       ("Barcha fayllar", "*.*")])
        if path:
            self._transcribe_and_send(path)

    # ---------- ishga tushish ----------
    def _startup(self):
        if self._offer_install():
            return
        self._ensure_autostart()
        scheduler.Scheduler(self.run_scheduled).start()
        self._auto_update_loop()
        self._start_phone_server()
        if not apply_settings(load_settings()):
            self.write("Xush kelibsiz! Boshlash uchun kamida bitta AI kalitini kiriting (Groq bepul va tez).", "event")
            if not self.open_settings():
                self.write("Kalit kiritilmadi. Yuqoridagi \"Sozlamalar\" tugmasidan kiriting.", "error")
                return
        self._create_agent()
        if self.display:
            self.write("— Oldingi suhbat davom etmoqda —", "event", record=False)
            greet = "Xush kelibsiz! Davom etamizmi yoki yangi ish bormi?"
        else:
            greet = GREETING
        self.write(greet, "agent", record=False)
        if self.voice_on():
            self.speak(greet)
        self.entry.focus()

    def _ensure_autostart(self):
        """O'rnatilgan dastur uchun avtomatik ishga tushish yorlig'ini sozlamaga moslaydi."""
        if not config.is_installed():
            return
        from agent import installer
        want = load_settings().get("autostart", True)
        try:
            if want and not installer.startup_link().exists():
                installer.set_autostart(True)
            elif not want and installer.startup_link().exists():
                installer.set_autostart(False)
        except Exception as e:
            config.log_error(f"autostart: {type(e).__name__}: {e}")

    def _offer_install(self) -> bool:
        """Birinchi ishga tushishda C:\\AI Agent ga o'rnatishni taklif qiladi."""
        from agent import installer
        if not installer.can_install() or load_settings().get("install_declined"):
            return False
        if not messagebox.askyesno(
                "AI Agent ni o'rnatish",
                f"AI Agent kompyuteringizga o'rnatilsinmi?\n\n"
                f"• Dastur {config.INSTALL_DIR} papkasiga joylashadi\n"
                f"• Ish stoli va Пуск menyusida \"AI Agent\" yorlig'i paydo bo'ladi\n"
                f"• Kompyuter yonganda o'zi ishga tushadi\n"
                f"• Suhbatlar, xotira va loyihalar shu papkada saqlanadi", parent=self.root):
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
        """Agent yaratadi va saqlangan suhbatni (shu AI xizmatiniki bo'lsa) yuklaydi."""
        from agent.core import make_agent
        self.agent = make_agent(GuiHuman(self))
        if hasattr(self.agent, "on_switch"):
            self.agent.on_switch = lambda m: self.events.put(("call", lambda: self._model_switched(m)))
        saved = self._load_chat_file()
        if saved:
            if saved.get("provider") == config.provider():
                self.agent.load_state(saved.get("state", []))
            if not self.display:
                for tag, text in saved.get("display", []):
                    if tag == "image":
                        self.show_image(text)
                    else:
                        self.write(text, tag)
        self._update_subtitle()

    def _update_subtitle(self):
        model = getattr(self.agent, "model", config.MODEL)
        self.subtitle.configure(text=f"{model} · v{updater.current_version()}")
        self.root.title(f"AI Agent — v{updater.current_version()}")

    def _model_switched(self, model: str):
        self._update_subtitle()

    # ---------- suhbat tarixi ----------
    @property
    def current_chat_file(self):
        return config.CHATS_DIR / "current.json"

    def _load_chat_file(self):
        try:
            return json.loads(self.current_chat_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save_chat(self):
        if self.agent is None:
            return
        try:
            data = {"provider": config.provider(), "updated": time.strftime("%Y-%m-%d %H:%M"),
                    "display": self.display[-400:], "state": self.agent.export_state()}
            tmp = self.current_chat_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.current_chat_file)
        except Exception as e:
            config.log_error(f"save_chat: {type(e).__name__}: {e}")

    def _archive_chat(self):
        if self.current_chat_file.exists() and any(t == "user" for t, _ in self.display):
            self.current_chat_file.replace(config.CHATS_DIR / f"suhbat_{time.strftime('%Y-%m-%d_%H-%M-%S')}.json")
        else:
            self.current_chat_file.unlink(missing_ok=True)

    def new_chat(self):
        if self.agent and not self.busy:
            self.save_chat()
            self._archive_chat()
            self.agent.reset()
            self.display = []
            self.clear_chat()
            self.write("Yangi suhbat. Oldingisi \"Tarix\" bo'limida saqlandi.", "event", record=False)
            self.write("Nima qilamiz?", "agent", record=False)

    def _toplevel(self, title, size):
        win = ctk.CTkToplevel(self.root)
        win.title(title)
        win.geometry(size)
        win.transient(self.root)
        return win

    def show_history(self):
        win = self._toplevel("Suhbatlar tarixi", "820x520")
        files = sorted(config.CHATS_DIR.glob("suhbat_*.json"), reverse=True)
        side = ctk.CTkScrollableFrame(win, width=200)
        side.pack(side="left", fill="y", padx=(12, 6), pady=12)
        txt = ctk.CTkTextbox(win, wrap="word", font=(FONT, 13))
        txt.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        txt.insert("end", "Chap tomondan suhbatni tanlang." if files else "Hali eski suhbatlar yo'q.")
        txt.configure(state="disabled")

        def show(f):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for tag, text in data.get("display", []):
                prefix = {"user": "Siz: ", "image": "[rasm] "}.get(tag, "")
                txt.insert("end", prefix + text.removeprefix("Siz: ") + "\n\n")
            txt.configure(state="disabled")
        for f in files:
            ctk.CTkButton(side, text=f.stem.removeprefix("suhbat_").replace("_", "  "), anchor="w",
                          fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                          command=lambda f=f: show(f)).pack(fill="x", pady=1)

    def show_more(self):
        """"Yana" tugmasi ostida menyu ochadi."""
        b = self.more_btn
        try:
            self.more_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            self.more_menu.grab_release()

    # ---------- aloqani tekshirish ----------
    def run_diagnose(self):
        """Kaliti kiritilgan har bir AI bilan aloqani tekshiradi."""
        if self.busy:
            return
        provs = config.configured_providers()
        if not provs:
            messagebox.showinfo("Tekshirish", "Avval Sozlamalarda AI kalitini kiriting.", parent=self.root)
            return
        self._set_busy(True)
        self.write("🔎 AI'lar bilan aloqa tekshirilmoqda (1-3 daqiqa)...", "event", record=False)

        def work():
            say = lambda m: self.events.put(("event", m))
            ok = []
            for p in provs:
                say(f"— {p.capitalize()} —")
                try:
                    if p == "groq":
                        from agent.groq_core import diagnose
                    elif p == "gemini":
                        from agent.gemini_core import diagnose
                    else:
                        say("Claude pullik, tekshiruvsiz qoldirildi (kalit kiritilgan).")
                        ok.append(p)
                        continue
                    best = diagnose(on_line=say)
                    if best:
                        ok.append(p)
                        if p == "gemini":
                            save_settings({"gemini_model": best})
                            config.GEMINI_MODEL = best
                except Exception as e:
                    config.log_error(f"diagnose {p}: {type(e).__name__}: {e}")
                    say(f"❌ {p}: {e}")

            def finish():
                self._set_busy(False)
                if ok:
                    self.write(f"✅ Ishlayotgan AI'lar: {', '.join(x.capitalize() for x in ok)}.", "event", record=False)
                else:
                    self.write("❌ Hech bir AI ishlamadi. Natijani Claude'ga yuboring.", "error", record=False)
            self.events.put(("call", finish))
        threading.Thread(target=work, daemon=True).start()

    # ---------- telefon ----------
    def _start_phone_server(self):
        from agent.core import make_agent
        try:
            self.phone_server = server.start(make_agent, on_log=lambda m: self.events.put(("task", m)))
        except OSError as e:
            config.log_error(f"phone server: {e}")

    def show_phone(self):
        win = self._toplevel("Telefondan ulanish", "520x400")
        f = ctk.CTkFrame(win, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=24, pady=20)
        if not self.phone_server:
            ctk.CTkLabel(f, text="Telefon serveri ishlamayapti. Dasturni qayta oching.").pack()
            return
        addr = f"{server.lan_ip()}:{server.PORT}"
        ctk.CTkLabel(f, text="Telefondan ulanish", font=(FONT, 20, "bold")).pack(anchor="w")
        ctk.CTkLabel(f, text="Telefonga AI Agent ilovasini o'rnating va bitta Wi-Fi'ga ulaning.\n"
                             "Keyin ilovaga quyidagilarni kiriting:", justify="left",
                     text_color=MUTED).pack(anchor="w", pady=(6, 12))
        for label, value in (("Manzil", addr), ("Kod", server.get_token())):
            ctk.CTkLabel(f, text=label, font=(FONT, 13, "bold")).pack(anchor="w")
            e = ctk.CTkEntry(f, font=(FONT, 20, "bold"), height=44)
            e.insert(0, value)
            e.configure(state="readonly")
            e.pack(fill="x", pady=(2, 10))
        link_label(f, "APK ni yuklab olish",
                   "https://github.com/ndoston1202-glitch/aget_ai/releases/download/latest/aget_ai.apk").pack(anchor="w")
        ctk.CTkLabel(f, text="Windows \"Брандмауэр\" so'rasa - \"Разрешить доступ\" ni bosing.",
                     text_color=MUTED, font=(FONT, 12)).pack(anchor="w", pady=(6, 0))

    # ---------- yangilanish ----------
    def _auto_update_loop(self):
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
                f"AI Agent ning yangi versiyasi bor (v{info['sha'][:7]}, {mb:.0f} MB).\n"
                "Hozir yangilansinmi? Dastur yopilib, o'zi qayta ochiladi.", parent=self.root):
            return
        if self.busy and not messagebox.askyesno(
                "Diqqat", "Agent hozir ishlayapti. Baribir yangilansinmi?", parent=self.root):
            return
        self.updating = True
        self.send_btn.configure(state="disabled")
        self.save_chat()

        def work():
            try:
                new = updater.download(info, on_progress=lambda pct: self.events.put(
                    ("call", lambda: self.status.configure(text=f"⬇️ Yangilanish yuklanmoqda... {pct}%"))))
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
            self.voice_var.set(dlg.result.get("voice_reply", True))
            self._ensure_autostart()
            if self.agent is not None and not self.busy:
                self.save_chat()
                self._create_agent()
                self.write("Sozlamalar saqlandi.", "event", record=False)
            return True
        return False

    # ---------- harakatlar ----------
    def send(self):
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        if self.agent is None:
            if self.open_settings() and self.agent is None:
                self._create_agent()
            if self.agent is None:
                return
        self.stop_speaking()
        self.entry.delete(0, "end")
        self.write(f"Siz: {text}", "user")
        self._set_busy(True)
        self.run_id += 1
        run_id, agent = self.run_id, self.agent
        from agent import voice
        voice.spoke_during_run = False

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

    def show_memory(self):
        win = self._toplevel("Agent xotirasi", "640x460")
        txt = ctk.CTkTextbox(win, wrap="word", font=(FONT, 13))
        txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt.insert("end", memory.show())
        txt.configure(state="disabled")

        def clear():
            if messagebox.askyesno("Tasdiqlang", "Butun xotira o'chirilsinmi?", parent=win):
                config.MEMORY_FILE.unlink(missing_ok=True)
                win.destroy()
        ctk.CTkButton(win, text="Xotirani tozalash", fg_color=DANGER, hover_color=DANGER,
                      command=clear).pack(pady=(0, 12))

    def show_tasks(self):
        win = self._toplevel("Takrorlanuvchi vazifalar", "720x420")
        box = ctk.CTkScrollableFrame(win)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        tasks = scheduler.list_tasks()
        if not tasks:
            ctk.CTkLabel(box, text="Vazifalar yo'q. Agentga \"har ... daqiqada ...\" deb ayting.",
                         text_color=MUTED).pack(pady=20)
        for t in tasks:
            row = ctk.CTkFrame(box, fg_color=PANEL, corner_radius=10)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"Har {t['every_minutes']} daqiqada: {t['prompt']}\nKeyingi: {t['next_run']}",
                         justify="left", wraplength=520).pack(side="left", padx=12, pady=8)

            def delete(tid=t["id"]):
                scheduler.remove_task(tid)
                win.destroy()
                self.show_tasks()
            ctk.CTkButton(row, text="O'chirish", width=80, fg_color=DANGER, hover_color=DANGER,
                          command=delete).pack(side="right", padx=10)


def selftest() -> int:
    """CI uchun: barcha modullar .exe ichida yuklanishini tekshiradi."""
    import agent.core  # noqa: F401
    import agent.gemini_core  # noqa: F401
    import agent.voice  # noqa: F401
    import PIL.ImageTk  # noqa: F401
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
    if "--apply-update-test" in sys.argv:  # CI: yangilanishni o'rnatish sinovi
        i = sys.argv.index("--apply-update-test")
        from pathlib import Path
        updater.install_and_restart(Path(sys.argv[i + 1]), ["--write-marker", sys.argv[i + 2]])
    if "--tts-test" in sys.argv:  # CI: Windows ovozi ishlashini tekshirish
        import shutil
        from agent import voice
        shutil.copy(voice._windows_tts("Salom! Bu ovoz sinovi."), sys.argv[sys.argv.index("--tts-test") + 1])
        sys.exit(0)
    if "--write-marker" in sys.argv:
        with open(sys.argv[sys.argv.index("--write-marker") + 1], "w") as f:
            f.write(f"{config.is_installed()}|{config.BASE_DIR}")
        sys.exit(0)
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    App(root)
    root.mainloop()
