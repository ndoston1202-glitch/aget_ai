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


def _shortcut(folder_ps: str, exe: Path, args: str = "") -> None:
    """PowerShell orqali "AI Agent.lnk" yorlig'ini yaratadi. folder_ps - papkani beruvchi PowerShell ifoda."""
    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut((Join-Path ({folder_ps}) 'AI Agent.lnk')); "
        f"$l.TargetPath = '{exe}'; $l.Arguments = '{args}'; "
        f"$l.WorkingDirectory = '{exe.parent}'; $l.Description = 'Shaxsiy AI yordamchi'; $l.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60, check=False)


def _create_shortcuts(exe: Path) -> None:
    """Ish stoli va Пуск menyusida "AI Agent" yorlig'ini yaratadi."""
    _shortcut("[Environment]::GetFolderPath('Desktop')", exe)
    _shortcut("Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'", exe)


def startup_link() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "AI Agent.lnk"


def set_autostart(enabled: bool, exe: Path | None = None) -> None:
    """Kompyuter yonganda dasturni avtomatik ishga tushirishni yoqadi/o'chiradi."""
    if sys.platform != "win32":
        return
    if enabled:
        _shortcut("[Environment]::GetFolderPath('Startup')", exe or Path(sys.executable), "--autostart")
    else:
        startup_link().unlink(missing_ok=True)


def install(extra_args: list[str] | None = None) -> Path:
    """O'rnatadi va o'rnatilgan nusxani ishga tushiradi. Xato bo'lsa istisno ko'taradi."""
    exe = target_exe()
    config.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = exe.with_suffix(".new")
    shutil.copy2(sys.executable, tmp)
    os.replace(tmp, exe)
    _copy_legacy_data()
    _create_shortcuts(exe)
    set_autostart(True, exe)
    subprocess.Popen([str(exe), *(extra_args or [])], cwd=str(config.INSTALL_DIR),
                     env=clean_env(), close_fds=True)
    return exe
