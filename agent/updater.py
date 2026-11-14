"""Dastur ichidan yangilanish: GitHub'dagi "latest" relizni tekshiradi va .exe ni almashtiradi."""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import config

REPO = "ndoston1202-glitch/aget_ai"
API_URL = f"https://api.github.com/repos/{REPO}/releases/tags/latest"

try:
    from ._version import BUILD_SHA  # CI .exe yasashda yaratadi
except ImportError:
    BUILD_SHA = "dev"


def current_version() -> str:
    return BUILD_SHA[:7]


def can_update() -> bool:
    """Faqat Windows .exe versiyasi o'zini yangilay oladi."""
    return config.FROZEN and sys.platform == "win32" and BUILD_SHA != "dev"


def check() -> dict | None:
    """Yangi versiya bo'lsa {'sha', 'url', 'size'} qaytaradi, aks holda None."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "aget_ai-updater",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    sha = data.get("target_commitish", "")
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(".exe")), None)
    if not asset or not sha or sha == BUILD_SHA:
        return None
    return {"sha": sha, "url": asset["browser_download_url"], "size": asset.get("size", 0)}


def download(info: dict, on_progress=lambda pct: None) -> Path:
    exe = Path(sys.executable)
    new = exe.with_name(exe.stem + "_new.exe")
    req = urllib.request.Request(info["url"], headers={"User-Agent": "aget_ai-updater"})
    with urllib.request.urlopen(req, timeout=60) as r, open(new, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if total:
                on_progress(int(done * 100 / total))
    if info.get("size") and new.stat().st_size != info["size"]:
        new.unlink(missing_ok=True)
        raise IOError("Fayl to'liq yuklanmadi, qayta urinib ko'ring.")
    return new


def install_and_restart(new: Path, restart_args: list[str] | None = None) -> None:
    """Dastur yopilgach eski .exe ni yangisiga almashtirib, qayta ishga tushiradi.

    Eski fayl oldindan o'chirilmaydi: yangisi uning ustiga ko'chiriladi. Fayl band bo'lsa
    (dastur hali yopilmagan yoki antivirus tekshiryapti) 2 daqiqagacha qayta urinadi; baribir
    bo'lmasa, yangi nusxani o'z joyidan ishga tushiradi - dastur hech qachon yo'qolib qolmaydi.
    """
    old = Path(sys.executable)
    args = " ".join(f'"{a}"' for a in (restart_args or []))
    log = config.LOG_DIR / "update.log"
    bat = Path(tempfile.gettempdir()) / "aget_ai_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
        "set n=0\r\n"
        ":wait\r\n"
        "ping -n 3 127.0.0.1 >nul\r\n"
        f'move /y "{new}" "{old}" >nul 2>&1\r\n'
        f'if not exist "{new}" goto ok\r\n'
        "set /a n+=1\r\n"
        "if %n% lss 60 goto wait\r\n"
        f'echo %date% %time% move failed, starting new copy >> "{log}"\r\n'
        f'start "" "{new}" {args}\r\n'
        "goto end\r\n"
        ":ok\r\n"
        f'echo %date% %time% updated after %n% retries >> "{log}"\r\n'
        f'start "" "{old}" {args}\r\n'
        ":end\r\n"
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True, env=clean_env())
    os._exit(0)


def clean_env() -> dict:
    """Yangi nusxa eski nusxaning vaqtinchalik papkasini (_MEI...) "meros" olmasligi uchun.

    Aks holda qayta ishga tushganda "Failed to load Python DLL" xatosi chiqadi.
    """
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("_PYI") or k.startswith("_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def spawn_self_test(marker: str) -> None:
    """CI sinovi: o'zini yangilanishdagidek qayta ishga tushiradi va darhol chiqadi."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", "start", "", sys.executable, "--write-marker", marker],
                     creationflags=flags, close_fds=True, env=clean_env())
    os._exit(0)
