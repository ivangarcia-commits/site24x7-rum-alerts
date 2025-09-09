# run_rum.py
import os
import json
import re
import time
import requests

# === ENV VARS ===
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
ZOHO_TOKEN_URL     = os.environ.get("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")
ZOHO_REFRESH_TOKEN = os.environ.get("ZOHO_REFRESH_TOKEN")
ZOHO_CLIENT_ID     = os.environ.get("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.environ.get("ZOHO_CLIENT_SECRET")

RUM_MONITORS = json.loads(os.environ.get("RUM_MONITORS", json.dumps({
    "AWC7": "509934000004443003",
    "IG7":  "509934000004441003",
    "QM7":  "509934000004443045"
})))


# ----------------- Helpers -----------------

def _sanitize_code(text: str) -> str:
    return str(text).replace("`", "'")

def clean_path(path: str) -> str:
    if not isinstance(path, str):
        return ""
    if re.search(r"^/syn33/[^/]+/slots/games/[^/]+/?", path):
        return ""
    path = re.sub(r"^/asia-ig7/", "", path)
    path = re.sub(r"^/syn33/\*/", "", path)
    path = re.sub(r"^/games/\*/", "", path)
    path = re.sub(r"/games/\*/", "", path)
    path = re.sub(r"/\*/index\.html$", "", path)
    path = re.sub(r"/+", "/", path).strip("/")
    return path


# ----------------- Zoho API -----------------

def refresh_access_token():
    if not (ZOHO_REFRESH_TOKEN and ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET):
        raise Exception("Zoho credentials missing in environment variables")
    params = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    r = requests.post(ZOHO_TOKEN_URL, data=params, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

def fetch_rum_data(rum_id, token):
    url = f"https://www.site24x7.com/api/rum/web/view/{rum_id}/wt/list/avgRT/H"
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    if "data" not in data:
        return []
    data_field = data["data"]
    if isinstance(data_field, list):
        return data_field
    if isinstance(data_field, dict):
        if "list" in data_field and isinstance(data_field["list"], list):
            return data_field["list"]
        for v in data_field.values():
            if isinstance(v, list):
                return v
    return []


# ----------------- Formatting -----------------

def format_monitor_lines(rum_data):
    rows = []
    for item in rum_data or []:
        raw_path = item.get("name", "") or ""
        path = clean_path(raw_path)
        if not path:
            continue
        if path.startswith("prod/") or path.strip() in {"*", ""}:
            continue

        try:
            avg_s = float(item.get("average_response_time", 0)) / 1000.0
        except (TypeError, ValueError):
            avg_s = 0.0

        emoji = "🚨" if avg_s > 6 else "⚠️" if avg_s > 5 else ""
        game = _sanitize_code(path)
        avg_str = f"{avg_s:.2f} sec"
        rows.append((game, avg_s, avg_str, emoji))

    if not rows:
        return ["No data"]

    rows.sort(key=lambda x: x[1], reverse=True)

    max_game_len = max(len(r[0]) for r in rows)
    game_w = max(20, max_game_len + 2)
    max_avg_len = max(len(r[2]) for r in rows)
    avg_w = max(8, max_avg_len)

    lines = [f"{'Game'.ljust(game_w)}{'Avg'.rjust(avg_w)}   ", ""]
    for game, _, avg_str, emoji in rows:
        line = f"{game.ljust(game_w)}{avg_str.rjust(avg_w)}   {emoji}"
        lines.append(line)
        lines.append("")
    return lines


# ----------------- Telegram -----------------

def send_telegram_message(message_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise Exception("Telegram credentials missing in environment variables")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "MarkdownV2"
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()


def send_monitor_block(monitor_name: str, rum_data):
    lines = format_monitor_lines(rum_data)
    divider = "-" * 40
    mn = _sanitize_code(monitor_name)

    body = "\n".join(lines)
    msg = f"`📊 Site24x7 RUM Summary`\n\n`{mn}`\n\n`{body}`\n{divider}"
    send_telegram_message(msg)


# ----------------- Main -----------------

def main():
    token = refresh_access_token()
    for name, rum_id in RUM_MONITORS.items():
        try:
            rum_data = fetch_rum_data(rum_id, token)
            send_monitor_block(name, rum_data)
        except Exception as e:
            err_msg = f"`📊 Site24x7 RUM Summary`\n\n`{_sanitize_code(name)}`\n\n❌ {_sanitize_code(str(e))}"
            send_telegram_message(err_msg)


if __name__ == "__main__":
    main()
