"""Ovoz: mikrofondan yozish va javobni ovoz chiqarib o'qish (Windows).

Yozish - Windows'ning o'zidagi winmm (MCI), ijro - winsound. Qo'shimcha kutubxona kerak emas.
O'qish: avval Gemini TTS (o'zbekchani yaxshiroq o'qiydi), ishlamasa Windows'ning o'z ovozi.
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from . import config

IS_WIN = sys.platform == "win32"
TMP = Path(tempfile.gettempdir())
_rec_file = TMP / "ai_agent_mic.wav"
_play_lock = threading.Lock()
_tts_model: str | None = None


# ---------- mikrofon ----------

def _mci(cmd: str) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
    if err:
        msg = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciGetErrorStringW(err, msg, 255)
        raise RuntimeError(f"Mikrofon xatosi: {msg.value}")
    return buf.value


def start_recording() -> None:
    if not IS_WIN:
        raise RuntimeError("Mikrofon faqat Windows'da ishlaydi.")
    stop_speaking()
    try:
        _mci("close aimic")
    except RuntimeError:
        pass
    _mci("open new type waveaudio alias aimic")
    _mci("set aimic bitspersample 16 samplespersec 16000 channels 1")
    _mci("record aimic")


def stop_recording() -> Path:
    """Yozishni to'xtatib, WAV faylni qaytaradi."""
    _mci("stop aimic")
    _rec_file.unlink(missing_ok=True)
    _mci(f'save aimic "{_rec_file}"')
    _mci("close aimic")
    if not _rec_file.exists() or _rec_file.stat().st_size < 8000:  # ~0.25 s dan qisqa
        raise RuntimeError("Ovoz yozilmadi yoki juda qisqa. Mikrofon ulanganini tekshiring.")
    return _rec_file


# ---------- o'qib berish ----------

def clean_for_speech(text: str) -> str:
    """Markdown belgilar, havolalar va emojilarni olib tashlaydi."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "havola", text)
    text = re.sub(r"[*_#`>|~]+", " ", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:1500]


def _pick_tts_model(client) -> str:
    global _tts_model
    if _tts_model:
        return _tts_model
    names = [(m.name or "").removeprefix("models/") for m in client.models.list()]
    tts = [n for n in names if "tts" in n and n.startswith("gemini")]

    def ver(n):
        m = re.match(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0
    tts.sort(key=lambda n: (-ver(n), "pro" in n))
    _tts_model = tts[0] if tts else "gemini-2.5-flash-preview-tts"
    return _tts_model


def _gemini_tts(text: str) -> Path:
    from google.genai import types
    from .gemini_core import make_client
    client = make_client(timeout_s=60)
    resp = client.models.generate_content(
        model=_pick_tts_model(client),
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore"))),
        ),
    )
    part = resp.candidates[0].content.parts[0]
    data, mime = part.inline_data.data, part.inline_data.mime_type or ""
    out = TMP / f"ai_agent_tts_{int(time.time() * 1000)}.wav"
    if "wav" in mime:
        out.write_bytes(data)
    else:  # xom PCM (audio/L16;rate=24000)
        rate = int((re.search(r"rate=(\d+)", mime) or [None, "24000"])[1])
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(data)
    return out


def _windows_tts(text: str) -> Path:
    out = TMP / f"ai_agent_tts_{int(time.time() * 1000)}.wav"
    txt = TMP / "ai_agent_tts.txt"
    txt.write_text(text, encoding="utf-8")
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{out}'); "
          f"$s.Speak([IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8)); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=120, check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not out.exists():
        raise RuntimeError("Windows ovozi ishlamadi")
    return out


def synthesize(text: str) -> Path:
    text = clean_for_speech(text)
    if not text:
        raise RuntimeError("O'qiladigan matn yo'q")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            return _gemini_tts(text)
        except Exception as e:
            config.log_error(f"gemini tts: {type(e).__name__}: {e}")
    if IS_WIN:
        return _windows_tts(text)
    raise RuntimeError("Ovoz chiqarish faqat Windows'da ishlaydi")


def play(path: Path) -> None:
    if IS_WIN:
        import winsound
        with _play_lock:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def stop_speaking() -> None:
    if IS_WIN:
        import winsound
        with _play_lock:
            winsound.PlaySound(None, 0)


def speak(text: str) -> None:
    """Matnni ovozga aylantirib, fonda ijro etadi (kutib turmaydi)."""
    play(synthesize(text))


def speak_async(text: str, on_error=lambda e: None) -> None:
    def work():
        try:
            speak(text)
        except Exception as e:
            config.log_error(f"speak: {type(e).__name__}: {e}")
            on_error(e)
    threading.Thread(target=work, daemon=True).start()

# Agent o'zi biror narsani o'qib bergan bo'lsa, oyna javobni qayta o'qimaydi
spoke_during_run = False
