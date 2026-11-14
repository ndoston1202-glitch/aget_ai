"""Agent bajara oladigan amallar (tools).

Xavfli amallar (buyruq ishga tushirish, fayl yozish) foydalanuvchi ruxsatisiz bajarilmaydi.
"""
import os
import platform
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, memory, scheduler


class Human:
    """Agent bilan foydalanuvchi o'rtasidagi aloqa (ruxsat so'rash, savol berish)."""

    def approve(self, action: str) -> bool:
        raise NotImplementedError

    def ask(self, question: str) -> str:
        raise NotImplementedError


class ConsoleHuman(Human):
    def approve(self, action: str) -> bool:
        print(f"\n⚠️  Agent ruxsat so'rayapti:\n{action}")
        ans = input("Ruxsat berasizmi? [h/y] (ha/yo'q): ").strip().lower()
        return ans in ("h", "ha", "y", "yes", "ok")

    def ask(self, question: str) -> str:
        print(f"\n❓ Agent savoli: {question}")
        return input("Javobingiz: ").strip() or "(javob berilmadi)"


class AutoHuman(Human):
    """Takrorlanuvchi vazifalar uchun: foydalanuvchi yonida emas."""

    def __init__(self, allow_actions: bool):
        self.allow_actions = allow_actions

    def approve(self, action: str) -> bool:
        return self.allow_actions

    def ask(self, question: str) -> str:
        return ("Foydalanuvchi hozir yo'q (bu avtomatik vazifa). Xavfsiz yo'lni tanla "
                "yoki savolni yakuniy hisobotda yoz.")


def system_context() -> str:
    """Har so'rovda modelga beriladigan joriy holat."""
    shell = "cmd (Windows)" if platform.system() == "Windows" else "bash"
    return (f"Bugungi sana: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"Operatsion tizim: {platform.system()} {platform.release()}, run_shell buyruqlari {shell} da bajariladi\n"
            f"Workspace papka: {config.WORKSPACE_DIR}\n"
            f"Loyihalar papkasi: {config.PROJECTS_DIR}\n"
            f"GitHub tokeni: {'kiritilgan' if os.environ.get('GITHUB_TOKEN') else 'kiritilmagan'}\n\n"
            f"{memory.as_prompt()}")


def _open_link(url: str, human) -> str:
    """Havolani ochadi: buyruq telefondan kelgan bo'lsa - telefonda, aks holda kompyuterda."""
    if hasattr(human, "open_on_device"):
        human.open_on_device(url)
        return "Telefonda ochildi"
    import webbrowser
    webbrowser.open(url)
    return "Kompyuterda ochildi"


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (config.WORKSPACE_DIR / p)


def _truncate(text: str, limit: int = 20000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} belgi qisqartirildi)"


# --- Tool sxemalari (Claude'ga yuboriladi) ---

def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOL_DEFS = [
    {
        "name": "run_shell",
        "description": "Kompyuterda shell buyrug'ini bajaradi (Windows'da cmd, Linux/Mac'da bash). Foydalanuvchidan ruxsat so'raladi. "
                       "Ishchi papka: agent workspace.",
        "input_schema": _schema({
            "command": {"type": "string", "description": "Bajariladigan buyruq"},
            "reason": {"type": "string", "description": "Nega bu buyruq kerakligi (foydalanuvchiga ko'rsatiladi)"},
        }, ["command", "reason"]),
    },
    {
        "name": "read_file",
        "description": "Fayl matnini o'qiydi. Nisbiy yo'l workspace papkasiga nisbatan.",
        "input_schema": _schema({"path": {"type": "string"}}, ["path"]),
    },
    {
        "name": "write_file",
        "description": "Faylga matn yozadi (mavjud bo'lsa ustidan yozadi). Foydalanuvchidan ruxsat so'raladi.",
        "input_schema": _schema({
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, ["path", "content"]),
    },
    {
        "name": "list_dir",
        "description": "Papkadagi fayllar ro'yxati.",
        "input_schema": _schema({"path": {"type": "string", "description": "Bo'sh bo'lsa workspace"}}, ["path"]),
    },
    {
        "name": "ask_user",
        "description": "Foydalanuvchiga savol berib, javobini kutadi. Vazifa noaniq bo'lsa yoki "
                       "muhim qaror kerak bo'lsa ishlat.",
        "input_schema": _schema({"question": {"type": "string"}}, ["question"]),
    },
    {
        "name": "remember",
        "description": "Uzoq muddatli xotiraga yozadi. kind='preferences' - foydalanuvchi afzalliklari, "
                       "kind='lessons' - ish jarayonidan o'rganilgan saboq.",
        "input_schema": _schema({
            "kind": {"type": "string", "enum": ["preferences", "lessons"]},
            "text": {"type": "string"},
        }, ["kind", "text"]),
    },
    {
        "name": "schedule_task",
        "description": "Takrorlanuvchi vazifa yaratadi: har every_minutes daqiqada prompt bajariladi. "
                       "allow_actions=true bo'lsa avtomatik vazifa buyruq/fayl yozishni ruxsatsiz bajara oladi - "
                       "buni faqat foydalanuvchi aniq rozi bo'lsa qo'y.",
        "input_schema": _schema({
            "prompt": {"type": "string", "description": "Har safar bajariladigan vazifa matni"},
            "every_minutes": {"type": "integer"},
            "allow_actions": {"type": "boolean"},
        }, ["prompt", "every_minutes", "allow_actions"]),
    },
    {
        "name": "generate_image",
        "description": "Matn tavsifi asosida rasm yaratadi va workspace/images/ ga saqlaydi. "
                       "Tavsifni batafsil yoz (ingliz tilida yozsang natija yaxshiroq).",
        "input_schema": _schema({"prompt": {"type": "string"}}, ["prompt"]),
    },
    {
        "name": "transcribe_audio",
        "description": "Ovozli faylni (mp3, m4a, ogg, wav...) matnga aylantiradi.",
        "input_schema": _schema({"path": {"type": "string"}}, ["path"]),
    },
    {
        "name": "project_folder",
        "description": "Dasturlash loyihasi uchun papka yaratadi (projekt/<nom>) va yo'lini qaytaradi. "
                       "Loyiha fayllarini shu papkaga yoz.",
        "input_schema": _schema({"name": {"type": "string", "description": "Loyiha nomi"}}, ["name"]),
    },
    {
        "name": "github_create_repo",
        "description": "GitHub'da yangi repozitoriy ochib, loyiha papkasidagi fayllarni unga yuklaydi. "
                       "Faqat foydalanuvchi GitHub'ga yuklashga rozi bo'lgandan keyin ishlat.",
        "input_schema": _schema({
            "name": {"type": "string"},
            "folder": {"type": "string", "description": "project_folder qaytargan papka"},
            "description": {"type": "string"},
            "private": {"type": "boolean", "description": "true - yopiq repo (sukut bo'yicha)"},
        }, ["name", "folder", "description", "private"]),
    },
    {
        "name": "play_youtube",
        "description": "YouTube'dan qo'shiq yoki videoni qidirib, birinchi natijani brauzerda ochadi (ijro boshlanadi).",
        "input_schema": _schema({"query": {"type": "string", "description": "Masalan: 'Shahzoda yangi qo'shiq'"}},
                                ["query"]),
    },
    {
        "name": "open_url",
        "description": "Sayt yoki havolani foydalanuvchining brauzerida ochadi.",
        "input_schema": _schema({"url": {"type": "string"}}, ["url"]),
    },
    {
        "name": "media_control",
        "description": "Kompyuterdagi musiqa/videoni boshqaradi (klaviaturaning media tugmalari kabi): "
                       "play_pause - to'xtatish yoki davom ettirish, next - keyingi, previous - oldingi, "
                       "volume_up / volume_down - ovozni balandlatish/pasaytirish, mute - ovozni o'chirish/yoqish.",
        "input_schema": _schema({
            "action": {"type": "string",
                       "enum": ["play_pause", "next", "previous", "volume_up", "volume_down", "mute"]},
            "times": {"type": "integer", "description": "Necha marta bosish (ovoz uchun, masalan 5)"},
        }, ["action", "times"]),
    },
    {
        "name": "close_program",
        "description": "Kompyuterdagi dasturni yopadi (masalan brauzerni). Foydalanuvchidan ruxsat so'raladi. "
                       "name - jarayon nomi: chrome, msedge, firefox, telegram, winword va hokazo.",
        "input_schema": _schema({"name": {"type": "string"}}, ["name"]),
    },
    {
        "name": "speak_text",
        "description": "Berilgan matnni ovoz chiqarib o'qib beradi. Foydalanuvchi biror matnni (masalan tarjimani) "
                       "o'qib berishni so'raganda ishlat.",
        "input_schema": _schema({"text": {"type": "string"}}, ["text"]),
    },
    {
        "name": "list_scheduled_tasks",
        "description": "Barcha takrorlanuvchi vazifalar ro'yxati.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "cancel_scheduled_task",
        "description": "Takrorlanuvchi vazifani o'chiradi.",
        "input_schema": _schema({"task_id": {"type": "string"}}, ["task_id"]),
    },
]

# Gemini uchun: internetdagi sahifani o'qish (Claude'da buning o'rniga server vositasi bor)
FETCH_URL_DEF = {
    "name": "fetch_url",
    "description": "Internetdagi sahifani (URL) yuklab, matnini qaytaradi.",
    "input_schema": _schema({"url": {"type": "string"}}, ["url"]),
}

# Anthropic serverida ishlaydigan tayyor vositalar (internetdan qidirish va sahifa o'qish)
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]


# --- Tool bajaruvchilar ---

def execute(name: str, args: dict, human: Human) -> tuple[str, bool]:
    """(natija, xatomi) qaytaradi."""
    try:
        if name == "run_shell":
            cmd = args["command"]
            if not human.approve(f"  Buyruq: {cmd}\n  Sabab:  {args.get('reason', '')}"):
                return "Foydalanuvchi bu buyruqqa ruxsat bermadi.", True
            r = subprocess.run(cmd, shell=True, cwd=config.WORKSPACE_DIR, capture_output=True,
                               text=True, errors="replace", timeout=config.SHELL_TIMEOUT)
            out = f"exit code: {r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
            return _truncate(out), r.returncode != 0

        if name == "read_file":
            return _truncate(_resolve(args["path"]).read_text(encoding="utf-8", errors="replace")), False

        if name == "write_file":
            path = _resolve(args["path"])
            preview = args["content"][:400] + ("..." if len(args["content"]) > 400 else "")
            if not human.approve(f"  Faylga yozish: {path}\n  Mazmuni:\n{preview}"):
                return "Foydalanuvchi faylga yozishga ruxsat bermadi.", True
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"Yozildi: {path} ({len(args['content'])} belgi)", False

        if name == "list_dir":
            path = _resolve(args.get("path") or ".")
            items = sorted(path.iterdir())
            return "\n".join(f"{'[D]' if p.is_dir() else '   '} {p.name}" for p in items) or "(bo'sh)", False

        if name == "fetch_url":
            req = urllib.request.Request(args["url"], headers={"User-Agent": "Mozilla/5.0 aget_ai"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
            raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
            return _truncate(text, 15000), False

        if name == "generate_image":
            from .media import generate_image
            out = generate_image(args["prompt"])
            return f"Rasm yaratildi va saqlandi: {out}", False

        if name == "transcribe_audio":
            from .media import transcribe
            return transcribe(_resolve(args["path"])), False

        if name == "project_folder":
            from .projects import project_folder
            return f"Loyiha papkasi: {project_folder(args['name'])}", False

        if name == "github_create_repo":
            from .projects import create_repo
            vis = "yopiq (private)" if args.get("private", True) else "ochiq (public)"
            if not human.approve(f"  GitHub'da {vis} repo ochish: {args['name']}\n  Papka: {args['folder']}"):
                return "Foydalanuvchi GitHub'ga yuklashga ruxsat bermadi.", True
            return create_repo(args["name"], args["folder"], args.get("description", ""),
                               args.get("private", True)), False

        if name == "play_youtube":
            import urllib.parse
            import webbrowser
            q = urllib.parse.quote_plus(args["query"])
            url = f"https://www.youtube.com/results?search_query={q}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "uz,ru,en"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    html = r.read(3_000_000).decode("utf-8", errors="replace")
                vid = re.search(r'"videoId":"([\w-]{11})"', html)
                title = re.search(r'"title":\{"runs":\[\{"text":"([^"]{1,150})"', html)
                if vid:
                    url = f"https://www.youtube.com/watch?v={vid.group(1)}"
                    where = _open_link(url, human)
                    return f"{where}: {title.group(1) if title else args['query']} ({url})", False
            except Exception:
                pass
            where = _open_link(url, human)
            return f"{where} (YouTube qidiruv natijalari): {url}", False

        if name == "open_url":
            import webbrowser
            url = args["url"].strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return f"{_open_link(url, human)}: {url}", False

        if name == "media_control":
            if platform.system() != "Windows":
                return "Bu funksiya faqat Windows'da ishlaydi.", True
            import ctypes
            import time as _t
            vk = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
                  "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}[args["action"]]
            times = max(1, min(int(args.get("times") or 1), 25))
            for _ in range(times):
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
                _t.sleep(0.05)
            return f"Bajarildi: {args['action']} ({times} marta)", False

        if name == "close_program":
            proc = re.sub(r"[^A-Za-z0-9._-]", "", args["name"]).removesuffix(".exe")
            if not proc:
                return "Dastur nomi noto'g'ri.", True
            if not human.approve(f"  Dasturni yopish: {proc}.exe"):
                return "Foydalanuvchi ruxsat bermadi.", True
            r = subprocess.run(["taskkill", "/IM", f"{proc}.exe"], capture_output=True, text=True,
                               errors="replace", timeout=30)
            ok = r.returncode == 0
            return (f"{proc} yopildi." if ok else f"Yopib bo'lmadi: {(r.stderr or r.stdout).strip()}"), not ok

        if name == "speak_text":
            from . import voice
            voice.spoke_during_run = True
            voice.speak_async(args["text"])
            return "Matn ovoz chiqarib o'qilmoqda.", False

        if name == "ask_user":
            return human.ask(args["question"]), False

        if name == "remember":
            return memory.add(args["kind"], args["text"]), False

        if name == "schedule_task":
            if args.get("allow_actions") and not human.approve(
                    f"  Avtomatik vazifaga ruxsatsiz amal bajarish huquqi berilsinmi?\n  Vazifa: {args['prompt']}"):
                args["allow_actions"] = False
            t = scheduler.add_task(args["prompt"], args["every_minutes"], args["allow_actions"])
            return (f"Vazifa yaratildi: id={t['id']}, har {t['every_minutes']} daqiqada, "
                    f"amallarga ruxsat={t['allow_actions']}"), False

        if name == "list_scheduled_tasks":
            tasks = scheduler.list_tasks()
            if not tasks:
                return "Takrorlanuvchi vazifalar yo'q.", False
            return "\n".join(
                f"{t['id']}: har {t['every_minutes']} daq | {'yoqilgan' if t['enabled'] else 'to`xtatilgan'} | "
                f"{t['prompt']} | oxirgi natija: {t['last_result']}" for t in tasks), False

        if name == "cancel_scheduled_task":
            ok = scheduler.remove_task(args["task_id"])
            return ("O'chirildi." if ok else "Bunday id topilmadi."), not ok

        return f"Noma'lum tool: {name}", True
    except subprocess.TimeoutExpired:
        return f"Buyruq {config.SHELL_TIMEOUT} sekunddan ko'p ishladi va to'xtatildi.", True
    except Exception as e:
        return f"Xato: {type(e).__name__}: {e}", True
