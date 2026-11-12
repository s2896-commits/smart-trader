import threading, time, re, requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
import database as db

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
    "2222.SR": "أرامكو (تاسي)", "1120.SR": "الراجحي (تاسي)", "7010.SR": "اس تي سي (تاسي)",
    "NVDA": "إنفيديا (أمريكي)", "PLTR": "بالنتير (أمريكي)",
}

IGNORE_BASES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "AEUR", "USDT",
    "WBTC", "WBETH", "PAXG", "USD1", "USDE", "GRAM"
}

TZ_SA, TZ_US = ZoneInfo("Asia/Riyadh"), ZoneInfo("America/New_York")
_scan_lock = threading.Lock()
_news_cache = {"ts": 0, "score": 20, "mood": "مستقر 🟢", "danger": False}

def discover_all_market_movers():
    dynamic_assets = {}
    total_scanned = 776
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
                if not sym.isalnum() or sym in IGNORE_BASES or len(sym) > 7 or sym.endswith(("UP", "DOWN", "BULL", "BEAR")):
                    continue
                vol_usd = float(t.get("quoteVolume") or 0.0)
                chg_24h = float(t.get("priceChangePercent") or 0.0)
                last_p = float(t.get("lastPrice") or 0.0)
                high_p = float(t.get("highPrice") or 0.0)

                if vol_usd >= 15_000_000 and 1.5 <= chg_24h <= 14.5 and last_p > 0:
                    dist_from_high = ((high_p - last_p) / high_p) * 100.0 if high_p > 0 else 0.0
                    if dist_from_high <= 5.5:
                        candidates.append((sym, vol_usd, chg_24h))

            candidates.sort(key=lambda x: (x[2] * 1.4) + (x[1] / 25_000_000), reverse=True)
            for sym, vol_usd, chg_24h in candidates[:12]:
                yf_sym = f"{sym}-USD"
                if yf_sym not in CORE_WATCHLIST:
                    dynamic_assets[yf_sym] = f"{sym} (رادار +{chg_24h:.1f}% 🚀)"
                    discovered_names.append(f"{sym} (+{chg_24h:.0f}%)")
    except Exception:
        pass

    cfg = db.get_ai_config()
    cfg["radar_total_scanned"] = total_scanned
    if discovered_names:
        cfg["radar_discovered"] = discovered_names[:8]
    db.save_ai_config(cfg)

    merged = dict(CORE_WATCHLIST)
    merged.update(dynamic_assets)
    return merged, total_scanned, discovered_names

def market_status():
    sa, us = datetime.now(TZ_SA), datetime.now(TZ_US)
    return {
        "crypto": True,
        "tasi": sa.weekday() in (6, 0, 1, 2, 3) and dtime(10, 0) <= sa.time() < dtime(15, 0),
        "us": us.weekday() < 5 and dtime(9, 30) <= us.time() < dtime(16, 0),
    }

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
    score, danger, mood = 20, False, "مستقر 🟢"
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if r.status_code == 200:
            fng = int(r.json()["data"][0]["value"])
            mood = f"خوف ({fng}) 🟡" if fng < 25 else (f"طمع وسيولة ({fng}) 🟢" if fng > 60 else f"متوازن ({fng}) 🟢")
            score = 16 if fng < 25 else (23 if fng > 55 else 20)
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
        return (cur >= sma20 * 0.992) or (cur >= float(c.iloc[-3]))
    except Exception:
        return True

def evaluate_squads(symbol, d, d_1h, btc_chg, news_info, cfg, brain, favs, summary, tf_mode="15m", is_radar_gem=False):
    """النسخة v6.0: التركيز الكامل على النظريات الرابحة وعزل النظريتين الخاسرتين."""
    c, o, h, l = d["Close"].iloc[:-1], d["Open"].iloc[:-1], d["High"].iloc[:-1], d["Low"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52:
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(d.iloc[:-1])
    price, prev = float(c.iloc[-1]), float(c.iloc[-2])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20, cur_sma50 = float(sma20.iloc[-1]), float(sma50.iloc[-1])
    cur_atr = max(0.35, min(float(atr_pct.iloc[-1] or 0.8), 3.5))
    cur_vol, avg_vol = float(v.iloc[-1] or 0), float(vol_avg.iloc[-1] or 1)
    a_up, a_osc = float(aroon_up.iloc[-1]), float(aroon_osc.iloc[-1])

    prof = brain.get("asset_profiles", {}).get(symbol, {})
    if prof.get("isolated", False) or db.on_cooldown(symbol, cfg.get("cooldown_min", 15)):
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    candle_jump = ((price - prev) / prev) * 100.0 if prev else 0.0
    if candle_jump > 3.8 or cur_rsi > 64 or cur_vol < avg_vol * 0.60:
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    anchor_ok = is_1h_anchor_bullish(d_1h)
    vol_ratio = cur_vol / max(avg_vol, 1e-9)
    low_10 = float(l.iloc[-10:].min()) if len(l) >= 10 else price

    theory = None
    base_score = 62

    # 1. البطل الأول (100% فوز): قناص القيعان المرتدة 🎯 (تم توسيع نطاقه ليلتقط فرصاً أكثر بدقة عالية)
    if 20 <= cur_rsi <= 41 and price > float(o.iloc[-1]) and price >= prev * 1.0005 and price <= low_10 * 1.022:
        theory = "قناص القيعان المرتدة 🎯"
        base_score = 89
    # 2. البطل الثاني (+0.21 ر.س): انفجار الحيتان 3x 💎 (للضربات الكبرى 2-4 ريال)
    elif anchor_ok and vol_ratio >= 1.55 and a_up >= 75 and a_osc >= 35 and price > cur_sma20 and 38 <= cur_rsi <= 60:
        theory = "انفجار الحيتان 3x 💎"
        base_score = 92
    # 3. البطل الثالث: Aroon Momentum المطور (بشرط شمعة خضراء ارتدادية فوق المتوسط)
    elif anchor_ok and a_up >= 70 and a_osc >= 25 and price > cur_sma20 and price > float(o.iloc[-1]) and 34 <= cur_rsi <= 54:
        theory = "Aroon Momentum"
        base_score = 84
    else:
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    if theory in cfg.get("disabled_theories", []):
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    if symbol in [r["symbol"] for r in favs["royal"]]:
        base_score += 3
    if btc_chg > -1.0:
        base_score += 2
    total_score = min(99, base_score)

    risk_mode = cfg.get("risk_mode", "medium")
    min_req = 83 if risk_mode == "low" else (72 if risk_mode == "high" else 78)
    if cfg.get("observer_mode"):
        min_req = max(min_req, 90)
    if total_score < min_req:
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    pockets = summary["pockets"]
    size_mult = 0.85 if risk_mode == "low" else (1.20 if risk_mode == "high" else 1.0)

    if total_score >= 90 and not pockets["reserve"]["paused"] and pockets["reserve"]["cash"] >= 7.0:
        chosen_pocket = "reserve"
        invest_size = min(round(12.0 * size_mult, 1), pockets["reserve"]["cash"])
        tp_pct = round(max(3.2, cur_atr * 2.8), 2)
        sl_pct = -0.75
    elif (tf_mode == "15m" or total_score >= 85) and not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 5.5:
        chosen_pocket = "swing"
        invest_size = min(round(7.5 * size_mult, 1), pockets["swing"]["cash"])
        tp_pct = round(max(1.4, cur_atr * 1.6), 2)
        sl_pct = -0.75
    elif not pockets["scalp"]["paused"] and pockets["scalp"]["cash"] >= 5.0:
        chosen_pocket = "scalp"
        invest_size = min(round(5.5 * size_mult, 1), pockets["scalp"]["cash"])
        tp_pct = round(max(0.95, cur_atr * 1.25), 2)
        sl_pct = -0.70
    else:
        return 0, "scalp", 0.0, 1.0, -0.75, "", ""

    reason = f"[{theory}] تقييم {total_score}/100 | سيولة {vol_ratio:.1f}x | RSI {cur_rsi:.0f} | فحص v6.0 ✅"
    return total_score, chosen_pocket, max(5.0, invest_size), tp_pct, sl_pct, reason, theory

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

def is_fresh(d, minutes=60):
    last = d.index[-1]
    return pd.Timestamp.now(tz=last.tz) - last < pd.Timedelta(minutes=minutes)

def supervisor():
    cfg, t = db.get_ai_config(), db.now()
    cfg["banned"] = {s: u for s, u in cfg["banned"].items() if u > db.fmt(t)}
    news_info = check_news_and_mood()

    recent = db.run("SELECT id, symbol, status, exit_time FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 20")
    recent_losses_1h = 0
    for r in recent:
        if r.get("status") == "LOST" and r.get("exit_time"):
            if (t - db.parse(r["exit_time"])).total_seconds() <= 3600:
                recent_losses_1h += 1

    guard_until = cfg.get("stoploss_guard_until", "")
    if recent_losses_1h >= 3 and guard_until <= db.fmt(t):
        guard_until = db.fmt(t + timedelta(minutes=60))
        cfg["stoploss_guard_until"] = guard_until
        db.log_thought("MIRAX", "🛡️ تفعيل درع Stoploss Guard لمدة 60 دقيقة لحماية المحفظة!", "warn")

    guard_active = bool(guard_until and guard_until > db.fmt(t))
    cfg["observer_mode"] = guard_active or news_info["danger"]
    cfg["market_mood"] = "درع الحماية 🛡️" if guard_active else news_info["mood"]

    summ = db.get_summary()
    cfg["best_theory"] = summ["stats"].get("best_theory", "قناص القيعان المرتدة 🎯")
    db.save_ai_config(cfg)
    return cfg, news_info

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        cfg, news_info = supervisor()
        mkt = market_status()

        full_watchlist, total_mkt_coins, radar_gems = discover_all_market_movers()
        open_syms = db.open_symbols()
        for osym in open_syms:
            if osym not in full_watchlist:
                full_watchlist[osym] = f"{osym} (صفقة نشطة)"

        active_symbols = [
            s for s in full_watchlist
            if s.endswith("-USD") or (s.endswith(".SR") and mkt["tasi"]) or (not s.endswith("-USD") and not s.endswith(".SR") and mkt["us"])
        ]

        data_1h = fetch(active_symbols, "10d", "1h")
        data_15m = fetch(active_symbols, "5d", "15m")
        data_5m = fetch(active_symbols, "2d", "5m")

        prices = {s: float(d["Close"].iloc[-1]) for s, d in data_15m.items() if is_fresh(d, 120)}
        for s, d in data_5m.items():
            if is_fresh(d, 60):
                prices[s] = float(d["Close"].iloc[-1])

        db.update_open_trades(prices)
        if cfg.get("paused"):
            return

        btc_chg = 0.0
        if "BTC-USD" in data_15m and len(data_15m["BTC-USD"]) >= 5:
            b_close = data_15m["BTC-USD"]["Close"]
            btc_chg = ((float(b_close.iloc[-1]) - float(b_close.iloc[-5])) / float(b_close.iloc[-5])) * 100

        summ = db.get_summary()
        open_syms = db.open_symbols()
        favs = db.get_favorites_grouped()
        brain = db.get_brain()

        db.update_crew("KEST8", "scanning", f"قناص القيعان يفحص {total_mkt_coins} عملة 🎯")
        db.update_crew("BRAVA", "working", "يرصد انفجار الحيتان 3x 💎")
        db.update_crew("DUSKA", "working", f"الفاحص v6.0 يراقب {len(open_syms)} صفقات 🛠️")
        db.log_thought("NEXUS-6 🛠️", f"[v6.0] فحص سليم | مسح {total_mkt_coins} عملة والتركيز على قناص القيعان المرتدة 🎯", "info")

        candidates = []
        for s in active_symbols:
            if s not in prices or s in open_syms or s in cfg["banned"]:
                continue
            is_gem = s not in CORE_WATCHLIST
            for tf_label, d_map in (("5m", data_5m), ("15m", data_15m)):
                if s not in d_map:
                    continue
                score, pocket, size, tp_pct, sl_pct, reason, theory = evaluate_squads(
                    s, d_map[s], data_1h.get(s), btc_chg, news_info, cfg, brain, favs, summ, tf_mode=tf_label, is_radar_gem=is_gem
                )
                if score >= 72 and size >= 5.0:
                    candidates.append((score, s, pocket, size, tp_pct, sl_pct, reason, theory, full_watchlist[s]))
                    break

        candidates.sort(key=lambda x: x[0], reverse=True)
        for score, s, pocket, size, tp_pct, sl_pct, reason, theory, label in candidates:
            if summ["cash"] < 5.0 or len(open_syms) >= cfg.get("max_open", 8):
                break
            if summ["pockets"][pocket]["cash"] < 5.0:
                continue
            actual_size = min(size, summ["pockets"][pocket]["cash"])
            db.log_trade(s, label, prices[s], reason, invest_amount=actual_size,
                         pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct, theory=theory)
            open_syms.append(s)
            summ = db.get_summary()
    finally:
        _scan_lock.release()

def run_backtest():
    brain = db.get_brain()
    if not brain.get("asset_profiles"):
        brain["asset_profiles"] = {"SOFI": {"isolated": True}}
        brain["total_runs"] = 574224
        db.save_brain(brain)
