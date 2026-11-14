# aget_ai — shaxsiy AI agent

Oddiy chatbot emas: buyruqni tushunadi, **o'zi amal bajaradi**, kerak bo'lsa **sizdan so'raydi**,
**takrorlanuvchi vazifalarni** fon rejimida bajaradi va har bir ishdan keyin **o'zidan saboq chiqarib** boradi.
Claude (Anthropic API) asosida ishlaydi.

## Imkoniyatlar

| Imkoniyat | Qanday ishlaydi |
|---|---|
| Amal bajarish | Shell buyruqlari, fayl o'qish/yozish, papkalarni ko'rish, internetdan qidirish va sahifa o'qish |
| Ruxsat so'rash | Buyruq ishga tushirish va fayl yozishdan oldin har safar `Ruxsat berasizmi? [h/y]` deb so'raydi |
| Sizdan javob kutish | Vazifa noaniq bo'lsa `ask_user` orqali savol beradi va javobingizni kutadi |
| Takrorlanuvchi vazifalar | "Har soatda ..." desangiz, o'zi vazifa yaratadi va fon rejimida bajarib turadi |
| O'zini mukammallashtirish | Har bir vazifadan keyin o'z ishini tahlil qilib, saboqlarni `data/memory.json` ga yozadi. Keyingi safar ularni hisobga oladi |
| Xotira | Siz haqingizdagi afzalliklarni eslab qoladi (masalan, "javoblarni qisqa yoz") |

## Eng oson yo'l: .exe (Windows, terminalsiz)

1. Yuklab oling: **https://github.com/ndoston1202-glitch/aget_ai/releases/download/latest/aget_ai.exe**
2. Faylni ikki marta bosing. Windows ogohlantirsa: **Подробнее (More info) → Выполнить в любом случае (Run anyway)**.
3. Birinchi ochilishda **Gemini** ni tanlang va API kalitini kiriting
   (bepul kalit: https://aistudio.google.com/apikey).
4. Pastdagi maydonga topshiriq yozib, **Yuborish** ni bosing.

Ma'lumotlar (xotira, vazifalar, kalit) `C:\Users\<siz>\aget_ai` papkasida saqlanadi.
Dastur yopilsa, takrorlanuvchi vazifalar ham to'xtaydi.

## Dasturchilar uchun: Python orqali o'rnatish

```bash
git clone https://github.com/ndoston1202-glitch/aget_ai
cd aget_ai
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

API kalitini o'rnating. Bepul variant — Gemini ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)):

```bash
set GEMINI_API_KEY=kalitingiz            # Linux/Mac: export GEMINI_API_KEY=kalitingiz
```

Yoki Claude ([console.anthropic.com](https://console.anthropic.com), pullik): `ANTHROPIC_API_KEY`.

## Ishga tushirish

```bash
python gui.py      # oynali dastur
python main.py     # terminal versiyasi
```

Misollar:

```
Siz: workspace papkasida hello.py yarat, u "Salom dunyo" chiqarsin, keyin ishga tushirib tekshir
Siz: har 60 daqiqada BTC narxini internetdan topib, workspace/btc.txt ga qo'shib bor
Siz: bundan keyin javoblarni juda qisqa yoz
```

Suhbat buyruqlari: `/tasks`, `/stop <id>`, `/memory`, `/forget lessons 0`, `/new`, `/exit`.

Faqat takrorlanuvchi vazifalarni (masalan serverda) ishlatish uchun:

```bash
python main.py --daemon
```

## Xavfsizlik

- Avtomatik (takrorlanuvchi) vazifalar sukut bo'yicha buyruq ishga tushira olmaydi va fayl yoza olmaydi.
  Bunga faqat siz vazifa yaratilayotganda aniq ruxsat bersangiz huquq beriladi.
- Nisbiy fayl yo'llari `workspace/` papkasiga nisbatan olinadi.
- Ruxsat so'ralganda buyruqni diqqat bilan o'qing.

## Sozlamalar (muhit o'zgaruvchilari)

| O'zgaruvchi | Sukut | Ma'nosi |
|---|---|---|
| `AGENT_PROVIDER` | kalitga qarab | `gemini` yoki `claude` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini modeli |
| `AGENT_MODEL` | `claude-opus-5-5` | Claude modeli |
| `AGENT_EFFORT` | `high` | O'ylash darajasi: `low`, `medium`, `high`, `xhigh`, `max` |
| `AGENT_WORKSPACE` | `./workspace` | Agent ishlaydigan papka |
| `AGENT_DATA_DIR` | `./data` | Xotira, vazifalar va loglar |

## Tuzilma

```
gui.py             # oynali dastur (.exe shundan yasaladi)
main.py            # CLI va fon rejimi
agent/gemini_core.py # Gemini agent sikli
agent/core.py      # agent sikli (o'ylash -> amal -> natija)
agent/tools.py     # vositalar va ruxsat so'rash
agent/memory.py    # xotira va o'zini tahlil qilish
agent/scheduler.py # takrorlanuvchi vazifalar
```
