#!/usr/bin/env python3
import os, json, re, time, html
from datetime import datetime
import requests

# ----------------------
# Config (from env)
# ----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_TOKEN_URL     = os.getenv("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")

# Optional: supply JSON string of monitors as a secret or env var; fallback to defaults
RUM_MONITORS = json.loads(os.getenv("RUM_MONITORS", json.dumps({
    "awc7": "509934000004443003",
    "qm7":  "509934000004443045",
    "ig7":  "509934000004441003"
})))

# ----------------------
# Helpers
# ----------------------
def _sanitize_code(text: str) -> str:
    return str(text).replace("`", "'")

def clean_path(path: str) -> str:
    """Return cleaned path, or empty string to exclude the row."""
    if not isinstance(path, str):
        return ""
    # Exclude /syn33/*/slots/games/* anywhere
    if re.search(r"/syn33/[^/]+/slots/games/[^/]+", path):
        return ""
    path = re.sub(r"^/asia-ig7/", "", path)
    path = re.sub(r"^/syn33/\*/", "", path)
    path = re.sub(r"/games/\*/", "", path)
    path = re.sub(r"/\*/index\.html$", "", path)
    path = re.sub(r"/+", "/", path).strip("/")
    return path

def refresh_access_token():
    if not (ZOHO_REFRESH_TOKEN and ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET):
        raise Exception("Zoho credentials missing")
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
    j = r.json()
    # Normalize: the API sometimes nests in different shapes
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

# ----------------------
# Formatting (HTML <pre> monospace)
# ----------------------
def format_monitor_lines(rum_data):
    rows = []
    for item in rum_data or []:
        raw = item.get("name", "") or ""
        path = clean_path(raw)
        if not path or path.startswith("prod/") or path.strip() in {"*", ""}:
            continue
        try:
            avg_s = float(item.get("average_response_time", 0)) / 1000.0
        except (TypeError, ValueError):
            avg_s = 0.0
        emoji = "🚨" if avg_s > 6 else "⚠️" if avg_s > 5 else ""
        game = _sanitize_code(path)
        avg_txt = f"{avg_s:.2f} sec"
        rows.append((game, avg_s, avg_txt, emoji))

    if not rows:
        return ["No data"]

    rows.sort(key=lambda x: x[1], reverse=True)  # highest first

    max_game_len = max(len(r[0]) for r in rows)
    game_w = max(20, max_game_len + 2)
    avg_w = max(len(r[2]) for r in rows)

    lines = [f"{'Game'.ljust(game_w)}{'Avg'.rjust(avg_w)}", ""]
    for game, _, avg_txt, emoji in rows:
        # Escape text for HTML inside <pre>
        safe_game = html.escape(game)
        safe_avg = html.escape(avg_txt)
        line = f"{safe_game.ljust(game_w)}{safe_avg.rjust(avg_w)}   {emoji}"
        lines.append(line)
        lines.append("")  # spacing between rows

    return lines

# ----------------------
# Telegram sending (HTML parse_mode)
# ----------------------
def send_telegram_message_html(monitor_name, lines):
    """
    Send the lines wrapped in <pre> so Telegram uses fixed-width
    Split into chunks if very long.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise Exception("Telegram credentials missing")

    divider = "-" * 40
    monitor_safe = html.escape(_sanitize_code(monitor_name))

    # create blocks of lines sized by characters
    max_chars = 3200
    cur = []
    cur_len = 0

    def _send_block(block_lines):
        body = "\n".join(block_lines)
        pre = f"<pre>{body}</pre>"
        text = f"📊 Site24x7 RUM Summary\n\n[{monitor_safe}]\n\n{pre}\n{divider}"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        print("Sent chunk, length:", len(text))

    for line in lines:
        add_len = len(line) + 1
        if cur and (cur_len + add_len > max_chars):
            _send_block(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += add_len

    if cur:
        _send_block(cur)

# ----------------------
# Main
# ----------------------
def main():
    print("Start:", datetime.utcnow().isoformat(), "UTC")
    token = refresh_access_token()
    for name, rum_id in RUM_MONITORS.items():
        try:
            rum_data = fetch_rum_data(rum_id, token)
            lines = format_monitor_lines(rum_data)
            send_telegram_message_html(name, lines)
            time.sleep(1)  # small delay between monitors
        except Exception as e:
            print("Error processing", name, str(e))
            # best-effort notify
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                msg = f"Error for [{_sanitize_code(name)}]: {html.escape(str(e))}"
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
            except Exception:
                pass

if __name__ == "__main__":
    main()
