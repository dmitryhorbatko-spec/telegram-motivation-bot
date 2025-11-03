import os, json, sys, re, random
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from openai import OpenAI
from pathlib import Path

# ---- ENV ----
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SEND_HOUR = int(os.environ.get("SEND_HOUR", "9"))
TZ_NAME = os.environ.get("TZ", "Europe/Kyiv")
MINUTE_WINDOW = int(os.environ.get("MINUTE_WINDOW", "59"))

# ---- OpenAI ----
client = OpenAI(api_key=OPENAI_API_KEY)

# ---- История (для анти-повторов) ----
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "sent_history.json"))
HISTORY_LIMIT = 200  # сколько последних фраз помнить

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_history(history):
    try:
        HISTORY_FILE.write_text(json.dumps(history[-HISTORY_LIMIT:], ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception:
        pass

# --- Системный промпт (убрали шаблон "у тебя всё получится") ---
SYSTEM_PROMPT = (
    "Пиши ОДНО короткое поддерживающее утверждение на русском (5–9 слов). "
    "Спокойный тёплый тон. НИКАКИХ призывов к действию, пафоса, слов 'сегодня', "
    "'вперёд/вперед', 'сделай/сделать', 'не упусти', 'шаг'. "
    "Без восклицаний, кавычек и эмодзи. Всегда заканчивай точкой. "
    "Можно от первого лица ('я верю/знаю/считаю'), можно от второго ('у тебя...').\n\n"
    "Примеры стиля (это только примеры, не копируй их дословно):\n"
    "я на твоей стороне, даже когда тихо.\n"
    "ты важен, даже если сомневаешься.\n"
    "я вижу в тебе спокойную силу.\n"
)

# --- Запрещённые слова/шаблоны и заезженные конструкции ---
FORBIDDEN = [
    "сегодня","вперед","вперёд","сделай","сделать","давай","шаг","не упусти",
    "отличный день","классное","вдохновляющее"
]
# Точные или почти точные штампы, которые часто лезут
BAN_PHRASES = [
    "у тебя всё получится",
    "я верю, что у тебя всё получится",
    "ты справишься",
    "я верю, что ты справишься",
    "я знаю, что ты справишься",
]

def now_local():
    from datetime import datetime as dt
    return dt.now(ZoneInfo(TZ_NAME))

def is_send_time(dt):
    # отправляем только в окне HH:00..HH:MINUTE_WINDOW-1
    return dt.hour == SEND_HOUR and 0 <= dt.minute < MINUTE_WINDOW

def normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("—", " ").replace("-", " ")
    t = re.sub(r"[«»\"“”‘’#]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t

def ngrams(words, n=2):
    return set(tuple(words[i:i+n]) for i in range(len(words)-n+1)) if len(words) >= n else set()

def too_similar(a: str, b: str, thr: float = 0.65) -> bool:
    # Jaccard по биграммам слов
    aw = normalize(a).strip(".").split()
    bw = normalize(b).strip(".").split()
    A = ngrams(aw, 2)
    B = ngrams(bw, 2)
    if not A or not B:
        return False
    jac = len(A & B) / len(A | B)
    return jac >= thr

def conforms_style(text: str) -> bool:
    t = normalize(text)
    words = [w for w in t.split() if w]
    return (
        5 <= len(words) <= 9 and
        t.endswith(".") and
        "!" not in text and
        not any(bad in t for bad in FORBIDDEN)
    )

def is_banned(text: str) -> bool:
    t = normalize(text).rstrip(".")
    if any(t == normalize(p) or t.startswith(normalize(p)) for p in BAN_PHRASES):
        return True
    # простая проверка на штампы типа "у тебя всё получится" / "ты справишься"
    if re.search(r"\b(получится|справишься)\b", t):
        return True
    return False

def generate_candidates(n: int = 12) -> list:
    # Просим модель выдать список строк, по одной на строку
    user_prompt = (
        f"Предложи {n} разных вариантов, по одному на строку. "
        "Не нумеруй и не добавляй лишних символов."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=200,
        temperature=1.0,
        top_p=0.9,
        presence_penalty=0.7,
        frequency_penalty=0.7,
    )
    text = resp.choices[0].message.content.strip()
    lines = [re.sub(r"^\s*[-\d\.\)]\s*", "", l).strip() for l in text.splitlines() if l.strip()]
    # Санитайз и точка в конце
    cleaned = []
    for l in lines:
        l = l.replace("#", "").strip('«»"“”‘’').strip()
        if not l.endswith("."):
            l = l.rstrip(".") + "."
        cleaned.append(l)
    return cleaned

def pick_fresh(candidates: list, history: list) -> str | None:
    # фильтруем по стилю, бану, новизне по отношению к истории и внутри пакета
    ok = []
    for c in candidates:
        if not conforms_style(c): 
            continue
        if is_banned(c):
            continue
        if any(too_similar(c, h) for h in history[-HISTORY_LIMIT:]):
            continue
        ok.append(c)

    # Избавимся от взаимно похожих внутри пакета
    unique = []
    for c in ok:
        if any(too_similar(c, u) for u in unique):
            continue
        unique.append(c)

    return random.choice(unique) if unique else None

def fallback(history: list) -> str:
    # Ручной генератор безопасной фразы, если модель не справилась
    templates = [
        "я рядом, даже если молчишь.",
        "твоя тишина для меня понятна.",
        "я ценю твоё спокойное усилие.",
        "ты можешь опереться на меня.",
        "ты важен, даже если сомневаешься.",
        "я вижу, как ты держишься.",
    ]
    random.shuffle(templates)
    for t in templates:
        if not any(too_similar(t, h) for h in history):
            return t if t.endswith(".") else t + "."
    return "я рядом, даже если молчишь."

def generate_text() -> str:
    history = load_history()
    for _ in range(2):  # две попытки с батчем
        cand = generate_candidates(12)
        choice = pick_fresh(cand, history)
        if choice:
            history.append(choice)
            save_history(history)
            return choice
    # Фолбек
    text = fallback(history)
    history.append(text)
    save_history(history)
    return text

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

def main():
    dt = now_local()
    if not is_send_time(dt):
        print(f"Skipping: now {dt.strftime('%Y-%m-%d %H:%M')} {TZ_NAME}, target hour={SEND_HOUR}, window={MINUTE_WINDOW}m.")
        return
    text = generate_text()
    send_telegram(text)
    print("Message sent:", text)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        raise
