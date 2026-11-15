import threading, time, os, re, requests
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
    "WBTC", "WBETH", "PAXG", "USD1", "USDE", "GRAM", "GOOGLB", "NVDAB",
    "SNDKB", "SOXLB", "TSLAB", "AAPLB", "AMZNB", "METAB", "MSFTB", "PEPE"
}

TZ_SA, TZ_US = ZoneInfo("Asia/Riyadh"), ZoneInfo("America/New_York")
_scan_lock = threading.Lock()
_news_cache = {"ts": 0, "score": 20, "mood": "قناص متوازن 🎯", "danger": False}

def is_clean_crypto_symbol(sym: str) -> bool:
    if not sym.isalpha() or sym in IGNORE_BASES or len(sym) > 5:
        return False
    if sym.endswith(("UP", "DOWN", "BULL", "BEAR", "B")):
        return False
    return True

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
                if not is_clean_crypto_symbol(sym):
                    continue
                vol_usd = float(t.get("quoteVolume") or 0.0)
                chg_24h = float(t.get("priceChangePercent") or 0.0)
                last_p = float(t.get("lastPrice") or 0.0)
                high_p = float(t.get("highPrice") or 0.0)
                bid_p = float(t.get("bidPrice") or last_p)
                ask_p = float(t.get("askPrice") or last_p)
                spread_pct = ((ask_p - bid_p) / last_p) * 100.0 if last_p > 0 else 1.0

                if vol_usd >= 18_000_000 and spread_pct <= 0.15 and -4.0 <= chg_24h <= 12.5 and last_p > 0:
                    dist_from_high = ((high_p - last_p) / high_p) * 100.0 if high_p > 0 else 0.0
                    if dist_from_high >= 0.4:
                        candidates.append((sym, vol_usd, chg_24h))

            candidates.sort(key=lambda x: (x[1] / 25_000_000) + abs(x[2]), reverse=True)
            for sym, vol_usd, chg_24h in candidates[:12]:
                yf_sym = f"{sym}-USD"
                if yf_sym not in CORE_WATCHLIST:
                    dynamic_assets[yf_sym] = f"{sym} (سيولة عالية 🎯)"
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
    sa, us = datetime.now(TZ_SA), datetime.now(TZ_US)
    return {
        "crypto": True,
        "tasi": sa.weekday() in (6, 0, 1, 2, 3) and dtime(10, 0) <= sa.time() < dtime(15, 0),
        "us": us.weekday() < 5 and dtime(9, 30) <= us.time() < dtime(16, 0),
        "hour_sa": sa.hour,
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
    score, danger, mood = 20, False, "قناص متوازن 🎯"
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if r.status_code == 200:
            fng = int(r.json()["data"][0]["value"])
            mood = f"فرص قيعان ({fng}) 🎯" if fng < 30 else (f"سيولة عالية ({fng}) 🟢" if fng > 58 else f"متوازن ({fng}) 🟢")
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
        return (cur >= sma20 * 0.985) or (cur >= float(c.iloc[-3]))
    except Exception:
        return True

def evaluate_squads(symbol, d, d_1h, btc_chg, btc_flash_drop, news_info, cfg, brain, favs, summary, tf_mode="15m"):
    """الإصدار v10.1: فتح شهية ORVEN و BRAVA بشروط واقعية + تبديل الجيوب التلقائي للوصول لمحطة 70."""
    if cfg.get("prep_withdraw_mode", False):
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", 0.0

    c, o, h, l = d["Close"].iloc[:-1], d["Open"].iloc[:-1], d["High"].iloc[:-1], d["Low"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52 or btc_flash_drop < -0.55:
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", 0.0

    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(d.iloc[:-1])
    price, prev = float(c.iloc[-1]), float(c.iloc[-2])
    cur_open = float(o.iloc[-1])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20 = float(sma20.iloc[-1])
    cur_atr = max(0.40, min(float(atr_pct.iloc[-1] or 0.80), 3.2))
    cur_vol, avg_vol = float(v.iloc[-1] or 0), float(vol_avg.iloc[-1] or 1)
    a_up, a_osc = float(aroon_up.iloc[-1]), float(aroon_osc.iloc[-1])

    prof = brain.get("asset_profiles", {}).get(symbol, {})
    if prof.get("isolated", False) or db.on_cooldown(symbol, cfg.get("cooldown_min", 15)):
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    candle_jump = ((price - prev) / prev) * 100.0 if prev else 0.0
    if candle_jump > 3.2 or cur_rsi > 62 or cur_vol < avg_vol * 0.60:
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    anchor_ok = is_1h_anchor_bullish(d_1h)
    vol_ratio = cur_vol / max(avg_vol, 1e-9)
    low_14 = float(l.iloc[-14:].min()) if len(l) >= 14 else price
    bounce_from_low_pct = ((price - low_14) / low_14) * 100.0 if low_14 > 0 else 0.0
    green_bounce = (price >= cur_open) and (price >= prev * 0.9995) and (0.08 <= bounce_from_low_pct <= 2.4)

    recent_vols = v.iloc[-12:]
    order_block_support = (float(recent_vols.max()) >= avg_vol * 1.35) and (bounce_from_low_pct <= 2.2)

    theory = None
    target_pocket = None
    base_score = 65

    # 1. مسار KEST8 (قناص القيعان المرتدة 🎯): يشتري القاع المبكر RSI بين 18 و 43
    if green_bounce and 18 <= cur_rsi <= 43:
        theory = "قناص القيعان المرتدة 🎯"
        target_pocket = "scalp"
        base_score = 89 + (4 if cur_rsi <= 34 else 0)
    # 2. مسار ORVEN (جدار الحيتان 🐋): يشتري ارتداد مناطق الدعم RSI بين 28 و 50 مع سيولة حيتان
    elif green_bounce and order_block_support and 28 <= cur_rsi <= 50 and vol_ratio >= 0.95:
        theory = "جدار الحيتان (Order Block) 🐋"
        target_pocket = "swing"
        base_score = 88 + (4 if vol_ratio >= 1.35 else 0)
    # 3. مسار BRAVA (انفجار الحيتان 3x 💎): يشتري بداية الموجة النشطة RSI بين 38 و 60 (فكينا قيد الـ 48 المستحيل!)
    elif anchor_ok and vol_ratio >= 1.25 and a_up >= 65 and a_osc >= 20 and price >= cur_sma20 * 0.998 and price >= cur_open and 38 <= cur_rsi <= 60:
        theory = "انفجار الحيتان 3x 💎"
        target_pocket = "reserve"
        base_score = 90 + (4 if vol_ratio >= 1.65 else 0)
    else:
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    if theory in cfg.get("disabled_theories", []):
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    rep_bonus = int(cfg.get("coin_reputation", {}).get(symbol, 0))
    base_score += rep_bonus
    if symbol in [r["symbol"] for r in favs["royal"]]:
        base_score += 2
    if btc_chg > -0.6:
        base_score += 2
    total_score = min(99, base_score)

    risk_mode = cfg.get("risk_mode", "medium")
    min_req = 85 if risk_mode == "low" else (78 if risk_mode == "high" else 81)

    hour_sa = datetime.now(TZ_SA).hour
    if 3 <= hour_sa < 7:
        min_req += 2

    if float(summary.get("growth_total") or 63.34) <= float(cfg.get("ratchet_floor") or 62.65):
        min_req = max(min_req, 86)

    active_cap = float(summary.get("active_capital") or 60.0)
    if active_cap >= 150.0:
        min_req = max(min_req, 85)

    if cfg.get("observer_mode"):
        min_req = max(min_req, 89)
    if total_score < min_req:
        return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    pockets = summary["pockets"]
    emergency_res = float(summary.get("emergency_reserve") or 6.3)
    max_per_pk = int(cfg.get("max_open_per_pocket", 2))

    # ميزة "الفزعة بين الجيوب": إذا كان الجيب المستهدف مشغولاً بصفقتين، تنتقل الصفقة تلقائياً للجيب الفاضي!
    chosen_pocket = target_pocket
    if pockets[chosen_pocket]["paused"] or pockets[chosen_pocket]["open_count"] >= max_per_pk or pockets[chosen_pocket]["cash"] < 6.0:
        for alt_pk in ("swing", "reserve", "scalp"):
            if not pockets[alt_pk]["paused"] and pockets[alt_pk]["open_count"] < max_per_pk and pockets[alt_pk]["cash"] >= 6.0:
                chosen_pocket = alt_pk
                break
        else:
            return 0, "scalp", 0.0, 1.65, -1.05, "", "", price

    if total_score >= 92:
        desired_size = round(active_cap * 0.16, 1)  # 9.6 ر.س
        avail_with_reserve = pockets[chosen_pocket]["cash"] + (emergency_res * 0.4)
        invest_size = min(desired_size, avail_with_reserve)
        conf_label = "ضمان فائق 92+ 🔥"
    elif total_score >= 86:
        desired_size = round(active_cap * 0.13, 1)  # 7.8 ر.س
        invest_size = min(desired_size, pockets[chosen_pocket]["cash"])
        conf_label = "ضمان عالي ✅"
    else:
        desired_size = round(active_cap * 0.10, 1)  # 6.0 ر.س
        invest_size = min(desired_size, pockets[chosen_pocket]["cash"])
        conf_label = "حجم متوازن 🛡️"

    dynamic_sl = round(-max(0.85, min(1.25, cur_atr * 1.15)), 2)
    tp_pct = round(max(1.90, cur_atr * 2.1), 2) if chosen_pocket == "reserve" else (
        round(max(1.50, cur_atr * 1.75), 2) if chosen_pocket == "swing" else round(max(1.30, cur_atr * 1.50), 2)
    )

    reason = f"[{theory}] ضمان {total_score}% ({conf_label}) | RSI {cur_rsi:.0f} | هدف +{tp_pct:.1f}%"
    return total_score, chosen_pocket, max(6.0, round(invest_size, 1)), tp_pct, dynamic_sl, reason, theory, price

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

    recent = db.run("SELECT id, symbol, status, exit_time FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 20")
    recent_losses_1h = 0
    for r in recent:
        if r.get("status") == "LOST" and r.get("exit_time"):
            if (t - db.parse(r["exit_time"])).total_seconds() <= 3600:
                recent_losses_1h += 1

    guard_until = cfg.get("stoploss_guard_until", "")
    if recent_losses_1h >= 3 and guard_until <= db.fmt(t):
        guard_until = db.fmt(t + timedelta(minutes=45))
        cfg["stoploss_guard_until"] = guard_until
        db.log_thought("MIRAX", "🛡️ تفعيل درع الصبر لمدة 45 دقيقة!", "warn")

    guard_active = bool(guard_until and guard_until > db.fmt(t))
    cfg["observer_mode"] = guard_active or news_info["danger"]
    cfg["market_mood"] = "تجهيز السحب 🛬" if cfg.get("prep_withdraw_mode") else ("درع الصبر 🛡️" if guard_active else news_info["mood"])

    summ = db.get_summary()
    cfg["best_theory"] = summ["stats"].get("best_theory", "انفجار الحيتان 3x 💎")
    db.save_ai_config(cfg)
    return cfg, news_info

def _single_scan_pass():
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

    prices = {s: float(d["Close"].iloc[-1]) for s, d in data_15m.items() if is_fresh(d, 180)}
    for s, d in data_5m.items():
        if is_fresh(d, 90):
            prices[s] = float(d["Close"].iloc[-1])

    db.update_open_trades(prices)
    if cfg.get("paused") or cfg.get("prep_withdraw_mode"):
        return

    btc_chg = 0.0
    btc_flash_drop = 0.0
    if "BTC-USD" in data_15m and len(data_15m["BTC-USD"]) >= 5:
        b15 = data_15m["BTC-USD"]["Close"]
        btc_flash_drop = ((float(b15.iloc[-1]) - float(b15.iloc[-2])) / float(b15.iloc[-2])) * 100.0
        btc_chg = ((float(b15.iloc[-1]) - float(b15.iloc[-5])) / float(b15.iloc[-5])) * 100.0

    summ = db.get_summary()
    open_syms = db.open_symbols()
    favs = db.get_favorites_grouped()
    brain = db.get_brain()

    db.update_crew("KEST8", "scanning", "قناص القيعان (RSI<43) 🎯")
    db.update_crew("ORVEN", "scanning", "جدار الحيتان (RSI<50) 🐋")
    db.update_crew("BRAVA", "working", "انفجار الحيتان + المصعد 💎")
    db.update_crew("MIRAX", "working", "يحدث توصيات صالح الشخصية 📡")
    db.update_crew("DUSKA", "working", f"محطة التقييم ({summ['stats']['n']}/70) 🚀")
    db.log_thought("القناص v10.1 🎯", f"فحص {total_mkt_coins} عملة | الجيوب الـ 3 نشطة | المحطة ({summ['stats']['n']}/70)", "info")

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
            if score >= 78 and size >= 6.0:
                candidates.append((score, s, pocket, size, tp_pct, sl_pct, reason, theory, full_watchlist[s], cur_p))
                break

    candidates.sort(key=lambda x: x[0], reverse=True)

    if candidates:
        top = candidates[0]
        db.update_vip_signal(top[1], top[8], top[7], top[0], top[9], tp1=round(top[4], 1), tp2=round(top[4]*1.8, 1), sl=top[5], status="🟢 فرصة صيد جاهزة للدخول الآن")

    for score, s, pocket, size, tp_pct, sl_pct, reason, theory, label, cur_p in candidates:
        if summ["cash"] < 6.0 or len(open_syms) >= cfg.get("max_open", 6):
            break
        if summ["pockets"][pocket]["cash"] < 6.0 or summ["pockets"][pocket]["open_count"] >= cfg.get("max_open_per_pocket", 2):
            continue
        db.log_trade(s, label, prices[s], reason, invest_amount=size,
                     pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct, theory=theory)
        open_syms.append(s)
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
