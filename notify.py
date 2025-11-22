import os
import requests
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

SESSION = requests.Session()
if HTTP_PROXY or HTTPS_PROXY:
    SESSION.proxies.update({
        "http": HTTP_PROXY or HTTPS_PROXY,
        "https": HTTPS_PROXY or HTTP_PROXY,
    })


def send_telegram_message(text: str, parse_mode: Optional[str] = None) -> bool:
    """
    Send a message to the configured Telegram chat.
    Returns True if sent, False otherwise.
    """
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("[notify] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured. Skipping send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = SESSION.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            return True
        print(f"[notify] Telegram send failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[notify] Error sending Telegram message: {e}")
        return False
