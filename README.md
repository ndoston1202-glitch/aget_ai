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

## O'rnatish

```bash
git clone https://github.com/ndoston1202-glitch/aget_ai
cd aget_ai
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

API kalitini [console.anthropic.com](https://console.anthropic.com) dan oling va o'rnating:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."     # Windows: set ANTHROPIC_API_KEY=sk-ant-...
```

## Ishga tushirish

```bash
python main.py
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
| `AGENT_MODEL` | `claude-opus-5-5` | Ishlatiladigan model |
| `AGENT_EFFORT` | `high` | O'ylash darajasi: `low`, `medium`, `high`, `xhigh`, `max` |
| `AGENT_WORKSPACE` | `./workspace` | Agent ishlaydigan papka |
| `AGENT_DATA_DIR` | `./data` | Xotira, vazifalar va loglar |

## Tuzilma

```
main.py            # CLI va fon rejimi
agent/core.py      # agent sikli (o'ylash -> amal -> natija)
agent/tools.py     # vositalar va ruxsat so'rash
agent/memory.py    # xotira va o'zini tahlil qilish
agent/scheduler.py # takrorlanuvchi vazifalar
```
