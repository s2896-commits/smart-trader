import sqlite3
import os
import json
import base64
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "trades.db")
AI_CONFIG_FILE = os.path.join(BASE_DIR, "ai_supervisor.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "s2896-commits/smart-trader")
FILE_PATH = "trades_backup.db"

DEFAULT_AI_CONFIG = {
    "rsi_min": 35,
    "rsi_max": 54,
    "tp_pct": 1.4,
    "sl_pct": -1.2,
    "require_uptrend": True,
    "banned_symbols": [],
    "ai_report": "تم تفعيل المشرف الذكي: تم خفض سقف RSI إلى 54 لمنع الشراء في القمم وتفعيل فلتر المسار الصاعد."
}

def get_ai_config():
    if os.path.exists(AI_CONFIG_FILE):
        try:
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_AI_CONFIG.copy()

def save_ai_config(cfg):
    try:
        with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception as e:
        print(f"AI config save error: {e}")

def is_cloud_connected():
    return bool(GITHUB_TOKEN and len(GITHUB_TOKEN) > 10)

def restore_db_from_github():
    if not is_cloud_connected() or os.path.exists(DB_NAME):
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()['content'])
            with open(DB_NAME, 'wb') as f:
                f.write(content)
    except Exception as e:
        print(f"Restore error: {e}")

def backup_db_to_github():
    if not is_cloud_connected() or not os.path.exists(DB_NAME):
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        with open(DB_NAME, 'rb') as f:
            content = base64.b64encode(f.read()).decode('utf-8')
        r = requests.get(url, headers=headers, timeout=10)
        sha = r.json().get('sha') if r.status_code == 200 else None
        data = {"message": "Auto-save trades DB", "content": content}
        if sha:
            data["sha"] = sha
        requests.put(url, headers=headers, json=data, timeout=10)
    except Exception as e:
        print(f"Backup error: {e}")

def init_db():
    restore_db_from_github()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        asset_type TEXT,
        entry_price REAL,
        exit_price REAL,
        qty REAL DEFAULT 1.0,
        invested_sar REAL DEFAULT 20.0,
        entry_time TEXT,
        exit_time TEXT,
        reason TEXT,
        status TEXT,
        pnl_sar REAL DEFAULT 0.0,
        lesson TEXT,
        is_historical INTEGER DEFAULT 0
    )''')
    c.execute("PRAGMA table_info(trades)")
    cols = [col[1] for col in c.fetchall()]
    if "qty" not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN qty REAL DEFAULT 1.0")
    if "invested_sar" not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN invested_sar REAL DEFAULT 20.0")
    if "pnl_sar" not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN pnl_sar REAL DEFAULT 0.0")
    if "is_historical" not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN is_historical INTEGER DEFAULT 0")
    
    # تنظيف أي صفقات مفتوحة زائدة عن حد الـ 60 ريال (الحد الأقصى 3 صفقات)
    c.execute("SELECT id FROM trades WHERE status = 'OPEN' AND is_historical = 0 ORDER BY id ASC")
    open_ids = [r[0] for r in c.fetchall()]
    if len(open_ids) > 3:
        for extra_id in open_ids[3:]:
            c.execute("DELETE FROM trades WHERE id = ?", (extra_id,))
    conn.commit()
    conn.close()

def clear_old_backtest():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM trades WHERE is_historical = 1")
    conn.commit()
    conn.close()

def log_trade(symbol, asset_type, price, reason, is_historical=0, entry_time=None, exit_time=None, exit_price=None, status="OPEN", pnl_sar=0.0, lesson=""):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = entry_time if entry_time else datetime.now().strftime("%Y-%m-%d %H:%M")
    invest_sar = 20.0
    invest_usd = invest_sar / 3.75
    qty = round(invest_usd / price, 4) if price > 0 else 1.0

    c.execute('''INSERT INTO trades 
        (symbol, asset_type, entry_price, exit_price, qty, invested_sar, entry_time, exit_time, reason, status, pnl_sar, lesson, is_historical) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (symbol, asset_type, round(price, 4), round(exit_price, 4) if exit_price else None, 
         qty, invest_sar, now, exit_time, reason, status, round(pnl_sar, 2), lesson, is_historical))
    conn.commit()
    conn.close()
    if not is_historical:
        backup_db_to_github()

def update_open_trades(current_prices):
    cfg = get_ai_config()
    tp_target = cfg.get("tp_pct", 1.4)
    sl_target = cfg.get("sl_pct", -1.2)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status = 'OPEN' AND is_historical = 0")
    open_trades = [dict(r) for r in c.fetchall()]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    closed_any = False

    for t in open_trades:
        sym = t['symbol']
        if sym in current_prices:
            curr = current_prices[sym]
            entry = t['entry_price']
            qty = t.get('qty') or 1.0
            change_pct = ((curr - entry) / entry) * 100
            diff_usd = (curr - entry) * qty
            live_pnl_sar = round(diff_usd * 3.75, 2)

            if change_pct >= tp_target:
                lesson = f"أغلقت بربح (+{tp_target}%): استراتيجية المشرف الذكي أصابت الهدف."
                c.execute("UPDATE trades SET exit_price=?, exit_time=?, status='WON', pnl_sar=?, lesson=? WHERE id=?",
                          (round(curr, 4), now, live_pnl_sar, lesson, t['id']))
                closed_any = True
            elif change_pct <= sl_target:
                lesson = f"وقف خسارة ({sl_target}%): حماية المحفظة وسيتم مراجعة السبب بواسطة المشرف الذكي."
                c.execute("UPDATE trades SET exit_price=?, exit_time=?, status='LOST', pnl_sar=?, lesson=? WHERE id=?",
                          (round(curr, 4), now, live_pnl_sar, lesson, t['id']))
                closed_any = True
            else:
                lesson = f"السعر الحالي: {round(curr, 4)}$ ({change_pct:+.2f}%) | الهدف +{tp_target}%"
                c.execute("UPDATE trades SET pnl_sar=?, lesson=? WHERE id=?",
                          (live_pnl_sar, lesson, t['id']))
    conn.commit()
    conn.close()
    if closed_any:
        backup_db_to_github()

def get_all_trades():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 60")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

init_db()
