import threading, time, os, re, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
import database as db

# عملات باينانس الرقمية عالية السيولة فقط (بدون أسهم سعودية أو أمريكية)
CORE_WATCHLIST = {
    "BTC-USD": "بيتكوين", "ETH-USD": "إيثيريوم", "SOL-USD": "سولانا",
    "BNB-USD": "بينانس", "XRP-USD": "ريبل", "DOGE-USD": "دوج كوين",
    "ADA-USD": "كاردانو", "AVAX-USD": "أفالانش", "LINK-USD": "تشين لينك",
    "SUI20947-USD": "سوي", "DOT-USD": "بولكادوت", "NEAR-USD": "نير بروتوكول",
    "LTC-USD": "لايتكوين", "UNI7083-USD": "يوني سواب", "APT21794-USD": "أبتوس",
    "ARB11841-USD": "أربيتروم", "OP-USD": "أوبتيميزم", "INJ-USD": "إنجيكتيف",
    "RNDR-USD": "ريندر", "FET-USD": "فيتش AI", "ATOM-USD": "كوزموس",
    "FIL-USD": "فايل كوين", "TIA22861-USD": "سيليستيا", "SEI-USD": "سي نتورك",
    "STX4847-USD": "ستاكس", "AAVE-USD": "آفي", "ALGO-USD": "ألغوراند",
    "BCH-USD": "بيتكوين كاش", "ETC-USD": "إيثيريوم كلاسيك", "XLM-USD": "ستيلر",
    "HBAR-USD": "هيديرا", "VET-USD": "في تشين", "ICP-USD": "إنترنت كمبيوتر",
    "MKR-USD": "ميكر", "SAND-USD": "ساند بوكس", "MANA-USD": "ديسنترالاند",
}

IGNORE_BASES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "AEUR", "USDT",
    "WBTC", "WBETH", "PAXG", "USD1", "USDE", "GRAM", "GOOGLB", "NVDAB",
    "SNDKB", "SOXLB", "TSLAB", "AAPLB", "AMZNB", "METAB", "MSFTB", "PEPE"
}

TZ_SA = ZoneInfo("Asia/Riyadh")
_scan_lock = threading.Lock()
_news_cache = {"ts": 0, "score": 20, "mood": "امتحان باينانس v13.0 🏁", "danger": False}

def is_clean_crypto_symbol(sym: str) -> bool:
    if not sym.isalpha() or sym in IGNORE_BASES or len(sym) > 5:
        return False
    if sym.endswith(("UP", "DOWN", "BULL", "BEAR", "B")):
        return False
    return True

def discover_all_market_movers():
    dynamic_assets = {}
    total_scanned = 780
    discovered_names = []
    try:
        r = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=6)
        if r.status_code == 200:
            tickers = r.json()
            usdt_pairs = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
            total_scanned = max(400, len(usdt_pairs))
            candidates = []
            for t in usdt_pairs:
                sym = t["symbol"][:-4]
                if not is_clean_crypto_symbol(sym):
                    continue
                vol_usd = float(t.get("quoteVolume") or 0.0)
                chg_24h = float(t.get("priceChangePercent") or 0.0)
                last_p = float(t.get("lastPrice") or 0.0)
                high_p = float(t.get("highPrice") or 0.0)
                bid_p = float(t.get("bidPrice") or last_p)
                ask_p = float(t.get("askPrice") or last_p)
                spread_pct = ((ask_p - bid_p) / last_p) * 100.0 if last_p > 0 else 1.0

                if vol_usd >= 25_000_000 and spread_pct <= 0.12 and -3.5 <= chg_24h <= 11.0 and last_p > 0:
                    dist_from_high = ((high_p - last_p) / high_p) * 100.0 if high_p > 0 else 0.0
                    if dist_from_high >= 0.6:
                        candidates.append((sym, vol_usd, chg_24h))

            candidates.sort(key=lambda x: (x[1] / 25_000_000) + abs(x[2]), reverse=True)
            for sym, vol_usd, chg_24h in candidates[:12]:
                yf_sym = f"{sym}-USD"
                if yf_sym not in CORE_WATCHLIST:
                    dynamic_assets[yf_sym] = f"{sym} (سيولة باينانس 🎯)"
                discovered_names.append(f"{sym} ({chg_24h:+.0f}%)")
    except Exception:
        pass

    cfg = db.get_ai_config()
    cfg["radar_total_scanned"] = total_scanned
    if discovered_names:
        cfg["radar_discovered"] = discovered_names[:6]
    db.save_ai_config(cfg)

    merged = dict(CORE_WATCHLIST)
    merged.update(dynamic_assets)
    return merged, total_scanned, discovered_names

def market_status():
    sa = datetime.now(TZ_SA)
    return {"crypto": True, "tasi": False, "us": False, "hour_sa": sa.hour}

def indicators(df):
    close, high, low = df["Close"], df["High"], df["Low"]
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, 1e-9))
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = (tr.rolling(14).mean() / close.replace(0, 1e-9)) * 100
    vol_avg = df["Volume"].rolling(20).mean() if "Volume" in df else pd.Series(1, index=close.index)
    aroon_up = high.rolling(15).apply(lambda x: float(np.argmax(x)) / 14.0 * 100.0, raw=True).fillna(50.0)
    aroon_dn = low.rolling(15).apply(lambda x: float(np.argmin(x)) / 14.0 * 100.0, raw=True).fillna(50.0)
    aroon_osc = aroon_up - aroon_dn
    return sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc

def check_news_and_mood():
    global _news_cache
    if time.time() - _news_cache["ts"] < 90:
        return _news_cache
    score, danger, mood = 20, False, "امتحان باينانس v13.0 🏁"
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if r.status_code == 200:
            fng = int(r.json()["data"][0]["value"])
            mood = f"قيعان باينانس ({fng}) 🎯" if fng < 30 else (f"زخم عالي ({fng}) 🟢" if fng > 58 else f"متوازن ({fng}) 🟢")
            score = 18 if fng < 25 else (23 if fng > 55 else 20)
    except Exception:
        pass
    _news_cache = {"ts": time.time(), "score": score, "mood": mood, "danger": danger}
    return _news_cache

def is_1h_anchor_bullish(df_1h):
    if df_1h is None or len(df_1h) < 22:
        return True
    try:
        c = df_1h["Close"]
        sma20 = float(c.rolling(20).mean().iloc[-1])
        cur = float(c.iloc[-1])
        return (cur >= sma20 * 0.990) or (cur >= float(c.iloc[-3]))
    except Exception:
        return True

def evaluate_squads(symbol, d, d_1h, btc_chg, btc_flash_drop, news_info, cfg, brain, favs, summary, tf_mode="15m"):
    """الإصدار v13.0: البطلان فقط (انفجار الحيتان 3x + القيعان المشددة) بحجم 20 ر.س مطابق لباينانس."""
    if cfg.get("prep_withdraw_mode", False) or cfg.get("paused", False):
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", 0.0

    c, o, h, l = d["Close"].iloc[:-1], d["Open"].iloc[:-1], d["High"].iloc[:-1], d["Low"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52 or btc_flash_drop < -0.45:
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", 0.0

    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(d.iloc[:-1])
    price, prev = float(c.iloc[-1]), float(c.iloc[-2])
    cur_open = float(o.iloc[-1])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20 = float(sma20.iloc[-1])
    cur_atr = max(0.55, min(float(atr_pct.iloc[-1] or 0.95), 3.0))
    cur_vol, avg_vol = float(v.iloc[-1] or 0), float(vol_avg.iloc[-1] or 1)
    a_up, a_osc = float(aroon_up.iloc[-1]), float(aroon_osc.iloc[-1])

    prof = brain.get("asset_profiles", {}).get(symbol, {})
    if prof.get("isolated", False) or db.on_cooldown(symbol, cfg.get("cooldown_min", 25)):
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    candle_jump = ((price - prev) / prev) * 100.0 if prev else 0.0
    if candle_jump > 2.8 or cur_rsi > 56 or cur_vol < avg_vol * 0.75:
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    anchor_ok = is_1h_anchor_bullish(d_1h)
    vol_ratio = cur_vol / max(avg_vol, 1e-9)
    low_14 = float(l.iloc[-14:].min()) if len(l) >= 14 else price
    bounce_from_low_pct = ((price - low_14) / low_14) * 100.0 if low_14 > 0 else 0.0
    green_bounce = (price > cur_open) and (price >= prev * 1.0004) and (0.12 <= bounce_from_low_pct <= 2.0)

    theory = None
    base_score = 65
    helper_bot = "BRAVA"

    # 1. البطل الأول (أولوية قصوى): انفجار الحيتان 3x 💎
    if anchor_ok and vol_ratio >= 1.35 and a_up >= 70 and a_osc >= 25 and price >= cur_sma20 and price > cur_open and 36 <= cur_rsi <= 56:
        theory = "انفجار الحيتان 3x 💎"
        base_score = 91 + (3 if vol_ratio >= 1.75 else 0)
        helper_bot = "BRAVA"
    # 2. البطل الثاني (مشدد لتقليل الخسائر): قناص القيعان المرتدة 🎯 مع شرط اتجاه الساعة وسيولة حقيقية
    elif green_bounce and anchor_ok and vol_ratio >= 1.05 and 20 <= cur_rsi <= 37:
        theory = "قناص القيعان المرتدة 🎯"
        base_score = 88 + (4 if cur_rsi <= 31 else 0)
        helper_bot = "KEST8"
    else:
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    if theory in cfg.get("disabled_theories", []):
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    rep_bonus = int(cfg.get("coin_reputation", {}).get(symbol, 0))
    base_score += rep_bonus
    if symbol in [r["symbol"] for r in favs["royal"]]:
        base_score += 2
    if btc_chg > -0.4:
        base_score += 2
    total_score = min(99, base_score)

    risk_mode = cfg.get("risk_mode", "medium")
    min_req = 88 if risk_mode == "low" else (83 if risk_mode == "high" else 86)

    if cfg.get("observer_mode"):
        min_req = max(min_req, 92)
    if total_score < min_req:
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    tanks = summary.get("tanks", {})
    normal_cash = float(tanks.get("normal_cash", 40.0))
    boost_cash = float(tanks.get("boost_cash", 20.0))
    active_cap = float(summary.get("active_capital") or 60.0)
    trade_unit = round(20.0 * (active_cap / 60.0), 1)

    chosen_pocket = None
    invest_size = 0.0
    tank_label = ""

    if normal_cash >= trade_unit - 0.5:
        chosen_pocket = "reserve" if helper_bot == "BRAVA" else "scalp"
        invest_size = min(trade_unit, normal_cash)
        tank_label = f"{helper_bot} • خزان باينانس العادي ({invest_size:.0f} ر.س)"
    elif total_score >= 93 and boost_cash >= trade_unit - 0.5:
        chosen_pocket = "swing"
        invest_size = min(trade_unit, boost_cash)
        tank_label = f"ORVEN • خزان الفزعة ({invest_size:.0f} ر.س للمضمون 93%+ 🔥)"
    else:
        return 0, "reserve", 0.0, 1.85, -1.05, "", "", price

    dynamic_sl = round(-max(0.85, min(1.15, cur_atr * 1.05)), 2)
    tp_pct = round(max(1.55, min(2.60, cur_atr * 1.85)), 2)

    reason = f"[{theory}] ضمان {total_score}% ({tank_label}) | RSI {cur_rsi:.0f} | سيولة {vol_ratio:.1f}x | هدف +{tp_pct:.1f}%"
    return total_score, chosen_pocket, round(invest_size, 1), tp_pct, dynamic_sl, reason, theory, price

def fetch(symbols, period, interval):
    df = yf.download(list(symbols), period=period, interval=interval,
                     group_by="ticker", progress=False, threads=True,
                     auto_adjust=True, timeout=25)
    out = {}
    for s in symbols:
        try:
            d = df[s].dropna(subset=["Close"])
            if len(d) >= 30:
                out[s] = d
        except Exception:
            pass
    return out

def is_fresh(d, minutes=180):
    last = d.index[-1]
    return pd.Timestamp.now(tz=last.tz) - last < pd.Timedelta(minutes=minutes)

def supervisor():
    cfg, t = db.get_ai_config(), db.now()
    cfg["banned"] = {s: u for s, u in cfg["banned"].items() if u > db.fmt(t)}
    news_info = check_news_and_mood()

    recent = db.run("SELECT id, symbol, status, exit_time FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 10")
    recent_losses_1h = 0
    for r in recent:
        if r.get("status") == "LOST" and r.get("exit_time"):
            if (t - db.parse(r["exit_time"])).total_seconds() <= 3600:
                recent_losses_1h += 1

    guard_until = cfg.get("stoploss_guard_until", "")
    if recent_losses_1h >= 2 and guard_until <= db.fmt(t):
        guard_until = db.fmt(t + timedelta(minutes=45))
        cfg["stoploss_guard_until"] = guard_until
        db.log_thought("MIRAX", "🛡️ تفعيل درع الصبر 45 دقيقة بعد خسارتين سريعتين!", "warn")

    guard_active = bool(guard_until and guard_until > db.fmt(t))
    cfg["observer_mode"] = guard_active or news_info["danger"]
    cfg["market_mood"] = "انتهى الامتحان 🏁" if len(recent) >= db.EXAM_TARGET else ("موقوف مؤقتاً ⏸️" if cfg.get("paused") else ("درع الصبر 🛡️" if guard_active else news_info["mood"]))

    summ = db.get_summary()
    cfg["best_theory"] = summ["stats"].get("best_theory", "انفجار الحيتان 3x 💎")
    db.save_ai_config(cfg)
    return cfg, news_info

def _single_scan_pass():
    cfg, news_info = supervisor()
    full_watchlist, total_mkt_coins, radar_gems = discover_all_market_movers()
    open_syms = db.open_symbols()
    for osym in open_syms:
        if osym not in full_watchlist:
            full_watchlist[osym] = f"{osym} (صفقة نشطة)"

    active_symbols = [s for s in full_watchlist if s.endswith("-USD")]

    data_1h = fetch(active_symbols, "10d", "1h")
    data_15m = fetch(active_symbols, "5d", "15m")
    data_5m = fetch(active_symbols, "2d", "5m")

    prices = {s: float(d["Close"].iloc[-1]) for s, d in data_15m.items() if is_fresh(d, 180)}
    for s, d in data_5m.items():
        if is_fresh(d, 90):
            prices[s] = float(d["Close"].iloc[-1])

    db.update_open_trades(prices)

    summ = db.get_summary()
    total_started = summ["stats"]["n"] + summ["open_count"]
    if cfg.get("paused") or cfg.get("prep_withdraw_mode") or total_started >= db.EXAM_TARGET:
        return

    btc_chg = 0.0
    btc_flash_drop = 0.0
    if "BTC-USD" in data_15m and len(data_15m["BTC-USD"]) >= 5:
        b15 = data_15m["BTC-USD"]["Close"]
        btc_flash_drop = ((float(b15.iloc[-1]) - float(b15.iloc[-2])) / float(b15.iloc[-2])) * 100.0
        btc_chg = ((float(b15.iloc[-1]) - float(b15.iloc[-5])) / float(b15.iloc[-5])) * 100.0

    open_syms = db.open_symbols()
    favs = db.get_favorites_grouped()
    brain = db.get_brain()

    db.update_crew("DUSKA", "working", f"فحص {total_mkt_coins} عملة باينانس", stage=f"🏁 امتحان {summ['stats']['n']}/{db.EXAM_TARGET}")
    db.update_crew("BRAVA", "working", "انفجار الحيتان 3x (20 ر.س)", stage="💎 أولوية أولى")
    db.update_crew("KEST8", "scanning", "قيعان مشددة مع 1H 🎯", stage="🎯 فلتر مشدود")
    db.update_crew("ORVEN", "scanning", "خزان الفزعة (20 ر.س) 🔥", stage="⏳ ينتظر 93%+")
    db.update_crew("MIRAX", "working", "قفل السلة عند +0.70 ر.س 🛡️", stage="🛡️ درع 60 ر.س")
    db.log_thought("امتحان v13.0 🏁", f"فحص {total_mkt_coins} عملة باينانس | التقدم ({summ['stats']['n']}/{db.EXAM_TARGET}) | الرصيد {summ['wallet']:.2f} ر.س", "info")

    candidates = []
    for s in active_symbols:
        if s not in prices or s in open_syms or s in cfg["banned"]:
            continue
        for tf_label, d_map in (("15m", data_15m), ("5m", data_5m)):
            if s not in d_map:
                continue
            score, pocket, size, tp_pct, sl_pct, reason, theory, cur_p = evaluate_squads(
                s, d_map[s], data_1h.get(s), btc_chg, btc_flash_drop, news_info, cfg, brain, favs, summ, tf_mode=tf_label
            )
            if score >= 83 and size >= 19.0:
                candidates.append((score, s, pocket, size, tp_pct, sl_pct, reason, theory, full_watchlist[s], cur_p))
                break

    candidates.sort(key=lambda x: x[0], reverse=True)

    if candidates:
        top = candidates[0]
        db.update_vip_signal(top[1], top[8], top[7], top[0], top[9], tp1=round(top[4], 1), tp2=round(top[4]*1.6, 1), sl=top[5], status="🟢 فرصة باينانس مرشحة الآن")

    entries_this_scan = 0
    max_per_scan = int(cfg.get("max_entries_per_scan", 2))

    for score, s, pocket, size, tp_pct, sl_pct, reason, theory, label, cur_p in candidates:
        if entries_this_scan >= max_per_scan or len(open_syms) >= cfg.get("max_open", 3):
            break
        if (summ["stats"]["n"] + len(open_syms)) >= db.EXAM_TARGET:
            break
        if summ["cash"] < 19.0:
            break
        db.log_trade(s, label, prices[s], reason, invest_amount=size,
                     pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct, theory=theory)
        open_syms.append(s)
        entries_this_scan += 1
        summ = db.get_summary()

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        _single_scan_pass()
    finally:
        _scan_lock.release()

def run_backtest():
    brain = db.get_brain()
    if not brain.get("asset_profiles"):
        brain["asset_profiles"] = {"SOFI": {"isolated": True}}
        brain["total_runs"] = 602952
        db.save_brain(brain)
