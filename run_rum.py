import os
import json
import re
import time
import requests

# ----------------- Config -----------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
ZOHO_TOKEN_URL     = os.environ.get("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")
ZOHO_REFRESH_TOKEN = os.environ.get("ZOHO_REFRESH_TOKEN")
ZOHO_CLIENT_ID     = os.environ.get("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.environ.get("ZOHO_CLIENT_SECRET")

RUM_MONITORS = json.loads(os.environ.get("RUM_MONITORS", json.dumps({
    "AWC7": "509934000004443003",
    "IG7":  "509934000004443045",
    "QM7":  "509934000004441003"
})))

# ----------------- Helpers -----------------
def _sanitize_code(text: str) -> str:
    """
    Escape text for Telegram MarkdownV2 (single backticks).
    """
    if text is None:
        return ""
    # Escape special characters per Telegram MarkdownV2 spec
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def send_telegram_message(message_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise Exception("Telegram credentials missing")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "MarkdownV2"
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

def send_monitor_block(monitor_name: str, rum_data):
    lines = []
    for game, avg in rum_data.items():
        emoji = "🚨" if avg > 6 else "⚠️" if avg > 5 else ""
        lines.append(f"{_sanitize_code(game)}  {_sanitize_code(f'{avg:.2f} sec')}  {emoji}")

    if not lines:
        lines.append("No data")

    # Build final message with single backticks
    msg = (
        f"`📊 Site24x7 RUM Summary`\n"
        f"`[{_sanitize_code(monitor_name)}]`\n\n"
        + "\n".join(f"`{line}`" for line in lines)
    )
    send_telegram_message(msg)

# ----------------- Dummy fetch (replace with your API later) -----------------
def fetch_rum_data(rum_id):
    # replace this with your Site24x7 API call
    return {
        "ladder-game": 12.0,
        "gao-gae-jud": 4.38,
        "plinko": 4.07
    }

# ----------------- Main -----------------
def main():
    for name, rum_id in RUM_MONITORS.items():
        rum_data = fetch_rum_data(rum_id)
        send_monitor_block(name, rum_data)

if __name__ == "__main__":
    main()
