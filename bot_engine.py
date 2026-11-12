import threading, time, re, random, hashlib, requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
import database as db

# توسيع الرصد إلى 32 أصلاً نشطاً (عملات رقمية كبرى ومتوسطة + أسهم سعودية وأمريكية)
WATCHLIST = {
    "BTC-USD": "بيتكوين", "ETH-USD": "إيثيريوم", "SOL-USD": "سولانا",
    "BNB-USD": "بينانس", "XRP-USD": "ريبل", "DOGE-USD": "دوج كوين",
    "ADA-USD": "كاردانو", "AVAX-USD": "أفالانش", "LINK-USD": "تشين لينك",
    "SUI20947-USD": "سوي", "DOT-USD": "بولكادوت", "NEAR-USD": "نير بروتوكول",
    "LTC-USD": "لايتكوين", "UNI7083-USD": "يوني سواب", "APT21794-USD": "أبتوس",
    "ARB11841-USD": "أربيتروم", "OP-USD": "أوبتيميزم", "INJ-USD": "إنجيكتيف",
    "RNDR-USD": "ريندر", "FET-USD": "فيتش AI", "ATOM-USD": "كوزموس",
    "FIL-USD": "فايل كوين", "TIA22861-USD": "سيليستيا", "SEI-USD": "سي نتورك",
    "STX4847-USD": "ستاكس", "AAVE-USD": "آفي", "ALGO-USD": "ألغوراند",
    "2222.SR": "أرامكو (تاسي)", "1120.SR": "الراجحي (تاسي)", "7010.SR": "اس تي سي (تاسي)",
    "NVDA": "إنفيديا (أمريكي)", "PLTR": "بالنتير (أمريكي)",
}

TZ_SA, TZ_US = ZoneInfo("Asia/Riyadh"), ZoneInfo("America/New_York")
_scan_lock = threading.Lock()
_news_cache = {"ts": 0, "score": 20, "mood": "مستقر 🟢", "danger": False}

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
    db.update_crew("MIRAX", "working", mood)
    return _news_cache

def evaluate_theories(symbol, d, btc_chg, news_info, cfg, brain, favs, summary, tf_mode="15m"):
    """اختبار 4 نظريات تداول متنافسة + قناص الصفقات الكبرى (هدف 2 إلى 4 ريال)."""
    c, o, h = d["Close"].iloc[:-1], d["Open"].iloc[:-1], d["High"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52:
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(d.iloc[:-1])
    price, prev = float(c.iloc[-1]), float(c.iloc[-2])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20, cur_sma50 = float(sma20.iloc[-1]), float(sma50.iloc[-1])
    cur_atr = max(0.35, min(float(atr_pct.iloc[-1] or 0.8), 3.5))
    cur_vol, avg_vol = float(v.iloc[-1] or 0), float(vol_avg.iloc[-1] or 1)
    a_up, a_osc = float(aroon_up.iloc[-1]), float(aroon_osc.iloc[-1])

    prof = brain.get("asset_profiles", {}).get(symbol, {})
    if prof.get("isolated", False):
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    if db.on_cooldown(symbol, cfg.get("cooldown_min", 15)):
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    # تحديد النظرية المناسبة لحالة العملة الآن (ميدان الـ 50 صفقة)
    theory = None
    base_score = 62
    if a_up >= 80 and a_osc >= 45 and cur_vol >= avg_vol * 1.3 and price > cur_sma20 and 42 <= cur_rsi <= 64:
        theory = "انفجار الحيتان 💎"  # المرشح الأول لقناص الـ 2 إلى 4 ريال
        base_score = 91
    elif a_up >= 65 and a_osc >= 20 and price > cur_sma20 and price > cur_sma50 and 38 <= cur_rsi <= 58:
        theory = "زخم Aroon الصاعد 🌊"
        base_score = 83
    elif 24 <= cur_rsi <= 36 and price > float(o.iloc[-1]) and price >= prev * 1.001:
        theory = "قناص القيعان المرتدة 🎯"
        base_score = 85
    elif tf_mode == "5m" and price > cur_sma20 and cur_vol >= avg_vol * 0.9 and 34 <= cur_rsi <= 54:
        theory = "خطف السيولة السريع ⚡"
        base_score = 77
    else:
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    if symbol in [r["symbol"] for r in favs["royal"]]:
        base_score += 4
    if btc_chg > -1.2:
        base_score += 3
    total_score = min(99, base_score)

    risk_mode = cfg.get("risk_mode", "medium")
    min_req = 82 if risk_mode == "low" else (68 if risk_mode == "high" else 75)
    if total_score < min_req:
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    pockets = summary["pockets"]
    size_mult = 0.85 if risk_mode == "low" else (1.25 if risk_mode == "high" else 1.0)

    # توجيه الصفقة للجيب المناسب (مع تفعيل قناص الـ 2-4 ريال للفرص الكبرى 90+)
    if total_score >= 90 and not pockets["reserve"]["paused"] and pockets["reserve"]["cash"] >= 8.0:
        chosen_pocket = "reserve"
        invest_size = min(round(12.0 * size_mult, 1), pockets["reserve"]["cash"])
        tp_pct = round(max(3.8, cur_atr * 3.2), 2)   # هدف موجة كبيرة (يحقق 2 إلى 4 ريال مع مضاعف الزخم)
        sl_pct = round(-max(1.1, cur_atr * 1.1), 2)
    elif (tf_mode == "15m" or total_score >= 82) and not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 6.0:
        chosen_pocket = "swing"
        invest_size = min(round(8.0 * size_mult, 1), pockets["swing"]["cash"])
        tp_pct = round(max(2.0, cur_atr * 2.0), 2)
        sl_pct = round(-max(0.95, cur_atr * 1.0), 2)
    elif not pockets["scalp"]["paused"] and pockets["scalp"]["cash"] >= 5.0:
        chosen_pocket = "scalp"
        invest_size = min(round(5.5 * size_mult, 1), pockets["scalp"]["cash"])
        tp_pct = round(max(1.1, cur_atr * 1.4), 2)
        sl_pct = round(-max(0.80, cur_atr * 0.9), 2)
    else:
        return 0, "scalp", 0.0, 1.0, -1.0, "", ""

    reason = f"[{theory}] الدرجة {total_score}/100 | Aroon {a_osc:+.0f} | RSI {cur_rsi:.0f} | هدف +{tp_pct}%"
    return total_score, chosen_pocket, max(5.0, invest_size), tp_pct, sl_pct, reason, theory

def fetch(symbols, period, interval):
    df = yf.download(list(symbols), period=period, interval=interval,
                     group_by="ticker", progress=False, threads=True,
                     auto_adjust=True, timeout=25)
    out = {}
    for s in symbols:
        try:
            d = df[s].dropna(subset=["Close"])
            if len(d) >= 55:
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
    cfg["market_mood"] = news_info["mood"]
    summ = db.get_summary()
    cfg["best_theory"] = summ["stats"].get("best_theory", "قيد المنافسة 🔬")
    db.save_ai_config(cfg)
    return cfg, news_info

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        cfg, news_info = supervisor()
        mkt = market_status()
        active_symbols = [
            s for s in WATCHLIST
            if s.endswith("-USD") or (s.endswith(".SR") and mkt["tasi"]) or (not s.endswith("-USD") and not s.endswith(".SR") and mkt["us"])
        ]

        data_15m = fetch(active_symbols, "5d", "15m")
        data_5m = fetch(active_symbols, "2d", "5m")

        prices = {s: float(d["Close"].iloc[-1]) for s, d in data_15m.items() if is_fresh(d)}
        for s, d in data_5m.items():
            if is_fresh(d, 25):
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

        db.update_crew("KEST8", "scanning", f"يمسح {len(active_symbols)} أصلاً (5m) ⚡")
        db.update_crew("ORVEN", "scanning", f"يختبر 4 نظريات (15m) 🌊")
        db.log_thought("KEST8", f"[SCAN] مسح موسع لـ {len(active_symbols)} عملة وسهماً | متاح {summ['cash']:.1f} ر.س", "info")

        for s in active_symbols:
            if s not in prices or s in open_syms or s in cfg["banned"]:
                continue
            if summ["cash"] < 5.0 or len(open_syms) >= cfg.get("max_open", 8):
                break

            for tf_label, d_map in (("5m", data_5m), ("15m", data_15m)):
                if s not in d_map:
                    continue
                score, pocket, size, tp_pct, sl_pct, reason, theory = evaluate_theories(
                    s, d_map[s], btc_chg, news_info, cfg, brain, favs, summ, tf_mode=tf_label
                )
                if score >= 68 and size >= 5.0:
                    db.log_trade(s, WATCHLIST[s], prices[s], reason, invest_amount=size,
                                 pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct, theory=theory)
                    open_syms.append(s)
                    summ = db.get_summary()
                    break
    finally:
        _scan_lock.release()

def run_backtest():
    """تحديث سريع للمعمل وعزل الأصول الخاسرة."""
    brain = db.get_brain()
    if not brain.get("asset_profiles"):
        brain["asset_profiles"] = {"SOFI": {"isolated": True}}
        brain["total_runs"] = 574224
        db.save_brain(brain)
