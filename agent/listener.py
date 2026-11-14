"""Doimiy tinglash (tugmasiz ovozli buyruq).

Mikrofon doim tinglanadi; gap boshlanib tugaganini ovoz balandligidan aniqlaymiz (VAD),
gapni matnga aylantiramiz va "Agent, ..." deb boshlangan bo'lsa - buyruq sifatida yuboramiz.
Agent javob bergandan keyin qisqa vaqt "Agent" demasdan ham davom ettirsa bo'ladi.
"""
import math
import re
import tempfile
import threading
import time
import wave
from array import array
from collections import deque
from pathlib import Path

from . import config

RATE = 16000
FRAME = 480  # 30 ms
WAKE_WORDS = ("agent", "agentt", "ajent", "eyjent", "eydjent", "aydjent", "агент", "эйджент", "ейджент",
              "yordamchi")
FOLLOW_UP_SECONDS = 10


class Segmenter:
    """Ovoz oqimidan alohida gaplarni ajratib oladi (oddiy energiya asosidagi VAD)."""

    def __init__(self):
        self.floor = 200.0          # shovqin darajasi (o'zi moslashadi)
        self.pre = deque(maxlen=10)  # gap boshlanishidan oldingi 300 ms
        self.buf: list[bytes] = []
        self.loud = 0
        self.quiet = 0
        self.voiced = 0              # gap ichidagi baland bo'laklar soni
        self.speaking = False

    @staticmethod
    def rms(frame: bytes) -> float:
        a = array("h", frame)
        return math.sqrt(sum(x * x for x in a) / max(len(a), 1))

    def reset(self):
        self.pre.clear()
        self.buf = []
        self.loud = self.quiet = self.voiced = 0
        self.speaking = False

    def feed(self, frame: bytes) -> bytes | None:
        """Bitta 30 ms bo'lak. Gap tugaganda butun gapning ovozini qaytaradi."""
        level = self.rms(frame)
        threshold = max(self.floor * 3.0, 350.0)
        if not self.speaking:
            self.pre.append(frame)
            if level > threshold:
                self.loud += 1
                if self.loud >= 3:  # 90 ms dan uzoq baland ovoz - gap boshlandi
                    self.speaking = True
                    self.buf = list(self.pre)
                    self.quiet = 0
                    self.voiced = self.loud
            else:
                self.loud = 0
                self.floor = 0.95 * self.floor + 0.05 * level
            return None
        self.buf.append(frame)
        if level < threshold * 0.7:
            self.quiet += 1
        else:
            self.quiet = 0
            self.voiced += 1
        too_long = len(self.buf) > 20 * 1000 // 30  # 20 soniya
        if self.quiet >= 30 or too_long:  # 0.9 s jimlik - gap tugadi
            audio = b"".join(self.buf[:len(self.buf) - max(self.quiet - 10, 0)])  # oxirgi jimlikni qisqartiramiz
            voiced = self.voiced
            self.reset()
            if voiced * 30 >= 400:  # 0.4 s dan kam haqiqiy ovoz bo'lsa - taqillash/shovqin
                return audio
        return None


def strip_wake_word(text: str) -> str | None:
    """'Agent, musiqa qo'y' -> "musiqa qo'y". Uyg'otuvchi so'z bo'lmasa None."""
    words = re.sub(r"[^\w\s']", " ", text.lower()).split()
    for i, w in enumerate(words[:4]):
        if any(w.startswith(k) for k in WAKE_WORDS):
            rest = text.split()[i + 1:] if len(text.split()) > i else []
            return re.sub(r"^[\s,.!?:;-]+", "", " ".join(rest)).strip()
    return None


def save_wav(audio: bytes) -> Path:
    path = Path(tempfile.gettempdir()) / f"ai_agent_heard_{int(time.time() * 1000)}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio)
    return path


class HandsFree(threading.Thread):
    """Fon oqimi: mikrofonni tinglaydi va buyruqlarni on_command(text) ga beradi."""

    def __init__(self, on_command, on_status, is_muted):
        super().__init__(daemon=True)
        self.on_command = on_command   # on_command(text)
        self.on_status = on_status     # on_status(matn) - holat yoki xato
        self.is_muted = is_muted       # True bo'lsa tinglamaydi (agent gapiryapti yoki ishlayapti)
        self._stop_event = threading.Event()
        self.follow_up_until = 0.0
        self._follow_up_pending = False

    def stop(self):
        self._stop_event.set()

    def allow_follow_up(self):
        """Agent javob berdi - u gapirib bo'lgach qisqa vaqt "Agent" demasdan ham gapirsa bo'ladi."""
        self._follow_up_pending = True

    def run(self):
        try:
            import sounddevice as sd
            stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME)
            stream.start()
        except Exception as e:
            config.log_error(f"listener: {type(e).__name__}: {e}")
            self.on_status(f"error:Mikrofonni ochib bo'lmadi ({e}). Mikrofon ulanganini tekshiring.")
            return
        seg = Segmenter()
        try:
            while not self._stop_event.is_set():
                data, _overflow = stream.read(FRAME)
                if self.is_muted():
                    seg.reset()
                    continue
                if self._follow_up_pending:  # agent gapirib bo'ldi - suhbat oynasi shu paytdan boshlanadi
                    self._follow_up_pending = False
                    self.follow_up_until = time.time() + FOLLOW_UP_SECONDS
                    self.on_status("follow")
                audio = seg.feed(bytes(data))
                if audio:
                    threading.Thread(target=self._process_audio, args=(audio,), daemon=True).start()
        finally:
            stream.stop()
            stream.close()

    def _process_audio(self, audio: bytes):
        from .media import transcribe
        try:
            text = transcribe(save_wav(audio)).strip()
        except Exception as e:
            config.log_error(f"listener transcribe: {type(e).__name__}: {e}")
            return
        if not text:
            return
        command = strip_wake_word(text)
        if command is None and time.time() < self.follow_up_until:
            command = text  # suhbat davom etmoqda - "Agent" shart emas
        if command is None:
            return  # boshqa gap - buyruq emas
        self.on_command(command or "")
