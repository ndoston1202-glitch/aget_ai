"""Rasm yaratish va ovozni matnga aylantirish (Gemini orqali).

Bu funksiyalar GEMINI_API_KEY bilan ishlaydi - asosiy AI Claude bo'lsa ham.
"""
import mimetypes
import os
import re
import uuid
from pathlib import Path

from . import config

AUDIO_TYPES = {".mp3": "audio/mp3", ".wav": "audio/wav", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
               ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".flac": "audio/flac", ".amr": "audio/amr", ".3gp": "audio/3gpp", ".webm": "audio/webm"}

_image_model: str | None = None


def _client():
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise RuntimeError("Bu funksiya uchun Gemini API kaliti kerak (Sozlamalar).")
    from google import genai
    return genai.Client()


def _pick_image_model(client) -> str:
    """Rasm chiqara oladigan eng yangi Gemini modelini topadi."""
    global _image_model
    if _image_model:
        return _image_model
    preferred = os.environ.get("GEMINI_IMAGE_MODEL")
    if preferred:
        _image_model = preferred
        return preferred
    best, best_ver = None, -1.0
    for m in client.models.list():
        name = (m.name or "").removeprefix("models/")
        actions = m.supported_actions or []
        match = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash-image(?:-preview)?", name)
        if match and (not actions or "generateContent" in actions):
            ver = float(match.group(1)) - (0.01 if name.endswith("preview") else 0)
            if ver > best_ver:
                best, best_ver = name, ver
    _image_model = best or "gemini-2.5-flash-image"
    return _image_model


def generate_image(prompt: str) -> Path:
    """Matn asosida rasm yaratadi va workspace/images/ ga saqlaydi."""
    from google.genai import types
    client = _client()
    resp = client.models.generate_content(
        model=_pick_image_model(client),
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if part.inline_data and part.inline_data.data:
                ext = mimetypes.guess_extension(part.inline_data.mime_type or "image/png") or ".png"
                out = config.WORKSPACE_DIR / "images" / f"rasm_{uuid.uuid4().hex[:8]}{ext}"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(part.inline_data.data)
                return out
    raise RuntimeError("Model rasm qaytarmadi (so'rov rad etilgan yoki kalitda bu imkoniyat yo'q).")


def transcribe(path: Path) -> str:
    """Ovozli faylni matnga aylantiradi (aytilgan tilda)."""
    from google.genai import types
    path = Path(path)
    mime = AUDIO_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "audio/mp4"
    data = path.read_bytes()
    if len(data) > 18_000_000:
        raise RuntimeError("Ovozli fayl juda katta (18 MB dan oshmasin).")
    from google.genai import errors
    client = _client()
    contents = [types.Part.from_bytes(data=data, mime_type=mime),
                "Bu ovozli xabarni so'zma-so'z matnga aylantir. Qaysi tilda aytilgan bo'lsa, "
                "o'sha tilda yoz. Faqat matnning o'zini qaytar, izohsiz."]
    try:
        resp = client.models.generate_content(model=config.GEMINI_MODEL, contents=contents)
    except errors.APIError as e:
        if e.code != 404:
            raise
        from .gemini_core import pick_model
        resp = client.models.generate_content(model=pick_model(client) or config.GEMINI_MODEL,
                                              contents=contents)
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Ovozdan matn chiqmadi.")
    return text
