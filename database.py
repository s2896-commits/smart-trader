import sqlite3, os, json, base64, threading, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Riyadh")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "trades.db")
AI_CONFIG_FILE = os.path.join(BASE_DIR, "ai_supervisor.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "s2896-commits/smart-trader")
FILE_PATH = "trades_backup.db"

START_CAPITAL = 60.0
FEE_PCT = 0.10
LOCK = threading.RLock()
_dirty = False
_last_backup = 0.0

DEFAULT_CFG = {
    "rsi_min": 30, "rsi_max": 58, "tp_pct": 1.2, "sl_pct": -1.2,
    "trade_size": 6.0, "max_open": 8, "max_per_class": 3,
    "max_hold_h": 24, "cooldown_min": 60, "paused": False,
    "banned": {}, "ban_ref": {}, "ai_report": "المشرف يجمع البيانات...",
}

def now():
    return datetime.now(TZ)

def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

def parse(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)

def run(sql, args=()):
    with LOCK:
        c = sqlite3.connect(DB_NAME, timeout=20)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            cur = c.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            c.commit()
            return rows
        finally:
            c.close()

def get_ai_config():
    cfg = DEFAULT_CFG.copy()
    try:
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
    except Exception:
        pass
    if not isinstance(cfg.get("banned"), dict):
        cfg["banned"] = {}
    if not isinstance(cfg.get("ban_ref"), dict):
        cfg["ban_ref"] = {}
    return cfg

def save_ai_config(cfg):
    try:
        with LOCK, open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception as e:
        print(f"AI config save error: {e}")

def is_cloud_connected():
    return bool(GITHUB_TOKEN and len(GITHUB_TOKEN) > 10)

def _gh():
    return (f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}",
            {"Authorization": f"token {GITHUB_TOKEN}"})

def restore_db_from_github():
    if not is_cloud_connected() or os.path.exists(DB_NAME):
        return
    try:
        url, h = _gh()
        r = requests.get(url, headers=h, timeout=15)
        if r.status_code == 200:
            j = r.json()
            if j.get("content"):
                data = base64.b64decode(j["content"])
            else:
                data = requests.get(j["download_url"], headers=h, timeout=30).content
            with open(DB_NAME, "wb") as f:
                f.write(data)
    except Exception as e:
        print(f"Restore error: {e}")

def backup_db_to_github(force=False):
    global _dirty, _last_backup
    if not is_cloud_connected() or not os.path.exists(DB_NAME):
        return
    if not force and time.time() - _last_backup < 300:
        return
    try:
        tmp = DB_NAME + ".bak"
        with LOCK:
            src, dst = sqlite3.connect(DB_NAME), sqlite3.connect(tmp)
            src.backup(dst)
            dst.close()
            src.close()
        with open(tmp, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        url, h = _gh()
        r = requests.get(url, headers=h, timeout=15)
        data = {"message": "Auto-save trades DB", "content": content}
        if r.status_code == 200:
            data["sha"] = r.json().get("sha")
        res = requests.put(url, headers=h, json=data, timeout=30)
        if res.status_code in (200, 201):
            _dirty, _last_backup = False, time.time()
    except Exception as e:
        print(f"Backup error: {e}")

def backup_if_dirty(force=False):
    if _dirty or force:
        backup_db_to_github(force=force)

def init_db():
    restore_db_from_github()
    run('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, asset_type TEXT,
        entry_price REAL, exit_price REAL, qty REAL DEFAULT 1.0,
        invested_sar REAL DEFAULT 6.0, entry_time TEXT, exit_time TEXT,
        reason TEXT, status TEXT, pnl_sar REAL DEFAULT 0.0, lesson TEXT,
        is_historical INTEGER DEFAULT 0)''')
    
    # فحص وترقية الأعمدة الناقصة تلقائياً لمنع أي انهيار
    existing_cols = [r["name"] for r in run("PRAGMA table_info(trades)")]
    cols_to_add = {
        "qty": "REAL DEFAULT 1.0",
        "invested_sar": "REAL DEFAULT 6.0",
        "pnl_sar": "REAL DEFAULT 0.0",
        "lesson": "TEXT DEFAULT ''",
        "is_historical": "INTEGER DEFAULT 0"
    }
    for col, col_type in cols_to_add.items():
        if col not in existing_cols:
            try:
                run(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
            except Exception:
                pass

def calc_pnl(entry, exit_, invested):
    if not entry or entry <= 0:
        return 0.0
    return round(invested * (exit_ - entry) / entry - invested * FEE_PCT / 100 * 2, 2)

def log_trade(symbol, asset_type, price, reason, is_historical=0, entry_time=None,
              exit_time=None, exit_price=None, status="OPEN", pnl_sar=0.0,
              lesson="", invest_amount=6.0):
    global _dirty
    p = float(price) if price else 1.0
    invest_usd = invest_amount / 3.75 if (symbol.endswith("-USD") or not symbol.endswith(".SR")) else invest_amount
    qty = round(invest_usd / p, 4) if p > 0 else 1.0

    run('''INSERT INTO trades (symbol, asset_type, entry_price, exit_price, qty, invested_sar,
           entry_time, exit_time, reason, status, pnl_sar, lesson, is_historical)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (symbol, asset_type, round(p, 4),
         round(float(exit_price), 4) if exit_price else None, qty, invest_amount,
         entry_time or fmt(now()), exit_time, reason, status,
         round(float(pnl_sar or 0.0), 2), lesson, is_historical))
    if not is_historical:
        _dirty = True

def update_open_trades(prices):
    global _dirty
    cfg = get_ai_config()
    t_now = now()
    for t in run("SELECT * FROM trades WHERE status='OPEN' AND is_historical=0"):
        cur = prices.get(t["symbol"])
        if cur is None:
            continue
        entry = t["entry_price"]
        pct = ((cur - entry) / entry) * 100 if entry else 0
        inv = float(t.get("invested_sar") or 6.0)
        pnl = calc_pnl(entry, cur, inv)
        try:
            age_h = (t_now - parse(t["entry_time"])).total_seconds() / 3600
        except Exception:
            age_h = 0
        if pct >= cfg["tp_pct"]:
            st, lesson = "WON", f"وصل هدف الربح (+{cfg['tp_pct']}%)."
        elif pct <= cfg["sl_pct"]:
            st, lesson = "LOST", f"فعّل وقف الخسارة ({cfg['sl_pct']}%) — خسارة محسوبة ({pnl} ر.س)."
        elif age_h >= cfg["max_hold_h"]:
            st = "WON" if pnl > 0 else "LOST"
            lesson = f"خروج بالوقت بعد {int(age_h)} ساعة ({pct:+.2f}%)."
        else:
            run("UPDATE trades SET pnl_sar=?, lesson=? WHERE id=?",
                (pnl, f"التغير الحالي: {pct:+.2f}%", t["id"]))
            continue
        run("UPDATE trades SET exit_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
            (round(cur, 4), fmt(t_now), st, pnl, lesson, t["id"]))
        _dirty = True

def open_symbols():
    return [r["symbol"] for r in run("SELECT symbol FROM trades WHERE status='OPEN' AND is_historical=0")]

def on_cooldown(symbol, minutes):
    r = run("SELECT exit_time FROM trades WHERE symbol=? AND is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
    if not r or not r[0]["exit_time"]:
        return False
    try:
        return now() - parse(r[0]["exit_time"]) < timedelta(minutes=minutes)
    except Exception:
        return False

def get_trades(historical=0, limit=60):
    return run("SELECT * FROM trades WHERE is_historical=? ORDER BY id DESC LIMIT ?", (historical, limit))

def _stats(closed):
    closed = sorted(closed, key=lambda t: t.get("exit_time") or "")
    n = len(closed)
    won = sum(1 for t in closed if t.get("status") == "WON")
    gw = sum(float(t.get("pnl_sar") or 0) for t in closed if float(t.get("pnl_sar") or 0) > 0)
    gl = -sum(float(t.get("pnl_sar") or 0) for t in closed if float(t.get("pnl_sar") or 0) < 0)
    cum = peak = dd = 0.0
    curve = []
    for t in closed:
        val = float(t.get("pnl_sar") or 0)
        cum += val
        curve.append(round(cum, 2))
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"n": n, "won": won, "lost": n - won,
            "win_rate": round(won / n * 100, 1) if n else None,
            "pnl": round(cum, 2), "pf": round(gw / gl, 2) if gl else None,
            "expectancy": round(cum / n, 3) if n else None,
            "max_dd": round(dd, 2), "curve": curve}

def get_summary():
    live = run("SELECT * FROM trades WHERE is_historical=0")
    closed = [t for t in live if t.get("status") != "OPEN"]
    opn = [t for t in live if t.get("status") == "OPEN"]
    st = _stats(closed)
    invested = round(sum(float(t.get("invested_sar") or 6.0) for t in opn), 2)
    floating = round(sum(float(t.get("pnl_sar") or 0.0) for t in opn), 2)
    return {"stats": st, "invested": invested, "floating": floating,
            "open_count": len(opn),
            "wallet": round(START_CAPITAL + st["pnl"] + floating, 2),
            "cash": round(max(0.0, START_CAPITAL + st["pnl"] - invested), 2)}

def get_lab():
    hist = run("SELECT * FROM trades WHERE is_historical=1")
    st = _stats([t for t in hist if t.get("status") != "OPEN"])
    st["trades"] = get_trades(1, 100)
    return st

init_db()
