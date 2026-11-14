"""Uzoq muddatli xotira: agent tajribadan o'rgangan saboqlar va foydalanuvchi afzalliklari.

O'zini mukammallashtirish shu yerda: har bir vazifadan keyin agent nima yaxshi/yomon
o'tganini tahlil qiladi va saboqlarni saqlaydi. Keyingi safar bu saboqlar system
prompt'ga qo'shiladi, shuning uchun agent bir xil xatoni takrorlamaydi.
"""
import json
from datetime import datetime

from . import config
from .storage import load_json, save_json

MAX_ITEMS = 60  # xotira juda kattalashib ketmasligi uchun


def _load() -> dict:
    return load_json(config.MEMORY_FILE, {"lessons": [], "preferences": []})


def add(kind: str, text: str) -> str:
    """kind: 'lessons' yoki 'preferences'."""
    text = text.strip()
    if not text:
        return "Bo'sh matn saqlanmadi."
    mem = _load()
    items = mem.setdefault(kind, [])
    if any(i["text"].lower() == text.lower() for i in items):
        return "Bu allaqachon xotirada bor."
    items.append({"text": text, "date": datetime.now().isoformat(timespec="minutes")})
    mem[kind] = items[-MAX_ITEMS:]
    save_json(config.MEMORY_FILE, mem)
    return "Xotiraga saqlandi."


def remove(kind: str, index: int) -> str:
    mem = _load()
    items = mem.get(kind, [])
    if not 0 <= index < len(items):
        return "Bunday raqamli yozuv yo'q."
    removed = items.pop(index)
    save_json(config.MEMORY_FILE, mem)
    return f"O'chirildi: {removed['text']}"


def as_prompt() -> str:
    mem = _load()
    parts = []
    if mem.get("preferences"):
        parts.append("Foydalanuvchi afzalliklari:\n" + "\n".join(
            f"- {p['text']}" for p in mem["preferences"]))
    if mem.get("lessons"):
        parts.append("Oldingi tajribadan saboqlar:\n" + "\n".join(
            f"- {l['text']}" for l in mem["lessons"]))
    return "\n\n".join(parts) if parts else "Xotira hozircha bo'sh."


def show() -> str:
    mem = _load()
    out = []
    for kind, title in (("preferences", "Afzalliklar"), ("lessons", "Saboqlar")):
        out.append(f"== {title} ==")
        items = mem.get(kind, [])
        out += [f"  [{i}] {x['text']}" for i, x in enumerate(items)] or ["  (bo'sh)"]
    return "\n".join(out)


REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "lessons": {"type": "array", "items": {"type": "string"}},
        "preferences": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["lessons", "preferences"],
    "additionalProperties": False,
}


def reflect(complete_json, task: str, transcript: str) -> list[str]:
    """Vazifadan keyin o'z ishini tahlil qilib, yangi saboqlarni saqlaydi.

    complete_json(prompt, schema) -> str : modelga so'rov yuborib JSON matn qaytaruvchi funksiya.
    """
    prompt = (
        "Sen o'z ishini tahlil qilayotgan AI agentsan. Quyida bajarilgan vazifa va uning "
        "jarayoni berilgan. Kelajakda foydali bo'ladigan QISQA, ANIQ saboqlarni chiqar: "
        "qaysi yondashuv ishladi, qaysi xato bo'ldi va undan qanday qochish kerak. "
        "Foydalanuvchi o'zi haqida yoki ish uslubi haqida aytgan afzalliklarni alohida yoz. "
        "Agar haqiqatan yangi va foydali narsa bo'lmasa, bo'sh ro'yxat qaytar. "
        "Har biri 1 jumla, o'zbek tilida. Javob faqat JSON: "
        '{"lessons": [...], "preferences": [...]}\n\n'
        f"Mavjud xotira:\n{as_prompt()}\n\n"
        f"Vazifa: {task}\n\nJarayon:\n{transcript[-12000:]}"
    )
    try:
        text = complete_json(prompt, REFLECT_SCHEMA)
        if not text:
            return []
        data = json.loads(text)
    except Exception as e:  # tahlil muvaffaqiyatsiz bo'lsa ham asosiy ish buzilmasin
        return [f"(tahlil bajarilmadi: {e})"]

    saved = []
    for kind in ("lessons", "preferences"):
        for item in data.get(kind, []):
            if add(kind, item) == "Xotiraga saqlandi.":
                saved.append(item)
    return saved
