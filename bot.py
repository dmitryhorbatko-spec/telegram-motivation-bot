import os, random, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from openai import OpenAI

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SEND_HOUR = int(os.environ.get("SEND_HOUR", "9"))
TZ_NAME = os.environ.get("TZ", "Europe/Kyiv")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Ты пишешь ОДНО очень короткое мотивирующее предложение (до 120 символов), "
    "по-дружески, без пафоса, без хэштегов и кавычек. Язык: RU ."
)
USER_PROMPTS = [
    "Придумай короткое вдохновляющее сообщение, чтобы человек поверил в себя.",
    "Сгенерируй одно позитивное предложение для утреннего старта.",
    "Дай одну мотивационную фразу без лишних слов."
]

def now_in_kyiv() -> datetime:
    return datetime.now(ZoneInfo(TZ_NAME))

def is_send_time(dt: datetime) -> bool:
    return dt.hour == SEND_HOUR

def generate_text() -> str:
    prompt = random.choice(USER_PROMPTS)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        max_tokens=60,
        temperature=0.9
    )
    text = resp.choices[0].message.content.strip()
    text = text.replace("#", "").strip('«»"“”‘’').strip()
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0] + "…"
    return text

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

def main():
    dt = now_in_kyiv()
    if not is_send_time(dt):
        print(f"Not 09:00 in {TZ_NAME} (now {dt.strftime('%Y-%m-%d %H:%M')}). Skipping.")
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
