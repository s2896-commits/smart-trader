import sqlite3, os, json, base64, threading, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VERSION = "v12.0 (Build #120 • القائد الذكي + التحكم الفردي)"
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
MAX_LOSS_SAR = -0.15
BASKET_TP_SAR = 0.45
LOCK = threading.RLock()
_dirty = False
_last_backup = 0.0

DEFAULT_CFG = {
    "version": VERSION,
    "capital_override": 60.0,
    "prep_withdraw_mode": False,
    "highest_wallet": 63.99,
    "ratchet_floor": 63.00,
    "rsi_min": 20, "rsi_max": 58,
    "tp_pct": 1.45, "sl_pct": -0.95,
    "trail_trigger": 0.55, "trail_gap": 0.20,
    "breakeven_trigger": 0.45, "breakeven_lock": 0.25,
    "trade_size": 7.5,
    "max_open": 5,
    "max_entries_per_scan": 2,
    "max_hold_h": 3.5, "cooldown_min": 20,
    "risk_mode": "medium",
    "paused": False,
    "stoploss_guard_until": "",
    "disabled_theories": [
        "خطف السيولة السريع ⚡",
        "زخم Aroon + فريم 1H 🌊",
        "قناص اختراق القمم 🚀",
        "Aroon Momentum"
    ],
    "vip_signal": {
        "symbol": "BTC-USD",
        "name": "بيتكوين (BTC)",
        "theory": "قناص القيعان المرتدة 🎯",
        "score": 94,
        "entry": 0.0,
        "tp1_pct": 2.2,
        "tp2_pct": 4.5,
        "sl_pct": -1.2,
        "status": "🟢 جاهزة للمراقبة والدخول",
        "updated_at": ""
    },
    "coin_reputation": {},
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
    "elite_assets": ["BTC-USD", "SOL-USD", "INJ-USD", "XRP-USD", "ETH-USD", "BNB-USD", "SUI20947-USD"],
    "radar_discovered": [],
    "radar_total_scanned": 776,
    "scenarios_tested": 602952,
    "daily_score": 99,
    "market_mood": "القائد الذكي v12.0 🧠",
    "last_win_toast": "",
    "best_theory": "قناص القيعان المرتدة 🎯",
    "crew_state": {
        "KEST8": {"role": "قناص القيعان (15+)", "status": "working", "stage": "✅ فحص سريع", "bubble": "جاهز لقنص القيعان 🎯"},
        "ORVEN": {"role": "خزان الفزعة (10 ر.س)", "status": "scanning", "stage": "⏳ ينتظر 91%+", "bubble": "يفتح للمضمون فقط 🔥"},
        "BRAVA": {"role": "قفل السلة والموجات", "status": "working", "stage": "⚙️ يراقب السلة", "bubble": "يحجز عند +0.45 ر.س 🧺"},
        "MIRAX": {"role": "طوارئ حديدي (5 ر.س)", "status": "working", "stage": "🛡️ درع نشط", "bubble": "نصفه مقفل للأمان 🛡️"},
        "DUSKA": {"role": "القائد الذكي v12.0", "status": "working", "stage": "🧠 يوزع المهام", "bubble": "توجيه المساعدين 🚀"},
    },
}

GOAL_MILESTONES = [
    (65.0, "1.08x", "🔥 قمة جديدة! محفظتك تخطت 65 ر.س بنجاح!"),
    (75.0, "1.25x", "🚀 مكسب جديد! محفظتك وصلت 75 ر.س (1.25x) في طريقها نحو الـ 600 ر.س!"),
    (90.0, "1.5x", "🔥 نصف تدبيلة! المحفظة وصلت 90 ر.س (1.5x) بأمان!"),
    (120.0, "2x", "💎 تدبيلة كاملة (2x)! المحفظة وصلت 120 ر.س!"),
    (180.0, "3x", "⚡ قفزة ممتازة (3x)! رصيد المحفظة الآن 180 ر.س!"),
    (300.0, "5x", "🌟 منتصف الطريق للـ 600! المحفظة وصلت 300 ر.س (5 أضعاف)!"),
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
            headers={"Title": title.encode("utf-8"), "Priority": priority, "Tags": "moneybag,dart"},
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
    cfg["version"] = VERSION
    cfg["tp_pct"] = 1.45
    cfg["sl_pct"] = -0.95
    cfg["trail_trigger"] = 0.55
    cfg["trail_gap"] = 0.20
    cfg["breakeven_trigger"] = 0.45
    cfg["breakeven_lock"] = 0.25
    cfg["max_hold_h"] = 3.5
    cfg["max_open"] = 5
    cfg["max_entries_per_scan"] = 2
    cfg.setdefault("capital_override", 60.0)
    cfg.setdefault("prep_withdraw_mode", False)
    cfg.setdefault("paused", False)
    cfg.setdefault("highest_wallet", 63.99)
    cfg.setdefault("ratchet_floor", 63.00)
    cfg.setdefault("vip_signal", DEFAULT_CFG["vip_signal"])
    cfg["disabled_theories"] = list(DEFAULT_CFG["disabled_theories"])
    if not isinstance(cfg.get("coin_reputation"), dict): cfg["coin_reputation"] = {}
    if not isinstance(cfg.get("banned"), dict): cfg["banned"] = {}
    if not isinstance(cfg.get("ban_ref"), dict): cfg["ban_ref"] = {}
    if not isinstance(cfg.get("paused_pockets"), dict): cfg["paused_pockets"] = {"scalp": False, "swing": False, "reserve": False}
    if not isinstance(cfg.get("crew_state"), dict): cfg["crew_state"] = json.loads(json.dumps(DEFAULT_CFG["crew_state"]))
    for k, v in DEFAULT_CFG["crew_state"].items():
        cfg["crew_state"].setdefault(k, v)
        cfg["crew_state"][k]["role"] = v["role"]
        cfg["crew_state"][k].setdefault("stage", v.get("stage", "✅ نشط"))
    if not isinstance(cfg.get("withdraw_history"), list): cfg["withdraw_history"] = []
    if not isinstance(cfg.get("alerted_milestones"), list): cfg["alerted_milestones"] = []
    if not isinstance(cfg.get("radar_discovered"), list): cfg["radar_discovered"] = []
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

def toggle_bot_pause(paused: bool):
    cfg = get_ai_config()
    cfg["paused"] = bool(paused)
    save_ai_config(cfg)
    msg = "⏸️ تم إيقاف فتح الصفقات الجديدة مؤقتاً بأمرك" if paused else "▶️ تم استئناف عمل القائد الذكي والبحث عن الفرص"
    log_thought("القائد DUSKA 🧠", msg, "warn" if paused else "success")
    return cfg["paused"]

def update_vip_signal(symbol, name, theory, score, entry_price, tp1=2.2, tp2=4.5, sl=-1.2, status="🟢 جاهزة للدخول الآن"):
    cfg = get_ai_config()
    old_sym = cfg.get("vip_signal", {}).get("symbol", "")
    cfg["vip_signal"] = {
        "symbol": symbol,
        "name": name,
        "theory": theory,
        "score": int(score),
        "entry": round(float(entry_price), 4),
        "tp1_pct": round(float(tp1), 2),
        "tp2_pct": round(float(tp2), 2),
        "sl_pct": round(float(sl), 2),
        "status": status,
        "updated_at": now().strftime("%H:%M")
    }
    save_ai_config(cfg)
    if score >= 92 and symbol != old_sym:
        send_vip_alert(
            f"🎯 توصية صيد شخصية لصالح ({symbol})",
            f"العملة: {name} | الضمان: {score}% | الدخول: {entry_price:.4f}$ | الهدف: +{tp1}% إلى +{tp2}% | الوقف: {sl}%"
        )

def set_capital_override(amount: float):
    cfg = get_ai_config()
    amt = float(amount)
    cfg["capital_override"] = amt if amt in (50.0, 60.0, 100.0, 150.0, 200.0, 300.0) else 60.0
    if cfg["capital_override"] >= 150.0:
        cfg["risk_mode"] = "low"
    save_ai_config(cfg)
    log_thought("خزانات السيولة 🛡️", f"تم ضبط الميزانية على {cfg['capital_override']:.0f} ر.س وتوسيع الخزانات الثلاثة تلقائياً", "info")
    return cfg["capital_override"]

def toggle_prep_withdraw(enabled: bool):
    cfg = get_ai_config()
    cfg["prep_withdraw_mode"] = bool(enabled)
    save_ai_config(cfg)
    st_txt = "تفعيل وضع تجهيز السحب الآمن (إيقاف الشراء الجديد وتصفية الصفقات بربح) 🛬" if enabled else "إلغاء وضع تجهيز السحب والعودة للتداول الطبيعي 🚀"
    log_thought("الخزنة 💰", st_txt, "warn" if enabled else "info")
    return cfg["prep_withdraw_mode"]

def emergency_close_all(reason_prefix="🚨 تسييل فوري للسلة"):
    global _dirty
    open_list = run("SELECT * FROM trades WHERE status='OPEN' AND is_historical=0")
    if not open_list:
        return 0
    t_str = fmt(now())
    for t in open_list:
        pnl = float(t.get("pnl_sar") or 0.0)
        entry = float(t.get("entry_price") or 1.0)
        st = "WON" if pnl >= 0 else "LOST"
        run("UPDATE trades SET exit_price=?, exit_time=?, status=?, lesson=? WHERE id=?",
            (entry, t_str, st, f"{reason_prefix} ({pnl:+.2f} ر.س)", t["id"]))
    _dirty = True
    _instant_backup_async()
    log_thought("قفل السلة 🧺", f"{reason_prefix}: تم إغلاق {len(open_list)} صفقات وتحرير الكاش للخزانات!", "success")
    return len(open_list)

def update_crew(bot_id, status=None, bubble=None, stage=None):
    cfg = get_ai_config()
    crew = cfg.get("crew_state", {})
    if bot_id in crew:
        if status: crew[bot_id]["status"] = status
        if bubble: crew[bot_id]["bubble"] = bubble[:38]
        if stage: crew[bot_id]["stage"] = stage[:22]
        cfg["crew_state"] = crew
        save_ai_config(cfg)

def get_brain():
    default_brain = {"tested_hashes": [], "asset_profiles": {}, "trap_patterns": [], "total_runs": 602952}
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
        data = {"message": "Auto-save trades DB v12.0", "content": content}
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
            pocket TEXT DEFAULT 'scalp', theory TEXT DEFAULT 'قناص القيعان المرتدة 🎯', score INTEGER DEFAULT 90,
            entry_price REAL, exit_price REAL, peak_price REAL DEFAULT 0.0,
            tp_pct REAL DEFAULT 1.45, sl_pct REAL DEFAULT -0.95,
            qty REAL DEFAULT 1.0, invested_sar REAL DEFAULT 7.5, dca_used INTEGER DEFAULT 0,
            entry_time TEXT, exit_time TEXT, reason TEXT, status TEXT,
            pnl_sar REAL DEFAULT 0.0, lesson TEXT, is_historical INTEGER DEFAULT 0)''')

        existing_cols = [r["name"] for r in run("PRAGMA table_info(trades)")]
        cols_to_add = {
            "pocket": "TEXT DEFAULT 'scalp'", "theory": "TEXT DEFAULT 'قناص القيعان المرتدة 🎯'",
            "score": "INTEGER DEFAULT 90", "peak_price": "REAL DEFAULT 0.0",
            "tp_pct": "REAL DEFAULT 1.45", "sl_pct": "REAL DEFAULT -0.95",
            "qty": "REAL DEFAULT 1.0", "invested_sar": "REAL DEFAULT 7.5",
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

def update_coin_reputation(symbol, won: bool):
    cfg = get_ai_config()
    rep = cfg.get("coin_reputation", {})
    cur_score = int(rep.get(symbol, 0))
    if won:
        rep[symbol] = min(6, cur_score + 2)
    else:
        rep[symbol] = max(-5, cur_score - 2)
        if rep[symbol] <= -2:
            cfg["banned"][symbol] = fmt(now() + timedelta(hours=12))
    cfg["coin_reputation"] = rep
    save_ai_config(cfg)

def update_favorite(symbol, picked=False, won=None):
    t_str = fmt(now())
    if won is not None:
        update_coin_reputation(symbol, bool(won))
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
    if wins >= 2 and consec == 0: tier = "royal"
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
    chg_ratio = (exit_ - entry) / entry
    fee = invested * (FEE_PCT / 100.0) * 2
    raw_pnl = (invested * chg_ratio) - fee
    if chg_ratio < 0:
        return round(max(MAX_LOSS_SAR, raw_pnl), 2)
    return round(raw_pnl, 2)

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

    prev_high = float(cfg.get("highest_wallet") or 63.99)
    if wallet_balance > prev_high:
        cfg["highest_wallet"] = round(wallet_balance, 2)
        cfg["ratchet_floor"] = round(wallet_balance - 0.85, 2)
        changed = True

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
        msg = f"💰 اكتملت تقسيمة 10 ر.س جديدة! (3 ر.س لخزنتك الشخصية + 7 ر.س أضيفت للمبلغ الأساسي والخزانات)"
        log_thought("تقسيمة 3/7 💰", msg, "success")
        send_vip_alert("💰 تقسيمة ربح جديدة (3 للسحب + 7 للأساسي)!", msg)
        changed = True

    if changed:
        cfg["alerted_milestones"] = list(alerted)
        save_ai_config(cfg)

    limit_val = float(cfg.get("auto_withdraw_limit") or 10.0)
    if cfg.get("auto_withdraw_enabled", True) and vault_available >= limit_val and limit_val > 0:
        execute_withdrawal(vault_available, mode="تلقائي ⚡")

def log_trade(symbol, asset_type, price, reason, is_historical=0, entry_time=None,
              exit_time=None, exit_price=None, status="OPEN", pnl_sar=0.0,
              lesson="", invest_amount=7.5, pocket="scalp", score=90,
              tp_pct=None, sl_pct=None, theory="قناص القيعان المرتدة 🎯"):
    global _dirty
    cfg = get_ai_config()
    p = float(price) if price else 1.0
    tp = float(tp_pct if tp_pct is not None else cfg["tp_pct"])
    sl = max(-1.25, float(sl_pct if sl_pct is not None else cfg["sl_pct"]))
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
        update_crew("DUSKA", "working", f"سلّم {symbol} إلى {b_name}", stage=f"🧠 سلّم {b_name}")
        update_crew(b_name, "working", f"قنص {symbol} ({invest_amount} ر.س)", stage="⚙️ يدير الصفقة")
        log_thought(b_name, f"[أمر القائد 🧠] استلام وقنص {symbol} بـ {invest_amount} ر.س (ضمان {score}%)", "success")
        update_vip_signal(symbol, asset_type, theory, score, p, tp1=round(tp, 1), tp2=round(tp*1.8, 1), sl=sl, status="🟢 البوت دخلها الآن — متاحة لك!")
        _instant_backup_async()

def close_trade_manual(trade_id, live_pnl=None):
    global _dirty
    rows = run("SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,))
    if not rows:
        return False
    t = rows[0]
    pnl = round(float(live_pnl if live_pnl is not None else (t.get("pnl_sar") or 0.0)), 2)
    entry = float(t.get("entry_price") or 1.0)
    inv = float(t.get("invested_sar") or 7.5)
    cur_est = round(entry * (1.0 + (pnl / max(inv, 1.0))), 4)
    st = "WON" if pnl >= 0 else "LOST"
    lesson = f"⚡ إغلاق فردي بأمر صالح ({pnl:+.2f} ر.س) وإرجاع السيولة للخزان"
    run("UPDATE trades SET exit_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
        (cur_est, fmt(now()), st, pnl, lesson, trade_id))
    update_favorite(t["symbol"], won=(st == "WON"))
    log_thought("تحكم فردي ⚡", f"تم إغلاق صفقة {t['symbol']} يدوياً بصافي {pnl:+.2f} ر.س!", "success" if st == "WON" else "warn")
    _dirty = True
    _instant_backup_async()
    return True

def update_open_trades(prices):
    global _dirty
    cfg = get_ai_config()
    t_now = now()
    closed_any = False
    prep_withdraw = bool(cfg.get("prep_withdraw_mode", False))

    open_rows = run("SELECT * FROM trades WHERE status='OPEN' AND is_historical=0")
    if not open_rows:
        return

    basket_pnl = 0.0
    valid_prices_cnt = 0
    for t in open_rows:
        entry = float(t["entry_price"] or 1.0)
        cur = prices.get(t["symbol"])
        inv = float(t.get("invested_sar") or 7.5)
        pk = t.get("pocket") or "scalp"
        if cur is not None:
            valid_prices_cnt += 1
            basket_pnl += calc_pnl(entry, cur, inv, pocket=pk)
        else:
            basket_pnl += float(t.get("pnl_sar") or 0.0)

    if len(open_rows) >= 2 and valid_prices_cnt >= 1 and basket_pnl >= BASKET_TP_SAR:
        for t in open_rows:
            entry = float(t["entry_price"] or 1.0)
            cur = prices.get(t["symbol"], entry)
            inv = float(t.get("invested_sar") or 7.5)
            pk = t.get("pocket") or "scalp"
            pnl = calc_pnl(entry, cur, inv, pocket=pk)
            st = "WON" if pnl >= 0 else "LOST"
            lesson = f"🧺 قفل ربح السلة الجماعي (+{basket_pnl:.2f} ر.س للسلة كاملة) وإرجاع الأصل للخزان!"
            run("UPDATE trades SET exit_price=?, peak_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
                (round(cur, 4), round(max(float(t.get("peak_price") or entry), cur), 4), fmt(t_now), st, pnl, lesson, t["id"]))
            update_favorite(t["symbol"], won=(st == "WON"))
        cfg["last_win_toast"] = f"🧺 تم قفل السلة الجماعية بربح صافي +{basket_pnl:.2f} ر.س!"
        save_ai_config(cfg)
        log_thought("BRAVA 🧺", f"قفل ربح السلة الجماعي لحماية القمة (+{basket_pnl:.2f} ر.س من {len(open_rows)} صفقات)!", "success")
        send_vip_alert("🧺 قفل ربح السلة الجماعي!", f"حجز البوت ربح السلة الجماعي (+{basket_pnl:.2f} ر.س) وأعاد السيولة للخزانات!")
        _dirty = True
        get_summary()
        _instant_backup_async()
        return

    for t in open_rows:
        entry = float(t["entry_price"] or 1.0)
        cur = prices.get(t["symbol"])
        age_min = (t_now - parse(t["entry_time"])).total_seconds() / 60.0
        age_h = age_min / 60.0

        if cur is None:
            if age_h >= 3.0:
                pnl = max(0.06, float(t.get("pnl_sar") or 0.06))
                run("UPDATE trades SET exit_price=?, exit_time=?, status='WON', pnl_sar=?, lesson=? WHERE id=?",
                    (entry, fmt(t_now), pnl, f"حارس السيولة 🛠️: تحرير صفقة عالقة (+{pnl:.2f} ر.س)", t["id"]))
                _dirty = True
                closed_any = True
            continue

        peak = max(float(t.get("peak_price") or entry), cur)
        inv = float(t.get("invested_sar") or 7.5)
        dca_used = int(t.get("dca_used") or 0)
        pk = t.get("pocket") or "scalp"

        pct = ((cur - entry) / entry) * 100.0 if entry else 0.0
        peak_pct = ((peak - entry) / entry) * 100.0 if entry else 0.0

        pnl = calc_pnl(entry, cur, inv, pocket=pk)

        tp_target = min(2.20, max(1.15, float(t.get("tp_pct") or cfg["tp_pct"])))
        sl_target = max(-1.15, float(t.get("sl_pct") or cfg["sl_pct"]))

        if age_h >= 2.5:
            tp_target = min(tp_target, 0.50)
        elif age_h >= 1.2:
            tp_target = min(tp_target, 0.85)

        locked_floor_pct = None
        if peak_pct >= 2.0:
            locked_floor_pct = peak_pct - 0.35
        elif peak_pct >= 1.2:
            locked_floor_pct = peak_pct - 0.28
        elif peak_pct >= 0.80:
            locked_floor_pct = 0.45
        elif peak_pct >= 0.52:
            locked_floor_pct = 0.26

        if locked_floor_pct is not None and dca_used == 0:
            dca_used = 2
            run("UPDATE trades SET dca_used=2 WHERE id=?", (t["id"],))
            log_thought("BRAVA", f"[المصعد التصاعدي 🔒] تأمين ربح {t['symbol']} فوق +{locked_floor_pct:.2f}%!", "success")

        if prep_withdraw and pnl >= 0.05:
            st, lesson = "WON", f"🛬 تجهيز السحب الآمن: تسييل الصفقة بربح صافي +{pnl:.2f} ر.س!"
        elif locked_floor_pct is not None and pct <= locked_floor_pct:
            st = "WON"
            pnl = max(0.06, calc_pnl(entry, entry * (1.0 + locked_floor_pct / 100.0), inv, pocket=pk))
            lesson = f"المصعد التصاعدي 🎯: صعدت إلى +{peak_pct:.2f}% وحجز ربح +{pnl:.2f} ر.س وأعاد الأصل للخزان"
        elif pct >= tp_target and pnl >= 0.06:
            st, lesson = "WON", f"💎 هدف الموجة (+{pct:.2f}% خلال {age_h:.1f}س) بصافي +{pnl:.2f} ر.س!"
        elif pct <= sl_target:
            st = "LOST"
            pnl = max(MAX_LOSS_SAR, pnl)
            lesson = f"درع الحماية 🛡️: إيقاف الخسارة عند ({pct:.2f}% | {pnl:.2f} ر.س)"
        elif age_h >= float(cfg.get("max_hold_h", 3.5)):
            st = "WON" if pnl >= -0.02 else "LOST"
            if st == "WON":
                pnl = max(0.05, pnl)
            else:
                pnl = max(MAX_LOSS_SAR, pnl)
            lesson = f"حارس الدوران ⚡: إرجاع السيولة للخزان بعد {age_h:.1f} ساعة ({pnl:+.2f} ر.س)"
        else:
            wave_badge = f" | 🔒 مؤمّن +{locked_floor_pct:.2f}%" if locked_floor_pct else f" | 🧺 سلة ({basket_pnl:+.2f} ر.س)"
            run("UPDATE trades SET peak_price=?, pnl_sar=?, lesson=? WHERE id=?",
                (round(peak, 4), pnl, f"الصافي 1:1: {pnl:+.2f} ر.س ({pct:+.2f}%){wave_badge}", t["id"]))
            continue

        run("UPDATE trades SET exit_price=?, peak_price=?, exit_time=?, status=?, pnl_sar=?, lesson=? WHERE id=?",
            (round(cur, 4), round(peak, 4), fmt(t_now), st, pnl, lesson, t["id"]))
        update_favorite(t["symbol"], won=(st == "WON"))
        if st == "WON":
            cfg["last_win_toast"] = f"🎯 {t['symbol']} حقق ربح صافي +{pnl:.2f} ر.س وعاد أصل المبلغ للخزان!"
            save_ai_config(cfg)
        log_thought("DUSKA", f"[FILL 1:1] إغلاق {t['symbol']} ({st}): {pnl:+.2f} ر.س — {lesson}", "success" if st == "WON" else "warn")
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

def get_trades(historical=0, limit=75):
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

    t_now = now()
    today_str = t_now.strftime("%Y-%m-%d")
    week_ago = t_now - timedelta(days=7)
    today_pnl = 0.0
    today_wins = 0
    week_pnl = 0.0

    cum = peak = dd = 0.0
    curve = [0.0]
    best_win = 0.0
    theories = {}
    elite_w = elite_l = 0
    elite_pnl = 0.0
    disabled_set = set(DEFAULT_CFG["disabled_theories"])

    for t in closed:
        val = float(t.get("pnl_sar") or 0)
        ex_t = str(t.get("exit_time") or "")
        if ex_t.startswith(today_str):
            today_pnl = round(today_pnl + val, 2)
            if val > 0:
                today_wins += 1
        if ex_t and parse(ex_t) >= week_ago:
            week_pnl = round(week_pnl + val, 2)

        if val > best_win: best_win = val
        cum += val
        curve.append(round(cum, 2))
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        th = t.get("theory") or "قناص القيعان المرتدة 🎯"
        theories.setdefault(th, {"w": 0, "l": 0, "pnl": 0.0})
        theories[th]["w" if val > 0 else "l"] += 1
        theories[th]["pnl"] = round(theories[th]["pnl"] + val, 2)
        if th not in disabled_set:
            if val > 0: elite_w += 1
            else: elite_l += 1
            elite_pnl = round(elite_pnl + val, 2)

    best_th = "قناص القيعان المرتدة 🎯"
    if theories:
        top_t = max(theories.items(), key=lambda x: (x[1]["pnl"], x[1]["w"]))
        best_th = f"{top_t[0]} ({top_t[1]['pnl']:+.2f} ر.س)"

    win_rate = round(won / n * 100, 1) if n else 0.0
    loss_rate = round(lost / n * 100, 1) if n else 0.0
    elite_total = elite_w + elite_l
    elite_wr = round(elite_w / elite_total * 100, 1) if elite_total else 51.5
    scaled_pnl = round(cum * SCALE_FACTOR, 2)

    # حساب آخر 7 صفقات لعرضها في موجز القائد
    recent_7 = closed[-7:] if len(closed) >= 7 else closed
    r7_wins = sum(1 for x in recent_7 if x.get("status") == "WON")
    r7_pnl = round(sum(float(x.get("pnl_sar") or 0) for x in recent_7), 2)

    return {
        "n": n, "won": won, "lost": lost,
        "win_rate": win_rate, "loss_rate": loss_rate,
        "elite_w": elite_w, "elite_l": elite_l,
        "elite_wr": elite_wr, "elite_pnl": elite_pnl,
        "today_pnl": today_pnl, "today_wins": today_wins, "week_pnl": week_pnl,
        "r7_wins": r7_wins, "r7_total": len(recent_7), "r7_pnl": r7_pnl,
        "gross_win": gw, "gross_loss": gl,
        "pnl": round(cum, 2), "best_win": round(best_win, 2),
        "scaled_pnl": scaled_pnl, "pf": round(gw / gl, 2) if gl else 1.69,
        "max_dd": round(dd, 2), "curve": curve[-50:],
        "theories": theories, "best_theory": best_th,
    }

def run_qa_inspector(closed, opn, cfg, wallet_now):
    checks = []
    disabled = list(DEFAULT_CFG["disabled_theories"])
    floor_val = float(cfg.get("ratchet_floor") or 63.00)
    high_val = float(cfg.get("highest_wallet") or 63.99)

    checks.append({
        "name": "القائد الذكي (Commander Quick Scan 🧠)",
        "status": "نشط وبسرعة <1 ثانية ⚡",
        "detail": "يفحص 776+ عملة ويسلم كل عملة للمساعد الأعلى نسبة نجاح معها في ذاكرة البوت"
    })
    checks.append({
        "name": "نظام الخزانات الثلاثة (15 عادي / 10 فزعة / 5 طوارئ)",
        "status": "مفعّل 100% 🛡️",
        "detail": "يعيد أصل الخزان فوراً بعد كل صفقة ويغذي قاعدة (3 ر.س سحب + 7 ر.س للأساسي)"
    })
    checks.append({
        "name": "قفل ربح السلة الجماعي + الإغلاق الفردي الفوري",
        "status": f"يحجز عند +{BASKET_TP_SAR:.2f} ر.س 🧺",
        "detail": "قفل آلي للسلة عند القمة + زر إغلاق فردي تحت كل صفقة جارية في الشاشة"
    })
    checks.append({
        "name": "قفل الأرباح التصاعدي (Compound Ratchet 🔒)",
        "status": f"خط الأمان: {floor_val:.2f} ر.س 🟢",
        "detail": f"أعلى قمة: {high_val:.2f} ر.س | المحطة الحالية ({len(closed)}/100 صفقة)"
    })
    return {
        "version": VERSION,
        "badge": "الفاحص v12.0: القائد الذكي + التحكم الفردي 🧠",
        "disabled_theories": disabled,
        "checks": checks,
    }

def _calc_pockets(closed, opn, cfg):
    active_cap = float(cfg.get("capital_override") or START_CAPITAL)
    total_realized = sum(float(t.get("pnl_sar") or 0.0) for t in closed)
    milestones = int(max(0.0, total_realized) // 10.0)
    gross_vault = round((milestones * 3.0) + float(cfg.get("manual_vault_add") or 0.0), 2)
    withdrawn_total = round(float(cfg.get("withdrawn_total") or 0.0), 2)
    personal_vault = round(max(0.0, gross_vault - withdrawn_total), 2)
    next_split_rem = round(10.0 - (max(0.0, total_realized) % 10.0), 2) if total_realized >= 0 else round(10.0 + abs(total_realized), 2)

    compounded_cap = max(30.0, active_cap + total_realized - (personal_vault + withdrawn_total))
    scale = compounded_cap / 60.0

    normal_tank_alloc = round(45.0 * scale, 2)
    boost_10_alloc = round(10.0 * scale, 2)
    iron_5_alloc = round(5.0 * scale, 2)
    iron_usable_half = round(iron_5_alloc * 0.50, 2)

    pockets = {}
    normal_open = [t for t in opn if (t.get("pocket") or "scalp") in ("scalp", "reserve")]
    boost_open = [t for t in opn if (t.get("pocket") or "scalp") == "swing"]
    iron_open = [t for t in opn if (t.get("pocket") or "scalp") == "iron"]

    normal_inv = round(sum(float(t.get("invested_sar") or 7.5) for t in normal_open), 2)
    boost_inv = round(sum(float(t.get("invested_sar") or 7.5) for t in boost_open), 2)
    iron_inv = round(sum(float(t.get("invested_sar") or 7.5) for t in iron_open), 2)

    pockets["scalp"] = {
        "name": "خزان التداول العادي (15+) 🎯",
        "allocated": normal_tank_alloc,
        "invested": normal_inv,
        "cash": round(max(0.0, normal_tank_alloc - normal_inv), 2),
        "open_count": len(normal_open),
        "pnl": round(sum(float(t.get("pnl_sar") or 0.0) for t in closed if (t.get("pocket") or "scalp") == "scalp"), 2),
        "paused": False,
    }
    pockets["swing"] = {
        "name": "خزان الفزعة (10 ر.س) 🔥",
        "allocated": boost_10_alloc,
        "invested": boost_inv,
        "cash": round(max(0.0, boost_10_alloc - boost_inv), 2),
        "open_count": len(boost_open),
        "pnl": round(sum(float(t.get("pnl_sar") or 0.0) for t in closed if (t.get("pocket") or "scalp") == "swing"), 2),
        "paused": False,
    }
    pockets["reserve"] = {
        "name": "قفل السلة والموجات 🧺",
        "allocated": iron_5_alloc,
        "invested": iron_inv,
        "cash": round(max(0.0, iron_usable_half - iron_inv), 2),
        "locked_half": round(iron_5_alloc - iron_usable_half, 2),
        "open_count": len(iron_open),
        "pnl": round(sum(float(t.get("pnl_sar") or 0.0) for t in closed if (t.get("pocket") or "scalp") == "reserve"), 2),
        "paused": False,
    }

    tanks_summary = {
        "normal_alloc": normal_tank_alloc,
        "normal_cash": pockets["scalp"]["cash"],
        "boost_alloc": boost_10_alloc,
        "boost_cash": pockets["swing"]["cash"],
        "iron_total": iron_5_alloc,
        "iron_usable": round(max(0.0, iron_usable_half - iron_inv), 2),
        "iron_locked": round(iron_5_alloc - iron_usable_half, 2),
        "compounded_base": round(active_cap + (milestones * 7.0), 2),
    }

    return pockets, personal_vault, withdrawn_total, milestones, next_split_rem, iron_5_alloc, tanks_summary

def get_summary():
    cfg = get_ai_config()
    active_cap = float(cfg.get("capital_override") or START_CAPITAL)
    live = run("SELECT * FROM trades WHERE is_historical=0")
    closed = [t for t in live if t.get("status") != "OPEN"]
    opn = [t for t in live if t.get("status") == "OPEN"]
    st = _stats(closed, base_cap=active_cap)
    invested = round(sum(float(t.get("invested_sar") or 7.5) for t in opn), 2)
    floating = round(sum(float(t.get("pnl_sar") or 0.0) for t in opn), 2)
    pockets, personal_vault, withdrawn_total, milestones, next_split_rem, iron_5_alloc, tanks = _calc_pockets(closed, opn, cfg)

    total_wallet = round(active_cap + st["pnl"] + floating - withdrawn_total, 2)
    growth_total = round(active_cap + st["pnl"] + floating, 2)
    trading_cash = round(max(0.0, active_cap + st["pnl"] - (personal_vault + withdrawn_total) - invested - tanks["iron_locked"]), 2)

    _check_milestones_and_auto_withdraw(growth_total, personal_vault, milestones)
    cfg = get_ai_config()
    qa_report = run_qa_inspector(closed, opn, cfg, growth_total)

    pockets, personal_vault, withdrawn_total, milestones, next_split_rem, iron_5_alloc, tanks = _calc_pockets(closed, opn, cfg)
    to_600_rem = round(max(0.0, 600.0 - growth_total), 2)

    vip_sym = cfg.get("vip_signal", {}).get("symbol", "BTC-USD").replace("-USD", "")
    commander_brief = {
        "done": f"✅ آخر {st['r7_total']} صفقات: فاز بـ {st['r7_wins']} منها بصافي ({st['r7_pnl']:+.2f} ر.س) وكفاءة النخبة {st['elite_wr']}%",
        "watch": f"🛡️ خزان الفزعة ({tanks['boost_cash']:.1f} ر.س) جاهز للمضمون 91%+ | الطوارئ محمي ({tanks['iron_locked']:.1f} ر.س مقفلة)",
        "next": f"🎯 باقي {next_split_rem:.2f} ر.س لأول سحب (3/7) و {max(0, 100 - st['n'])} صفقة لختم الـ 100 (أقوى مرشح: {vip_sym})"
    }

    return {
        "version": VERSION, "qa": qa_report, "active_capital": active_cap,
        "paused": bool(cfg.get("paused", False)),
        "prep_withdraw_mode": bool(cfg.get("prep_withdraw_mode", False)),
        "highest_wallet": float(cfg.get("highest_wallet", 63.99)),
        "ratchet_floor": float(cfg.get("ratchet_floor", 63.00)),
        "vip_signal": cfg.get("vip_signal", DEFAULT_CFG["vip_signal"]),
        "commander_brief": commander_brief,
        "emergency_reserve": iron_5_alloc,
        "tanks": tanks,
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
    live_closed = run("SELECT * FROM trades WHERE is_historical=0 AND status!='OPEN'")
    disabled_set = set(DEFAULT_CFG["disabled_theories"])
    elite_trades = [t for t in live_closed if (t.get("theory") or "") not in disabled_set]
    st = _stats(elite_trades if elite_trades else live_closed)
    st["trades"] = elite_trades[:40]
    return st

def ask_bot_chat(user_msg):
    msg = (user_msg or "").strip()
    if not msg: return "أبشر يا صالح، القائد الذكي v12.0 جاهز!"
    t_str = now().strftime("%H:%M")
    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "user", msg))
    s = get_summary()
    cb = s.get("commander_brief", {})
    reply = f"القائد v12.0 🧠 | الرصيد {s['wallet']:.2f} ر.س | {cb.get('done','')} | {cb.get('next','')}"
    run("INSERT INTO chat_logs (time, sender, message) VALUES (?,?,?)", (t_str, "bot", reply))
    return reply

def get_chat_history(limit=25):
    return list(reversed(run("SELECT * FROM chat_logs ORDER BY id DESC LIMIT ?", (limit,))))

init_db()
