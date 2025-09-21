# run_rum.py
import os
import json
import re
import time
import requests
from datetime import datetime, timezone, timedelta
import sys

# ----------------- Config from env (GitHub secrets) -----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

ZOHO_TOKEN_URL     = os.getenv("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")

# RUM monitors mapping (string JSON in secret optional). Defaults to your 3 monitors.
RUM_MONITORS = json.loads(os.getenv("RUM_MONITORS", json.dumps({
    "AWC7": "509934000004443003",
    "IG7" : "509934000004441003",
    "QM7" : "509934000004443045"
})))

# ----------------- Helpers -----------------
def _sanitize_backticks(text: str) -> str:
    """Replace backticks so we can safely wrap the whole line inside single backticks."""
    if text is None:
        return ""
    return str(text).replace("`", "'")

def clean_path(path: str) -> str:
    """Return cleaned path or empty string to exclude."""
    if not isinstance(path, str):
        return ""
    if re.search(r"/syn33/[^/]+/slots/games/[^/]+", path):
        return ""
    path = re.sub(r"^/asia-ig7/", "", path)
    path = re.sub(r"^/syn33/\*/", "", path)
    path = re.sub(r"/games/\*/", "", path)
    path = re.sub(r"/\*/index\.html$", "", path)
    path = re.sub(r"/+", "/", path).strip("/")
    return path

# ----------------- Zoho token & Site24x7 fetch -----------------
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
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    j = r.json()

    try:
        fname = f"/tmp/rum_debug_{rum_id}.json"
        with open(fname, "w", encoding="utf-8") as fh:
            json.dump(j, fh, indent=2)
    except Exception:
        pass

    if "data" not in j:
        return []
    data_field = j["data"]
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
    """
    Build aligned table lines (monospace): Game (left), Avg (right), Emoji.
    Only include rows >= 5 seconds.
    """
    rows = []
    for item in rum_data or []:
        raw_path = item.get("name", "") or ""
        path = clean_path(raw_path)
        if not path:
            continue
        if path.startswith("prod/") or path.strip() in {"*", ""}:
            continue

        try:
            avg_ms = float(item.get("average_response_time", 0))
            avg_s = avg_ms / 1000.0
        except Exception:
            avg_s = 0.0

        # 🚨 Skip anything below 5s
        if avg_s < 5.0:
            continue

        emoji = "🚨" if avg_s > 6 else "⚠️"
        game = _sanitize_backticks(path)
        avg_str = f"{avg_s:.2f} sec"
        rows.append((game, avg_s, avg_str, emoji))

    if not rows:
        return ["No data ≥ 5 sec"]

    # sort by avg desc
    rows.sort(key=lambda x: x[1], reverse=True)

    # dynamic column widths
    max_game_len = max(len(r[0]) for r in rows)
    game_w = max(20, max_game_len + 2)
    max_avg_len = max(len(r[2]) for r in rows)
    avg_w = max(8, max_avg_len)

    lines = []
    header = f"{'Game'.ljust(game_w)}{'Avg'.rjust(avg_w)}"
    lines.append(header)
    lines.append("")  # blank line

    for game, _, avg_str, emoji in rows:
        line = f"{game.ljust(game_w)}{avg_str.rjust(avg_w)}   {emoji}"
        lines.append(line)
        lines.append("")

    return lines

# ----------------- Telegram sending -----------------
def send_telegram_message_safe(message_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise Exception("Telegram credentials missing in environment variables")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "MarkdownV2"
    }

    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                print("Telegram sent (len=%d)" % len(message_text))
                return True
            else:
                print(f"Telegram HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print("Telegram send exception:", str(e))
        time.sleep(2 ** attempt)
    print("Telegram sending failed after retries.")
    return False

def send_monitor_block(monitor_name: str, rum_data):
    lines = format_monitor_lines(rum_data)
    divider = "-" * 40

    msg_lines = []
    msg_lines.append(f"`📊 Site24x7 RUM Summary`")
    msg_lines.append("")
    msg_lines.append(f"`[{_sanitize_backticks(monitor_name)}]`")
    msg_lines.append("")

    for ln in lines:
        safe_ln = _sanitize_backticks(ln)
        msg_lines.append(f"`{safe_ln}`")

    msg_lines.append(f"`{divider}`")

    message_text = "\n".join(msg_lines)
    send_telegram_message_safe(message_text)

# ----------------- Main -----------------
def main():
    # Philippine Time (UTC+8)
    ph_tz = timezone(timedelta(hours=8))
    now = datetime.now(ph_tz)

    # Only run at exact hour
    if now.minute != 0:
        print(f"Skipping run at {now.strftime('%Y-%m-%d %H:%M:%S')} PH (not top of hour)")
        sys.exit(0)

    print("Run start:", now.strftime("%Y-%m-%d %H:%M:%S"), "PH")
    token = refresh_access_token()
    for name, rum_id in RUM_MONITORS.items():
        print("Processing monitor:", name, rum_id)
        try:
            rum_data = fetch_rum_data(rum_id, token)
            send_monitor_block(name, rum_data)
            time.sleep(1)
        except Exception as e:
            print("Error for monitor", name, str(e))
            try:
                err_msg = f"`📊 Site24x7 RUM Summary`\n`[{_sanitize_backticks(name)}]`\n\n`❌ { _sanitize_backticks(str(e)) }`"
                send_telegram_message_safe(err_msg)
            except Exception as e2:
                print("Failed to send error via Telegram:", e2)
            continue

if __name__ == "__main__":
    main()
