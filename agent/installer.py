"""O'rnatuvchi: dasturni C:\\AI Agent papkasiga ko'chiradi va yorliqlar yaratadi."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config
from .updater import clean_env

EXE_NAME = "aget_ai.exe"


def can_install() -> bool:
    return config.FROZEN and sys.platform == "win32" and not config.is_installed()


def target_exe() -> Path:
    return config.INSTALL_DIR / EXE_NAME


def _copy_legacy_data() -> None:
    """Eski joydagi (C:\\Users\\<siz>\\aget_ai) xotira, sozlamalar va fayllarni ko'chiradi."""
    for name in ("data", "workspace", "projekt"):
        src, dst = config.LEGACY_DIR / name, config.INSTALL_DIR / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)


def _create_shortcuts(exe: Path) -> None:
    """Ish stoli va Пуск menyusida "AI Agent" yorlig'ini yaratadi."""
    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        "$dirs = @([Environment]::GetFolderPath('Desktop'), "
        "(Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs')); "
        "foreach ($d in $dirs) { "
        "  $l = $s.CreateShortcut((Join-Path $d 'AI Agent.lnk')); "
        f"  $l.TargetPath = '{exe}'; "
        f"  $l.WorkingDirectory = '{exe.parent}'; "
        "  $l.Description = 'Shaxsiy AI agent'; "
        "  $l.Save() }"
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60, check=False)


def install(extra_args: list[str] | None = None) -> Path:
    """O'rnatadi va o'rnatilgan nusxani ishga tushiradi. Xato bo'lsa istisno ko'taradi."""
    exe = target_exe()
    config.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = exe.with_suffix(".new")
    shutil.copy2(sys.executable, tmp)
    os.replace(tmp, exe)
    _copy_legacy_data()
    _create_shortcuts(exe)
    subprocess.Popen([str(exe), *(extra_args or [])], cwd=str(config.INSTALL_DIR),
                     env=clean_env(), close_fds=True)
    return exe
