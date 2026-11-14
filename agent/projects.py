"""Dasturlash loyihalari: C:\\AI Agent\\projekt\\<nom> papkasi yoki GitHub repozitoriy."""
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import config

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
MAX_FILE = 20_000_000  # GitHub API orqali bitta fayl uchun chegara


def safe_name(name: str) -> str:
    """Loyiha nomini papka va repo nomi uchun xavfsiz qiladi."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return name[:80] or "loyiha"


def project_folder(name: str) -> Path:
    folder = config.PROJECTS_DIR / safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _api(method: str, url: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "AI-Agent", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 401:
            raise RuntimeError("GitHub tokeni noto'g'ri yoki muddati o'tgan (Sozlamalar).") from None
        if e.code == 422 and "already exists" in detail:
            raise RuntimeError("Bunday nomli repo GitHub'da allaqachon bor. Boshqa nom tanlang.") from None
        raise RuntimeError(f"GitHub xatosi {e.code}: {detail}") from None


def create_repo(name: str, folder: str, description: str = "", private: bool = True) -> str:
    """GitHub'da repo ochib, papkadagi fayllarni yuklaydi. Repo havolasini qaytaradi."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GitHub tokeni kiritilmagan. Sozlamalar oynasida GitHub tokenini kiriting.")
    root = Path(folder)
    if not root.is_dir():
        raise RuntimeError(f"Papka topilmadi: {root}")
    repo = _api("POST", "https://api.github.com/user/repos", token,
                {"name": safe_name(name), "description": description[:300], "private": private})
    full = repo["full_name"]
    uploaded, skipped = 0, []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        rel = f.relative_to(root).as_posix()
        if f.stat().st_size > MAX_FILE:
            skipped.append(rel)
            continue
        _api("PUT", f"https://api.github.com/repos/{full}/contents/{urllib.request.quote(rel)}", token,
             {"message": f"Add {rel}", "content": base64.b64encode(f.read_bytes()).decode()})
        uploaded += 1
    note = f" (juda katta, yuklanmadi: {', '.join(skipped)})" if skipped else ""
    return f"{repo['html_url']} — {uploaded} ta fayl yuklandi{note}"
