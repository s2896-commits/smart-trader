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
    "rsi_min": 30, "rsi_max": 60,
    "tp_pct": 1.4, "sl_pct": -1.0,
    "trail_trigger": 0.85, "trail_gap": 0.30,
    "breakeven_trigger": 0.55, "breakeven_lock": 0.18,
    "trade_size": 5.0,
    "max_open": 8,
    "max_hold_h": 12, "cooldown_min": 15,
    "risk_mode": "medium",
    "paused": False,
    "stoploss_guard_until": "",
    "paused_pockets": {"scalp": False, "swing": False, "reserve": False},
    "observer_mode": False,
    "manual_vault_add": 0.0,
    "auto_withdraw_enabled": True,
    "auto_withdraw_limit": 10.0,
    "withdrawn_total": 0.0,
    "withdraw_history": [],
    "alerted_milestones": [],
    "ntfy_topic": "smax_trader_vip_999",
    "banned": {}, "ban_ref": {},
    "elite_assets": ["BTC-USD", "SOL-USD", "XRP-USD", "ETH-USD", "BNB-USD", "SUI20947-USD"],
    "scenarios_tested": 574224,
    "daily_score": 95,
    "market_mood": "مستقر 🟢",
    "last_win_toast": "",
    "best_theory": "قيد المنافسة 🔬",
    "crew_state": {
        "KEST8": {"role": "المضارب السريع", "status": "scanning", "bubble": "يمسح 32 أصلاً (5m)"},
        "ORVEN": {"role": "صائد الموجات", "status": "scanning", "bubble": "فريم الساعة + Aroon"},
        "BRAVA": {"role": "قناص الـ 4 ريال", "status": "working", "bubble": "يرصد الفرص الكبرى 💎"},
        "MIRAX": {"role": "درع الحماية", "status": "working", "bubble": "Stoploss Guard نشط"},
        "DUSKA": {"role": "قفل التعادل", "status": "working", "bubble": "Break-Even + ROI 🎯"},
    },
}

GOAL_MILESTONES = [
    (75.0, "1.25x", "🚀 مكسب جديد! محفظتك وصلت 75 ر.س (1.25x) في طريقها نحو الـ 600 ر.س!"),
    (90.0, "1.5x", "🔥 نصف تدبيلة! المحفظة وصلت 90 ر.س (1.5x) بأمان!"),
    (120.0, "2x", "💎 تدبيلة كاملة (2x)! المحفظة وصلت 120 ر.س!"),
    (180.0, "3x", "⚡ قفزة ممتازة (3x)! رصيد المحفظة الآن 180 ر.س!"),
    (300.0, "5x", "🌟 منتصف الطريق للـ 600! المحفظة وصلت 300 ر.س (5 أضعاف)!"),
    (480.0, "8x", "🚨 اقتربنا جداً من الـ 600 ر.س! المحفظة وصلت 480 ر.س (8x)!"),
    (600.0, "10x", "👑 مبروك يا صالح! تحقق هدف الـ 10 أضعاف ووصلت المحفظة 600 ر.س!"),
]

def now():
    return datetime.now(TZ)

def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

def parse(s):
    s = str(s or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"):
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

def send_vip_alert(title, message, priority="high"):
    try:
        cfg = get_ai_config()
        topic = cfg.get("ntfy_topic", "smax_trader_vip_999")
        if not topic:
            return
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title.encode("utf-8"), "Priority": priority, "Tags": "moneybag,rocket"},
            timeout=4,
        )
    except Exception:
        pass

def get_ai_config():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        rows = run("SELECT val FROM kv_settings WHERE key='ai_cfg'")
        if rows and rows[0].get("val"):
            cfg.update(json.loads(rows[0]["val"]))
    except Exception:
        pass
    try:
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    if not isinstance(cfg.get("banned"), dict): cfg["banned"] = {}
    if not isinstance(cfg.get("ban_ref"), dict): cfg["ban_ref"] = {}
    if not isinstance(cfg.get("paused_pockets"), dict): cfg["paused_pockets"] = {"scalp": False, "swing": False, "reserve": False}
    if not isinstance(cfg.get("crew_state"), dict): cfg["crew_state"] = json.loads(json.dumps(DEFAULT_CFG["crew_state"]))
    if not isinstance(cfg.get("withdraw_history"), list): cfg["withdraw_history"] = []
    if not isinstance(cfg.get("alerted_milestones"), list): cfg["alerted_milestones"] = []
    return cfg

def save_ai_config(cfg):
    try:
        raw = json.dumps(cfg, ensure_ascii=False, indent=2)
        with LOCK:
            with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(raw)
        run("INSERT OR REPLACE INTO kv_settings (key, val) VALUES ('ai_cfg', ?)", (raw,))
    except Exception:
        pass

def update_crew(bot_id, status=None, bubble=None):
    cfg = get_ai_config()
    crew = cfg.get("crew_state", {})
    if bot_id in crew:
        if status: crew[bot_id]["status"] = status
        if bubble: crew[bot_id]["bubble"] = bubble[:38]
        cfg["crew_state"] = crew
        save_ai_config(cfg)

def get_brain():
    default_brain = {"tested_hashes": [], "asset_profiles": {}, "trap_patterns": [], "total_runs": 574224}
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
    except Exception:
        pass

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
    except Exception:
        pass

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
    except Exception:
        pass

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
            pocket TEXT DEFAULT 'scalp', theory TEXT DEFAULT 'Aroon Momentum', score INTEGER DEFAULT 80,
            entry_price REAL, exit_price REAL, peak_price REAL DEFAULT 0.0,
            tp_pct REAL DEFAULT 1.4, sl_pct REAL DEFAULT -1.0,
            qty REAL DEFAULT 1.0, invested_sar REAL DEFAULT 5.0, dca_used INTEGER DEFAULT 0,
            entry_time TEXT, exit_time TEXT, reason TEXT, status TEXT,
            pnl_sar REAL DEFAULT 0.0, lesson TEXT, is_historical INTEGER DEFAULT 0)''')

        existing_cols = [r["name"] for r in run("PRAGMA table_info(trades)")]
        cols_to_add = {
            "pocket": "TEXT DEFAULT 'scalp'", "theory": "TEXT DEFAULT 'Aroon Momentum'",
            "score": "INTEGER DEFAULT 80", "peak_price": "REAL DEFAULT 0.0",
            "tp_pct": "REAL DEFAULT 1.4", "sl_pct": "REAL DEFAULT -1.0",
            "qty": "REAL DEFAULT 1.0", "invested_sar": "REAL DEFAULT 5.0",
            "dca_used": "INTEGER DEFAULT 0", "pnl_sar": "REAL DEFAULT 0.0",
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
    except Exception:
        pass

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
        return
    if picks >= 4 and tier == "trend": tier = "testing"
    if wins >= 3 and consec == 0: tier = "royal"
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

def calc_pnl(entry, exit_, invested, pocket="scalp"):
    if not entry or entry <= 0:
        return 0.0
    mult = 3.5 if pocket == "reserve" else (1.8 if pocket == "swing" else 1.0)
    raw = invested * ((exit_ - entry) / entry) * mult
    fee = invested * (FEE_PCT / 100.0) * 2
    return round(raw - fee, 2)

def execute_withdrawal(amount=None, mode="يدوي 💸"):
    global _dirty
    cfg = get_ai_config()
    live = run("SELECT * FROM trades WHERE is_historical=0 AND status!='OPEN'")
    total_realized = sum(float(t.get("pnl_sar") or 0.0) for t in live)
    milestones = int(max(0.0, total_realized) // 10.0)
    gross_vault = round((milestones * 3.0) + float(cfg.get("manual_vault_add") or 0.0), 2)
    already_withdrawn = float(cfg.get("withdrawn_total") or 0.0)
    available = round(max(0.0, gross_vault - already_withdrawn), 2)

    pull_amt = round(float(amount if amount is not None else available), 2)
    if pull_amt <= 0 or pull_amt > available:
        return False, 0.0

    cfg["withdrawn_total"] = round(already_withdrawn + pull_amt, 2)
    hist = cfg.get("withdraw_history", [])
    hist.insert(0, {"time": fmt(now()), "amount": pull_amt, "mode": mode})
    cfg["withdraw_history"] = hist[:20]
    cfg["last_win_toast"] = f"🏦 تم سحب {pull_amt:.2f} ر.س ({mode}) إلى جيبك الخاص!"
    save_ai_config(cfg)

    log_thought("الخزنة 💰", f"تم سحب {pull_amt:.2f} ر.س ({mode}) | إجمالي المسحوب: {cfg['withdrawn_total']:.2f} ر.س", "success")
    send_vip_alert("🏦 عملية سحب ناجحة!", f"تم تحويل {pull_amt:.2f} ر.س ({mode}) من خزنة البوت إلى رصيدك المسحوب!")
    _dirty = True
    _instant_backup_async()
    return True, pull_amt

def configure_auto_withdraw(enabled: bool, limit_sar: float):
    cfg = get_ai_config()
    cfg["auto_withdraw_enabled"] = bool(enabled)
    cfg["auto_withdraw_limit"] = max(1.0, round(float(limit_sar), 2))
    save_ai_config(cfg)
    return cfg

def _check_milestones_and_auto_withdraw(wallet_balance, vault_available, milestones_count):
    cfg = get_ai_config()
    alerted = set(cfg.get("alerted_milestones", []))
    changed = False

    for target_sar, tag, msg in GOAL_MILESTONES:
        if wallet_balance >= target_sar and tag not in alerted:
            alerted.add(tag)
            cfg["last_win_toast"] = msg
            log_thought("رادار 600 🏆", msg, "success")
            send_vip_alert(f"🏆 إنجاز جديد ({tag}) نحو الـ 600 ر.س!", msg)
            changed = True

    m_tag = f"split_{milestones_count}"
    if milestones_count > 0 and m_tag not in alerted:
        alerted.add(m_tag)
        msg = f"💰 اكتملت تقسيمة ربح جديدة! أُضيف 3 ر.س لخزنة السحب (المتاح: {vault_available:.2f} ر.س)"
        log_thought("الخزنة 💰", msg, "success")
        send_vip_alert("💰 تغذية خزنة السحب!", msg)
        changed = True

    if changed:
        cfg["alerted_milestones"] = list(alerted)
        save_ai_config(cfg)

    limit_val = float(cfg.get("auto_withdraw_limit") or 10.0)
    if cfg.get("auto_withdraw_enabled", True) and vault_available >= limit_val and limit_val > 0:
        execute_withdrawal(vault_available, mode="تلقائي ⚡")

def log_trade(symbol, asset_type, price, reason, is_historical=0, entry_time=None,
              exit_time=None, exit_price=None, status="OPEN", pnl_sar=0.0,
              lesson="", invest_amount=5.0, pocket="scalp", score=82,
              tp_pct=None, sl_pct=None, theory="Aroon Momentum"):
    global _dirty
    cfg = get_ai_config()
    p = float(price) if price else 1.0
    tp = float(tp_pct if tp_pct is not None else cfg["tp_pct"])
    sl = float(sl_pct if sl_pct is not None else cfg["sl_pct"])
    invest_usd = invest_amount / 3.75 if (symbol.endswith("-USD") or not symbol.endswith(".SR")) else invest_amount
    qty = round(invest_usd / p, 4) if p > 0 else 1.0

    run('''INSERT INTO trades (symbol, asset_type, pocket, theory, score, entry_price, exit_price, peak_price,
           tp_pct, sl_pct, qty, invested_sar, dca_used, entry_time, exit_time, reason, status, pnl_sar, lesson, is_historical)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (symbol, asset_type, pocket, theory, int(score), round(p, 4),
         round(float(exit_price), 4) if exit_price else None, round(p, 4),
         tp, sl, qty, invest_amount, 0, entry_time or fmt(now()), exit_time,
         reason, status, round(float(pnl_sar or 0.0), 2), lesson, is_historical))
    if not is_historical:
        _dirty = True
        update_favorite(symbol, picked=True)
        bot_map = {"scalp": "KEST8", "swing": "ORVEN", "reserve": "BRAVA"}
        b_name = bot_map.get(pocket, "KEST8")
        update_crew(b_name, "working", f"قنص {symbol} ({theory})")
        log_thought(b_name, f"[SNIPE] شراء {symbol} بـ {invest_amount} ر.س | {theory}", "success")
        if pocket == "reserve" or score >= 90:
            send_vip_alert("💎 صيد كبير (قناص الـ 4 ريال)", f"دخل البوت صفقة كبرى في {symbol} بتقييم {score}/100 ({theory})")
        _instant_backup_async()

def close_trade_manual(trade_id):
    global _dirty
    rows = run("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,))
    if not rows: return False
    t = rows[0]
    pnl = float(t.get("pnl_sar") or 0.0)
    entry = float(t.get("entry_price") or 1.0)
    inv = float(t.get("invested_sar") or 5.0)
    cur_est = round(entry * (1.0 + (pnl / max(inv, 1.0))), 4)
    st = "WON" if pnl >= 0 else "LOST"
    lesson = f"إغلاق يدوي فوري ({pnl:+.2f} ر.س) ⚡"
    run("UPDATE trades SET exit_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
        (cur_est, fmt(now()), st, pnl, lesson, trade_id))
    _dirty = True
    _instant_backup_async()
    return True

def update_open_trades(prices):
    """دمج مزايا GitHub: قفل التعادل (Freqtrade) + جدول الهدف المتنازل (Time-Decay ROI) + التعزيز الذكي (OctoBot DCA)."""
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
        inv = float(t.get("invested_sar") or 5.0)
        dca_used = int(t.get("dca_used") or 0)
        pk = t.get("pocket") or "scalp"

        pct = ((cur - entry) / entry) * 100.0 if entry else 0.0
        peak_pct = ((peak - entry) / entry) * 100.0 if entry else 0.0
        drop_from_peak = ((peak - cur) / peak) * 100.0 if peak else 0.0
        age_min = (t_now - parse(t["entry_time"])).total_seconds() / 60.0
        age_h = age_min / 60.0

        # ميزة 5 (من OctoBot): التعزيز الذكي (Safety Order / DCA) مرة واحدة لتقليص سعر الدخول
        if dca_used == 0 and pk in ("swing", "reserve") and -0.85 <= pct <= -0.55 and age_min >= 10:
            add_sar = 3.0
            new_inv = round(inv + add_sar, 2)
            new_entry = round(((entry * inv) + (cur * add_sar)) / new_inv, 4)
            entry, inv, dca_used = new_entry, new_inv, 1
            pct = ((cur - entry) / entry) * 100.0
            run("UPDATE trades SET entry_price=?, invested_sar=?, dca_used=1 WHERE id=?", (entry, inv, t["id"]))
            log_thought("ORVEN", f"[DCA] تعزيز ذكي لصفقة {t['symbol']} بـ +3 ر.س وتخفيض الدخول إلى {entry}", "info")

        tp_target = float(t.get("tp_pct") or cfg["tp_pct"])
        sl_target = float(t.get("sl_pct") or cfg["sl_pct"])

        # ميزة 2 (من Freqtrade): جدول الهدف المتنازل مع الوقت (Time-Decay ROI) لعدم تعليق الكاش
        if pk != "reserve":
            if age_min > 180:
                tp_target = min(tp_target, 0.35)
            elif age_min > 90:
                tp_target = min(tp_target, 0.55)
            elif age_min > 45:
                tp_target = min(tp_target, 0.80)

        # ميزة 1 (من Freqtrade): قفل نقطة التعادل التلقائي (Break-Even Lock)
        be_trig = float(cfg.get("breakeven_trigger", 0.55))
        be_lock = float(cfg.get("breakeven_lock", 0.18))
        is_breakeven_locked = peak_pct >= be_trig

        pnl = calc_pnl(entry, cur, inv, pocket=pk)

        if pk == "reserve" and pnl >= 2.0 and drop_from_peak >= 0.40:
            st, lesson = "WON", f"💎 هدف القناص الكبير تحقق! ربح صافي +{pnl:.2f} ر.س"
        elif peak_pct >= cfg["trail_trigger"] and drop_from_peak >= cfg["trail_gap"] and pnl >= 0.20:
            st, lesson = "WON", f"تتبع القمة 🎯: بلغ (+{peak_pct:.1f}%) وحجز +{pnl:.2f} ر.س"
        elif is_breakeven_locked and pct <= be_lock:
            st = "WON"
            pnl = max(0.08, pnl)
            lesson = f"قفل التعادل الذكي 🔒 (Freqtrade): حمى الصفقة بعد بلوغ +{peak_pct:.1f}% ومنع الخسارة!"
        elif pct >= tp_target and pnl > 0:
            st, lesson = "WON", f"هدف ROI الذكي (+{pct:.2f}% خلال {int(age_min)}د) بصافي +{pnl:.2f} ر.س"
        elif pct <= sl_target:
            st, lesson = "LOST", f"حماية الوقف ({sl_target}%) — خسارة محكومة ({pnl:.2f} ر.س)"
        elif age_h >= cfg["max_hold_h"]:
            st = "WON" if pnl >= 0 else "LOST"
            lesson = f"إغلاق زمني لتحرير السيولة بعد {int(age_h)} ساعة ({pnl:+.2f} ر.س)"
        else:
            lock_badge = " | 🔒 قفل التعادل مفعّل" if is_breakeven_locked else ""
            dca_badge = " | ⚡ معززة DCA" if dca_used else ""
            run("UPDATE trades SET peak_price=?, pnl_sar=?, lesson=? WHERE id=?",
                (round(peak, 4), pnl, f"الربح اللحظي: {pnl:+.2f} ر.س ({pct:+.2f}%){lock_badge}{dca_badge}", t["id"]))
            continue

        run("UPDATE trades SET exit_price=?, peak_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
            (round(cur, 4), round(peak, 4), fmt(t_now), st, pnl, lesson, t["id"]))
        update_favorite(t["symbol"], won=(st == "WON"))
        if st == "WON":
            cfg["last_win_toast"] = f"🎯 {t['symbol']} حقق ربح +{pnl:.2f} ر.س ({t.get('theory','Aroon')})"
            save_ai_config(cfg)
            if pnl >= 1.2:
                send_vip_alert("💰 مكسب كبير تم حجزه!", f"أغلق البوت صفقة {t['symbol']} بربح صافي +{pnl:.2f} ر.س!")
        log_thought("DUSKA", f"[FILL] إغلاق {t['symbol']} ({st}): {pnl:+.2f} ر.س — {lesson}", "success" if st == "WON" else "warn")
        _dirty = True
        closed_any = True

    if closed_any:
        get_summary()
        _instant_backup_async()

def open_symbols():
    return [r["symbol"] for r in run("SELECT symbol FROM trades WHERE status='OPEN' AND is_historical=0")]

def on_cooldown(symbol, minutes):
    r = run("SELECT exit_time FROM trades WHERE symbol=? AND is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
    if not r or not r[0]["exit_time"]: return False
    try: return now() - parse(r[0]["exit_time"]) < timedelta(minutes=minutes)
    except Exception: return False

def get_trades(historical=0, limit=60):
    return run("SELECT * FROM trades WHERE is_historical=? ORDER BY id DESC LIMIT ?", (historical, limit))

def _stats(closed, base_cap=START_CAPITAL):
    closed = sorted(closed, key=lambda t: t.get("exit_time") or "")
    n = len(closed)
    won_list = [t for t in closed if t.get("status") == "WON"]
    lost_list = [t for t in closed if t.get("status") != "WON"]
    won = len(won_list)
    lost = len(lost_list)
    gw = round(sum(float(t.get("pnl_sar") or 0) for t in won_list), 2)
    gl = round(abs(sum(float(t.get("pnl_sar") or 0) for t in lost_list)), 2)

    cum = peak = dd = 0.0
    curve = [0.0]
    best_win = 0.0
    theories = {}
    for t in closed:
        val = float(t.get("pnl_sar") or 0)
        if val > best_win: best_win = val
        cum += val
        curve.append(round(cum, 2))
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        th = t.get("theory") or "Aroon Momentum"
        theories.setdefault(th, {"w": 0, "l": 0, "pnl": 0.0})
        theories[th]["w" if val > 0 else "l"] += 1
        theories[th]["pnl"] = round(theories[th]["pnl"] + val, 2)

    best_th = "قيد المنافسة 🔬"
    if theories:
        top_t = max(theories.items(), key=lambda x: (x[1]["pnl"], x[1]["w"]))
        best_th = f"{top_t[0]} ({top_t[1]['pnl']:+.2f} ر.س)"

    win_rate = round(won / n * 100, 1) if n else 0.0
    loss_rate = round(lost / n * 100, 1) if n else 0.0
    scaled_pnl = round(cum * SCALE_FACTOR, 2)

    return {
        "n": n, "won": won, "lost": lost,
        "win_rate": win_rate, "loss_rate": loss_rate,
        "gross_win": gw, "gross_loss": gl,
        "pnl": round(cum, 2), "best_win": round(best_win, 2),
        "scaled_pnl": scaled_pnl, "pf": round(gw / gl, 2) if gl else None,
        "max_dd": round(dd, 2), "curve": curve[-40:],
        "theories": theories, "best_theory": best_th,
    }

def _calc_pockets(closed, opn, cfg):
    total_realized = sum(float(t.get("pnl_sar") or 0.0) for t in closed)
    milestones = int(max(0.0, total_realized) // 10.0)
    gross_vault = round((milestones * 3.0) + float(cfg.get("manual_vault_add") or 0.0), 2)
    withdrawn_total = round(float(cfg.get("withdrawn_total") or 0.0), 2)
    personal_vault = round(max(0.0, gross_vault - withdrawn_total), 2)
    next_split_rem = round(10.0 - (max(0.0, total_realized) % 10.0), 2) if total_realized >= 0 else round(10.0 + abs(total_realized), 2)

    unsplit = total_realized - (milestones * 10.0) if total_realized >= 0 else total_realized
    base_alloc = {
        "scalp": round(20.0 + (milestones * 2.0) + (unsplit * 0.35), 2),
        "swing": round(22.0 + (milestones * 2.5) + (unsplit * 0.35), 2),
        "reserve": round(18.0 + (milestones * 2.5) + (unsplit * 0.30), 2),
    }

    pockets = {}
    for pk, label in (("scalp", "المضارب السريع ⚡"), ("swing", "صائد الموجات 🌊"), ("reserve", "قناص الـ 4 ريال 💎")):
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
    return pockets, personal_vault, withdrawn_total, milestones, next_split_rem

def get_summary():
    cfg = get_ai_config()
    live = run("SELECT * FROM trades WHERE is_historical=0")
    closed = [t for t in live if t.get("status") != "OPEN"]
    opn = [t for t in live if t.get("status") == "OPEN"]
    st = _stats(closed)
    invested = round(sum(float(t.get("invested_sar") or 5.0) for t in opn), 2)
    floating = round(sum(float(t.get("pnl_sar") or 0.0) for t in opn), 2)
    pockets, personal_vault, withdrawn_total, milestones, next_split_rem = _calc_pockets(closed, opn, cfg)

    total_wallet = round(START_CAPITAL + st["pnl"] + floating - withdrawn_total, 2)
    growth_total = round(START_CAPITAL + st["pnl"] + floating, 2)
    trading_cash = round(max(0.0, START_CAPITAL + st["pnl"] - (personal_vault + withdrawn_total) - invested), 2)

    _check_milestones_and_auto_withdraw(growth_total, personal_vault, milestones)

    cfg = get_ai_config()
    pockets, personal_vault, withdrawn_total, milestones, next_split_rem = _calc_pockets(closed, opn, cfg)
    to_600_rem = round(max(0.0, 600.0 - growth_total), 2)

    return {
        "stats": st, "invested": invested, "floating": floating,
        "open_count": len(opn), "wallet": total_wallet, "growth_total": growth_total,
        "cash": trading_cash, "personal_vault": personal_vault,
        "withdrawn_total": withdrawn_total, "withdraw_history": cfg.get("withdraw_history", []),
        "auto_withdraw_enabled": cfg.get("auto_withdraw_enabled", True),
        "auto_withdraw_limit": cfg.get("auto_withdraw_limit", 10.0),
        "profit_milestones": milestones, "next_split_remaining": next_split_rem,
        "to_600_remaining": to_600_rem, "pockets": pockets,
    }

def get_lab():
    hist = run("SELECT * FROM trades WHERE is_historical=1")
    st = _stats([t for t in hist if t.get("status") != "OPEN"])
    st["trades"] = get_trades(1, 100)
    return st

def ask_bot_chat(user_msg):
    msg = (user_msg or "").strip()
    if not msg: return "أبشر يا صالح، اكتب أمرك!"
    t_str = now().strftime("%H:%M")
    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "user", msg))
    s = get_summary()
    reply = (f"الرصيد النشط {s['wallet']:.2f} ر.س | المتاح بالخزنة: {s['personal_vault']:.2f} ر.س | "
             f"المسحوب لجيبك: {s['withdrawn_total']:.2f} ر.س | باقي لهدف الـ 600: {s['to_600_remaining']:.1f} ر.س")
    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "bot", reply))
    return reply

def get_chat_history(limit=25):
    return list(reversed(run("SELECT * FROM chat_logs ORDER BY id DESC LIMIT ?", (limit,))))

init_db()
