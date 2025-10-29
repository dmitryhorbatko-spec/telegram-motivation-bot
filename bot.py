import os, random, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from openai import OpenAI

# ---- ENV ----
BOT_TOKEN = os.environ["BOT_TOKEN"]          # токен бота из @BotFather (через Secrets)
CHAT_ID = os.environ["CHAT_ID"]              # числовой chat_id
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SEND_HOUR = int(os.environ.get("SEND_HOUR", "9"))       # 9 = 09:00
TZ_NAME = os.environ.get("TZ", "Europe/Kyiv")
MINUTE_WINDOW = int(os.environ.get("MINUTE_WINDOW", "59"))  # окно в минутах, по умолчанию 10

# ---- OpenAI ----
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Новый системный промпт: коротко, спокойно, без коуч-тонов ---
SYSTEM_PROMPT = (
    "Пиши ОДНО короткое поддерживающее утверждение на русском (5–9 слов). "
    "Спокойный тёплый тон. НИКАКИХ призывов к действию, пафоса, слов 'сегодня', "
    "'вперёд/вперед', 'сделай/сделать', 'не упусти', 'шаг'. "
    "Без восклицаний, кавычек и эмодзи. Всегда заканчивай точкой. "
    "Можно от первого лица ('я считаю/верю/знаю'), можно от второго ('у тебя...').\n\n"
    "Примеры стиля:\n"
    "считаю, что у тебя есть шанс на лучшую жизнь.\n"
    "таких как ты нет больше.\n"
    "у тебя всё получится.\n"
)

# Запрещённые слова/шаблоны (чтобы отсекать 'коучевый' тон)
FORBIDDEN = [
    "сегодня", "вперед", "вперёд", "сделай", "сделать", "давай", "шаг",
    "не упусти", "отличный день", "классное", "вдохновляющее"
]

def now_local():
    return __import__("datetime").datetime.now(ZoneInfo(TZ_NAME))

def is_send_time(dt):
    # Отправляем только в окне HH:00..HH:09 (по умолчанию 10 минут)
    return dt.hour == SEND_HOUR and 0 <= dt.minute < MINUTE_WINDOW

def _conforms_style(text: str) -> bool:
    t = text.lower().strip()
    words = [w for w in t.replace("—", " ").split() if w]
    return (
        5 <= len(words) <= 9 and
        t.endswith(".") and
        "!" not in t and
        not any(bad in t for bad in FORBIDDEN)
    )

def generate_text() -> str:
    user_prompt = "Сформулируй одну такую фразу в указанном стиле."
    # Несколько попыток, чтобы строго попасть в стиль
    for _ in range(4):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=60,
            temperature=0.7,
            presence_penalty=0.0,
            frequency_penalty=0.2
        )
        text = resp.choices[0].message.content.strip()
        # Санитайз
        text = text.replace("#", "").strip('«»"“”‘’').strip()
        if _conforms_style(text):
            return text
    # Фолбек, если модель упёрлась
    return "я верю, у тебя всё получится."

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = __import__("requests").post(url, data={"chat_id": CHAT_ID, "text": text})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

def main():
    dt = now_local()
    if not is_send_time(dt):
        print(f"Skipping: now {dt.strftime('%Y-%m-%d %H:%M')} {TZ_NAME}, target hour={SEND_HOUR}, window={MINUTE_WINDOW}m.")
        return
    text = generate_text()
    send_telegram(text)
    print("Message sent.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        raise
