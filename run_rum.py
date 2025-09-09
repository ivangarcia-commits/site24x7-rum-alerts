import os
import json
import requests

# === CONFIG ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ZOHO_TOKEN_URL = os.getenv("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")

# Monitors (from GitHub secrets or default empty dict)
RUM_MONITORS = json.loads(os.getenv("RUM_MONITORS", "{}"))

# === FUNCTIONS ===

def refresh_access_token():
    resp = requests.post(
        ZOHO_TOKEN_URL,
        data={
            "refresh_token": ZOHO_REFRESH_TOKEN,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_rum_data(access_token, monitor_id):
    url = f"https://www.site24x7.com/api/rum/reports/summary/{monitor_id}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def format_table(data):
    """Format game data into monospace rows with single backticks."""
    lines = ["`Game           Avg`"]
    for game, avg in data.items():
        emoji = " ❌" if avg >= 5 else ""
        lines.append(f"`{game:<15} {avg:.2f} sec`{emoji}")
    return "\n".join(lines)


def build_message(all_data):
    """Build the full Telegram message with headers and tables."""
    parts = ["`📊 Site24x7 RUM Summary`", ""]
    for monitor_name, games in all_data.items():
        parts.append(f"`{monitor_name}`")
        parts.append(format_table(games))
        parts.append("")  # blank line between monitors
    return "\n".join(parts).strip()


def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    token = refresh_access_token()

    all_data = {}
    for monitor_name, monitor_id in RUM_MONITORS.items():
        rum_json = fetch_rum_data(token, monitor_id)

        # Example: extract games and avg response time
        games = {}
        for g in rum_json.get("top_transactions", []):
            game = g.get("name", "unknown")
            avg = g.get("avg_resp_time", 0)
            games[game] = avg

        all_data[monitor_name] = games

    message = build_message(all_data)
    send_to_telegram(message)


if __name__ == "__main__":
    main()
