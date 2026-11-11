import sqlite3, os, json, base64, threading, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Riyadh")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "trades.db")
AI_CONFIG_FILE = os.path.join(BASE_DIR, "ai_supervisor.json")
BRAIN_FILE = os.path.join(BASE_DIR, "ai_brain.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "s2896-commits/smart-trader")
FILE_PATH = "trades_backup.db"

START_CAPITAL = 60.0
SCALE_FACTOR = 10.0
FEE_PCT = 0.10
LOCK = threading.RLock()
_dirty = False
_last_backup = 0.0

DEFAULT_CFG = {
    "rsi_min": 32, "rsi_max": 58,
    "tp_pct": 1.1, "sl_pct": -1.0,
    "trail_trigger": 0.85, "trail_gap": 0.35,
    "trade_size": 5.0, "min_size": 5.0, "med_size": 10.0, "max_size": 15.0,
    "max_open": 6, "max_per_class": 3,
    "max_hold_h": 18, "cooldown_min": 25,
    "risk_mode": "medium",  # low | medium | high
    "paused": False,
    "paused_pockets": {"scalp": False, "swing": False, "reserve": False},
    "observer_mode": False,
    "manual_vault_add": 0.0,
    "banned": {}, "ban_ref": {},
    "elite_assets": ["BTC-USD", "SOL-USD", "XRP-USD", "ETH-USD", "BNB-USD"],
    "scenarios_tested": 0,
    "daily_score": 95,
    "market_mood": "مستقر 🟢",
    "last_win_toast": "",
    "crew_state": {
        "KEST8": {"role": "المضارب السريع", "status": "scanning", "bubble": "يمسح فريم 5د..."},
        "ORVEN": {"role": "صائد الموجات", "status": "scanning", "bubble": "يقيس قوة Aroon..."},
        "BRAVA": {"role": "قناص الاحتياط", "status": "cooling", "bubble": "ينتظر فرصة 90+"},
        "MIRAX": {"role": "راصد الأخبار", "status": "working", "bubble": "يراقب السيولة"},
        "DUSKA": {"role": "حارس المخاطر", "status": "working", "bubble": "يتتبع القمم 🎯"},
    },
    "ai_report": "منظومة Grok Crew والجيوب الثلاثة نشطة.",
}

def now():
    return datetime.now(TZ)

def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

def parse(s):
    s = str(s or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%H:%M:%S %d-%m-%Y"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=TZ)
        except ValueError:
            pass
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except Exception:
        return now() - timedelta(hours=25)

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
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        rows = run("SELECT val FROM kv_settings WHERE key='ai_cfg'")
        if rows and rows[0].get("val"):
            saved_db = json.loads(rows[0]["val"])
            if isinstance(saved_db, dict):
                cfg.update(saved_db)
    except Exception:
        pass
    try:
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
    except Exception:
        pass
    if not isinstance(cfg.get("banned"), dict): cfg["banned"] = {}
    if not isinstance(cfg.get("ban_ref"), dict): cfg["ban_ref"] = {}
    if not isinstance(cfg.get("paused_pockets"), dict): cfg["paused_pockets"] = {"scalp": False, "swing": False, "reserve": False}
    if not isinstance(cfg.get("crew_state"), dict): cfg["crew_state"] = json.loads(json.dumps(DEFAULT_CFG["crew_state"]))
    cfg.setdefault("trade_size", 5.0)
    cfg.setdefault("risk_mode", "medium")
    return cfg

def save_ai_config(cfg):
    try:
        raw = json.dumps(cfg, ensure_ascii=False, indent=2)
        with LOCK:
            with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(raw)
        run("INSERT OR REPLACE INTO kv_settings (key, val) VALUES ('ai_cfg', ?)", (raw,))
    except Exception as e:
        print(f"AI config save error: {e}")

def update_crew(bot_id, status=None, bubble=None):
    cfg = get_ai_config()
    crew = cfg.get("crew_state", {})
    if bot_id in crew:
        if status: crew[bot_id]["status"] = status
        if bubble: crew[bot_id]["bubble"] = bubble[:38]
        cfg["crew_state"] = crew
        save_ai_config(cfg)

def get_brain():
    default_brain = {"tested_hashes": [], "asset_profiles": {}, "trap_patterns": [], "total_runs": 0}
    try:
        rows = run("SELECT val FROM kv_settings WHERE key='ai_brain'")
        if rows and rows[0].get("val"):
            default_brain.update(json.loads(rows[0]["val"]))
    except Exception:
        pass
    try:
        if os.path.exists(BRAIN_FILE):
            with open(BRAIN_FILE, "r", encoding="utf-8") as f:
                default_brain.update(json.load(f))
    except Exception:
        pass
    return default_brain

def save_brain(brain_data):
    try:
        raw = json.dumps(brain_data, ensure_ascii=False, indent=2)
        with LOCK:
            with open(BRAIN_FILE, "w", encoding="utf-8") as f:
                f.write(raw)
        run("INSERT OR REPLACE INTO kv_settings (key, val) VALUES ('ai_brain', ?)", (raw,))
    except Exception as e:
        print(f"Brain save error: {e}")

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
        r = requests.get(url, headers=h, timeout=8)
        if r.status_code == 200:
            j = r.json()
            data = base64.b64decode(j["content"]) if j.get("content") else requests.get(j["download_url"], headers=h, timeout=15).content
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
        r = requests.get(url, headers=h, timeout=10)
        data = {"message": "Auto-save trades DB", "content": content}
        if r.status_code == 200:
            data["sha"] = r.json().get("sha")
        res = requests.put(url, headers=h, json=data, timeout=20)
        if res.status_code in (200, 201):
            _dirty, _last_backup = False, time.time()
    except Exception as e:
        print(f"Backup error: {e}")

def _instant_backup_async():
    threading.Thread(target=backup_db_to_github, kwargs={"force": True}, daemon=True).start()

def backup_if_dirty(force=False):
    if _dirty or force:
        backup_db_to_github(force=force)

def init_db():
    try:
        restore_db_from_github()
        run("CREATE TABLE IF NOT EXISTS kv_settings (key TEXT PRIMARY KEY, val TEXT)")
        run('''CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, asset_type TEXT,
            pocket TEXT DEFAULT 'scalp', score INTEGER DEFAULT 80,
            entry_price REAL, exit_price REAL, peak_price REAL DEFAULT 0.0,
            tp_pct REAL DEFAULT 1.1, sl_pct REAL DEFAULT -1.0,
            qty REAL DEFAULT 1.0, invested_sar REAL DEFAULT 5.0,
            entry_time TEXT, exit_time TEXT, reason TEXT, status TEXT,
            pnl_sar REAL DEFAULT 0.0, lesson TEXT, is_historical INTEGER DEFAULT 0)''')

        existing_cols = [r["name"] for r in run("PRAGMA table_info(trades)")]
        cols_to_add = {
            "pocket": "TEXT DEFAULT 'scalp'", "score": "INTEGER DEFAULT 80",
            "peak_price": "REAL DEFAULT 0.0", "tp_pct": "REAL DEFAULT 1.1",
            "sl_pct": "REAL DEFAULT -1.0", "qty": "REAL DEFAULT 1.0",
            "invested_sar": "REAL DEFAULT 5.0", "pnl_sar": "REAL DEFAULT 0.0",
            "lesson": "TEXT DEFAULT ''", "is_historical": "INTEGER DEFAULT 0",
        }
        for col, col_type in cols_to_add.items():
            if col not in existing_cols:
                try: run(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
                except Exception: pass

        run('''CREATE TABLE IF NOT EXISTS favorites (
            symbol TEXT PRIMARY KEY, tier TEXT DEFAULT 'trend',
            picks INTEGER DEFAULT 1, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, consec_losses INTEGER DEFAULT 0, updated_at TEXT)''')
        run('''CREATE TABLE IF NOT EXISTS thoughts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT,
            agent TEXT, message TEXT, level TEXT DEFAULT 'info')''')
        run('''CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, sender TEXT, message TEXT)''')
    except Exception as e:
        print(f"DB init warning: {e}")

def log_thought(agent, message, level="info"):
    try:
        run("INSERT INTO thoughts (time, agent, message, level) VALUES (?,?,?,?)",
            (now().strftime("%H:%M"), agent, message, level))
        run("DELETE FROM thoughts WHERE id NOT IN (SELECT id FROM thoughts ORDER BY id DESC LIMIT 45)")
    except Exception:
        pass

def get_thoughts(limit=14):
    return run("SELECT * FROM thoughts ORDER BY id DESC LIMIT ?", (limit,))

def update_favorite(symbol, picked=False, won=None):
    t_str = fmt(now())
    rows = run("SELECT * FROM favorites WHERE symbol=?", (symbol,))
    if not rows:
        tier = "royal" if symbol in DEFAULT_CFG["elite_assets"][:3] else "trend"
        run("INSERT INTO favorites (symbol, tier, picks, wins, losses, consec_losses, updated_at) VALUES (?,?,?,?,?,?,?)",
            (symbol, tier, 1 if picked else 0, 1 if won is True else 0, 1 if won is False else 0, 1 if won is False else 0, t_str))
        return
    r = rows[0]
    picks = int(r["picks"] or 0) + (1 if picked else 0)
    wins = int(r["wins"] or 0) + (1 if won is True else 0)
    losses = int(r["losses"] or 0) + (1 if won is False else 0)
    consec = 0 if won is True else (int(r["consec_losses"] or 0) + 1 if won is False else int(r["consec_losses"] or 0))
    tier = r["tier"]

    if consec >= 2:
        run("DELETE FROM favorites WHERE symbol=?", (symbol,))
        log_thought("DUSKA", f"طرد {symbol} من المفضلة بعد خسارتين متتاليتين 🛡️", "warn")
        return
    if picks >= 5 and tier == "trend":
        tier = "testing"
    if wins >= 3 and consec == 0 and tier in ("trend", "testing"):
        tier = "royal"
    run("UPDATE favorites SET tier=?, picks=?, wins=?, losses=?, consec_losses=?, updated_at=? WHERE symbol=?",
        (tier, picks, wins, losses, consec, t_str, symbol))

def get_favorites_grouped():
    rows = run("SELECT * FROM favorites ORDER BY wins DESC, picks DESC")
    if not rows:
        for s in DEFAULT_CFG["elite_assets"][:3]:
            update_favorite(s, picked=True)
        rows = run("SELECT * FROM favorites ORDER BY wins DESC, picks DESC")
    return {
        "royal": [r for r in rows if r["tier"] == "royal"],
        "testing": [r for r in rows if r["tier"] == "testing"],
        "trend": [r for r in rows if r["tier"] == "trend"],
        "all": rows,
    }

def calc_pnl(entry, exit_, invested):
    if not entry or entry <= 0:
        return 0.0
    return round(invested * (exit_ - entry) / entry - invested * FEE_PCT / 100 * 2, 2)

def log_trade(symbol, asset_type, price, reason, is_historical=0, entry_time=None,
              exit_time=None, exit_price=None, status="OPEN", pnl_sar=0.0,
              lesson="", invest_amount=5.0, pocket="scalp", score=82,
              tp_pct=None, sl_pct=None):
    global _dirty
    cfg = get_ai_config()
    p = float(price) if price else 1.0
    tp = float(tp_pct if tp_pct is not None else cfg["tp_pct"])
    sl = float(sl_pct if sl_pct is not None else cfg["sl_pct"])
    invest_usd = invest_amount / 3.75 if (symbol.endswith("-USD") or not symbol.endswith(".SR")) else invest_amount
    qty = round(invest_usd / p, 4) if p > 0 else 1.0

    run('''INSERT INTO trades (symbol, asset_type, pocket, score, entry_price, exit_price, peak_price,
           tp_pct, sl_pct, qty, invested_sar, entry_time, exit_time, reason, status, pnl_sar, lesson, is_historical)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (symbol, asset_type, pocket, int(score), round(p, 4),
         round(float(exit_price), 4) if exit_price else None, round(p, 4),
         tp, sl, qty, invest_amount, entry_time or fmt(now()), exit_time,
         reason, status, round(float(pnl_sar or 0.0), 2), lesson, is_historical))
    if not is_historical:
        _dirty = True
        update_favorite(symbol, picked=True)
        bot_map = {"scalp": "KEST8", "swing": "ORVEN", "reserve": "BRAVA"}
        b_name = bot_map.get(pocket, "KEST8")
        update_crew(b_name, "working", f"قنص {symbol} بـ {invest_amount} ر.س 🎯")
        log_thought(b_name, f"[SNIPE] شراء {symbol} بمبلغ {invest_amount} ر.س ({score}/100)", "success")
        _instant_backup_async()

def close_trade_manual(trade_id):
    """إغلاق الصفقة يدوياً بضغطة زر على طريقة SLAYER."""
    global _dirty
    rows = run("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,))
    if not rows:
        return False
    t = rows[0]
    pnl = float(t.get("pnl_sar") or 0.0)
    entry = float(t.get("entry_price") or 1.0)
    inv = float(t.get("invested_sar") or 5.0)
    cur_est = round(entry * (1.0 + (pnl / max(inv, 1.0))), 4)
    st = "WON" if pnl >= 0 else "LOST"
    lesson = f"إغلاق يدوي فوري بأمرك ({pnl:+.2f} ر.س) ⚡"
    run("UPDATE trades SET exit_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
        (cur_est, fmt(now()), st, pnl, lesson, trade_id))
    log_thought("DUSKA", f"[MANUAL] إغلاق يدوي لصفقة {t['symbol']} بصافي {pnl:+.2f} ر.س", "info")
    _dirty = True
    _instant_backup_async()
    return True

def update_open_trades(prices):
    global _dirty
    cfg = get_ai_config()
    t_now = now()
    closed_any = False
    for t in run("SELECT * FROM trades WHERE status='OPEN' AND is_historical=0"):
        cur = prices.get(t["symbol"])
        if cur is None:
            continue
        entry = float(t["entry_price"] or cur)
        peak = max(float(t.get("peak_price") or entry), cur)
        pct = ((cur - entry) / entry) * 100 if entry else 0
        peak_pct = ((peak - entry) / entry) * 100 if entry else 0
        drop_from_peak = ((peak - cur) / peak) * 100 if peak else 0
        inv = float(t.get("invested_sar") or 5.0)
        tp_target = float(t.get("tp_pct") or cfg["tp_pct"])
        sl_target = float(t.get("sl_pct") or cfg["sl_pct"])
        pnl = calc_pnl(entry, cur, inv)
        age_h = (t_now - parse(t["entry_time"])).total_seconds() / 3600

        if peak_pct >= cfg["trail_trigger"] and drop_from_peak >= cfg["trail_gap"] and pct > 0.28:
            st, lesson = "WON", f"قناص القمة 🎯: بلغ (+{peak_pct:.1f}%) وحجز الربح عند (+{pct:.1f}%)."
        elif pct >= tp_target * 1.8:
            st, lesson = "WON", f"انفجار سعري ممتاز (+{pct:.1f}%)."
        elif t.get("pocket") == "scalp" and pct >= tp_target:
            st, lesson = "WON", f"خطف سريع ناجح (+{pct:.1f}%)."
        elif pct <= sl_target:
            st, lesson = "LOST", f"حماية الوقف ({sl_target}%) — خسارة محكومة ({pnl} ر.س)."
        elif age_h >= cfg["max_hold_h"]:
            st = "WON" if pnl > 0 else "LOST"
            lesson = f"إغلاق زمني بعد {int(age_h)} ساعة لتحرير السيولة ({pct:+.2f}%)."
        else:
            trail_note = f" | تتبع القمة 🔥 (+{peak_pct:.1f}%)" if peak_pct >= cfg["trail_trigger"] else ""
            run("UPDATE trades SET peak_price=?, pnl_sar=?, lesson=? WHERE id=?",
                (round(peak, 4), pnl, f"التغير اللحظي: {pct:+.2f}%{trail_note}", t["id"]))
            continue

        run("UPDATE trades SET exit_price=?, peak_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
            (round(cur, 4), round(peak, 4), fmt(t_now), st, pnl, lesson, t["id"]))
        update_favorite(t["symbol"], won=(st == "WON"))
        if st == "WON":
            cfg["last_win_toast"] = f"🎯 قناص {t['symbol']} حجز ربح +{pnl:.2f} ر.س ({pct:+.1f}%)"
            save_ai_config(cfg)
        log_thought("DUSKA", f"[FILL] إغلاق {t['symbol']} ({st}): {pnl:+.2f} ر.س — {lesson}", "success" if st == "WON" else "warn")
        _dirty = True
        closed_any = True

    if closed_any:
        _instant_backup_async()

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

def _stats(closed, base_cap=START_CAPITAL):
    closed = sorted(closed, key=lambda t: t.get("exit_time") or "")
    n = len(closed)
    won = sum(1 for t in closed if t.get("status") == "WON")
    gw = sum(float(t.get("pnl_sar") or 0) for t in closed if float(t.get("pnl_sar") or 0) > 0)
    gl = -sum(float(t.get("pnl_sar") or 0) for t in closed if float(t.get("pnl_sar") or 0) < 0)
    cum = peak = dd = 0.0
    curve = [0.0]
    best_win = 0.0
    for t in closed:
        val = float(t.get("pnl_sar") or 0)
        if val > best_win: best_win = val
        cum += val
        curve.append(round(cum, 2))
        peak = max(peak, cum)
        dd = max(dd, peak - cum)

    current_tier_base = 100.0 if (base_cap + cum) >= 100.0 else START_CAPITAL
    scaled_capital = round(current_tier_base * SCALE_FACTOR, 0)
    scaled_pnl = round(cum * SCALE_FACTOR, 2)

    return {
        "n": n, "won": won, "lost": n - won,
        "win_rate": round(won / n * 100, 1) if n else None,
        "pnl": round(cum, 2),
        "best_win": round(best_win, 2),
        "pro_pnl": scaled_pnl,
        "scaled_capital": scaled_capital,
        "scaled_pnl": scaled_pnl,
        "pf": round(gw / gl, 2) if gl else None,
        "expectancy": round(cum / n, 3) if n else None,
        "max_dd": round(dd, 2), "curve": curve[-40:]
    }

def _calc_pockets(closed, opn, cfg):
    total_realized = sum(float(t.get("pnl_sar") or 0.0) for t in closed)
    milestones = int(max(0.0, total_realized) // 10.0)
    auto_vault = round(milestones * 3.0, 2)
    manual_vault = round(float(cfg.get("manual_vault_add") or 0.0), 2)
    personal_vault = round(auto_vault + manual_vault, 2)
    next_split_rem = round(10.0 - (max(0.0, total_realized) % 10.0), 2) if total_realized >= 0 else round(10.0 + abs(total_realized), 2)

    unsplit_pnl = total_realized - (milestones * 10.0) if total_realized >= 0 else total_realized
    base_alloc = {
        "scalp": round(25.0 + (milestones * 2.5) + (unsplit_pnl * 0.45) - (manual_vault * 0.5), 2),
        "swing": round(25.0 + (milestones * 2.5) + (unsplit_pnl * 0.45) - (manual_vault * 0.5), 2),
        "reserve": round(10.0 + (milestones * 2.0) + (unsplit_pnl * 0.10), 2),
    }

    pockets = {}
    for pk, label in (("scalp", "المضارب السريع ⚡"), ("swing", "صائد الموجات 🌊"), ("reserve", "قناص الاحتياط 🎯")):
        pk_open = [t for t in opn if (t.get("pocket") or "scalp") == pk]
        pk_closed = [t for t in closed if (t.get("pocket") or "scalp") == pk]
        pk_pnl = round(sum(float(t.get("pnl_sar") or 0.0) for t in pk_closed), 2)
        inv = round(sum(float(t.get("invested_sar") or 5.0) for t in pk_open), 2)
        alloc = max(0.0, base_alloc[pk])
        pockets[pk] = {
            "name": label, "allocated": alloc, "invested": inv,
            "cash": round(max(0.0, alloc - inv), 2),
            "open_count": len(pk_open), "pnl": pk_pnl,
            "paused": bool(cfg.get("paused_pockets", {}).get(pk, False)),
        }
    return pockets, personal_vault, milestones, next_split_rem

def get_summary():
    cfg = get_ai_config()
    live = run("SELECT * FROM trades WHERE is_historical=0")
    closed = [t for t in live if t.get("status") != "OPEN"]
    opn = [t for t in live if t.get("status") == "OPEN"]
    st = _stats(closed)
    invested = round(sum(float(t.get("invested_sar") or 5.0) for t in opn), 2)
    floating = round(sum(float(t.get("pnl_sar") or 0.0) for t in opn), 2)
    pockets, personal_vault, milestones, next_split_rem = _calc_pockets(closed, opn, cfg)

    total_wallet = round(START_CAPITAL + st["pnl"] + floating, 2)
    trading_cash = round(max(0.0, START_CAPITAL + st["pnl"] - personal_vault - invested), 2)

    return {
        "stats": st, "invested": invested, "floating": floating,
        "open_count": len(opn), "wallet": total_wallet, "cash": trading_cash,
        "personal_vault": personal_vault, "profit_milestones": milestones,
        "next_split_remaining": next_split_rem, "pockets": pockets,
    }

def get_lab():
    hist = run("SELECT * FROM trades WHERE is_historical=1")
    st = _stats([t for t in hist if t.get("status") != "OPEN"])
    st["trades"] = get_trades(1, 100)
    return st

def ask_bot_chat(user_msg):
    msg = (user_msg or "").strip()
    if not msg: return "اكتب سؤالك أو أمرك يا صالح وأبشر!"
    t_str = now().strftime("%H:%M")
    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "user", msg))
    s = get_summary()
    cfg = get_ai_config()
    pockets = s["pockets"]
    st = s["stats"]

    if "وقف" in msg and "سريع" in msg:
        cfg["paused_pockets"]["scalp"] = True; save_ai_config(cfg)
        reply = "تم إيقاف الشراء في (جيب المضارب السريع) ⏸️."
    elif ("شغل" in msg or "استئناف" in msg) and "سريع" in msg:
        cfg["paused_pockets"]["scalp"] = False; save_ai_config(cfg)
        reply = "تم تشغيل (جيب المضارب السريع) من جديد ▶️."
    elif "مراقب" in msg:
        cfg["observer_mode"] = not cfg.get("observer_mode", False); save_ai_config(cfg)
        reply = f"وضع المراقب والقناص الآن: {'مفعّل 🎯' if cfg['observer_mode'] else 'ملغي (تداول طبيعي) ✅'}."
    elif "كم معي" in msg or "رصيد" in msg or "محفظ" in msg or "ملخص" in msg:
        reply = (f"إجمالي محفظتك {s['wallet']:.2f} ر.س (الصافي: {st['pnl']:+.2f} ر.س) 💼.\n"
                 f"• KEST8 (السريع): متاح {pockets['scalp']['cash']} ر.س\n"
                 f"• ORVEN (الموجات): متاح {pockets['swing']['cash']} ر.س\n"
                 f"• BRAVA (الاحتياط): متاح {pockets['reserve']['cash']} ر.س\n"
                 f"• خزنة السحب: {s['personal_vault']:.2f} ر.س.")
    elif "نخبة" in msg or "مفضل" in msg:
        favs = get_favorites_grouped()
        reply = f"👑 النخبة الملكية: {', '.join(r['symbol'] for r in favs['royal']) or 'قيد التحديث'}"
    else:
        reply = f"طاقم الروبوتات الـ 5 يفحص السوق على فريم 5د و15د 🤖. الكاش المتاح: {s['cash']:.2f} ر.س."

    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "bot", reply))
    run("DELETE FROM chat_logs WHERE id NOT IN (SELECT id FROM chat_logs ORDER BY id DESC LIMIT 50)")
    return reply

def get_chat_history(limit=25):
    return list(reversed(run("SELECT * FROM chat_logs ORDER BY id DESC LIMIT ?", (limit,))))

init_db()
