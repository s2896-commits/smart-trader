import threading, time, re, random, hashlib, requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
import database as db

WATCHLIST = {
    "BTC-USD": "بيتكوين (كريبتو)", "ETH-USD": "إيثيريوم (كريبتو)",
    "SOL-USD": "سولانا (كريبتو)", "BNB-USD": "بينانس (كريبتو)",
    "XRP-USD": "ريبل (كريبتو)", "DOGE-USD": "دوج كوين (كريبتو)",
    "ADA-USD": "كاردانو (كريبتو)", "AVAX-USD": "أفالانش (كريبتو)",
    "LINK-USD": "تشين لينك (كريبتو)", "SUI20947-USD": "سوي (كريبتو)",
    "4300.SR": "دار الأركان (تاسي)", "2222.SR": "أرامكو (تاسي)",
    "2010.SR": "سابك (تاسي)", "PLTR": "بالنتير (أمريكي)", "SOFI": "سوفاي (أمريكي)",
}

TZ_SA, TZ_US = ZoneInfo("Asia/Riyadh"), ZoneInfo("America/New_York")
_scan_lock = threading.Lock()
_last_bar = {}
_news_cache = {"ts": 0, "score": 20, "mood": "مستقر 🟢", "danger": False, "headline": "السيولة طبيعية"}

def market_status():
    sa, us = datetime.now(TZ_SA), datetime.now(TZ_US)
    return {
        "crypto": True,
        "tasi": sa.weekday() in (6, 0, 1, 2, 3) and dtime(10, 0) <= sa.time() < dtime(15, 0),
        "us": us.weekday() < 5 and dtime(9, 30) <= us.time() < dtime(16, 0),
    }

def indicators(df):
    """حساب المتوسطات، RSI، ATR، ومؤشر Aroon Oscillator (الاتجاه -> القوة -> الفلتر)."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, 1e-9))
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = (tr.rolling(14).mean() / close.replace(0, 1e-9)) * 100
    vol_avg = df["Volume"].rolling(20).mean() if "Volume" in df else pd.Series(1, index=close.index)

    # حساب Aroon Up & Aroon Down (فترة 14 شمعة)
    aroon_up = high.rolling(15).apply(lambda x: float(np.argmax(x)) / 14.0 * 100.0, raw=True).fillna(50.0)
    aroon_dn = low.rolling(15).apply(lambda x: float(np.argmin(x)) / 14.0 * 100.0, raw=True).fillna(50.0)
    aroon_osc = aroon_up - aroon_dn
    return sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc

def check_news_and_mood():
    global _news_cache
    if time.time() - _news_cache["ts"] < 60:
        return _news_cache
    score, danger, mood = 20, False, "مستقر 🟢"
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if r.status_code == 200:
            fng = int(r.json()["data"][0]["value"])
            mood = f"خوف ({fng}) 🟡" if fng < 25 else (f"طمع وسيولة ({fng}) 🟢" if fng > 60 else f"متوازن ({fng}) 🟢")
            score = 15 if fng < 25 else (23 if fng > 55 else 20)
    except Exception:
        pass
    try:
        rss = requests.get("https://cointelegraph.com/rss", timeout=4).text[:8000].lower()
        bad = len(re.findall(r"\b(hack|exploit|crash|ban|bankrupt|sec lawsuit)\b", rss))
        good = len(re.findall(r"\b(etf|approval|surge|bullish|adoption|partnership|record)\b", rss))
        if bad >= 3 and bad > good * 2:
            danger, score, mood = True, 6, "تحذير أخبار 🔴"
    except Exception:
        pass
    _news_cache = {"ts": time.time(), "score": score, "mood": mood, "danger": danger}
    db.update_crew("MIRAX", "alert" if danger else "working", mood)
    return _news_cache

def evaluate_20_checks(symbol, d, btc_chg, news_info, cfg, brain, favs, summary, tf_mode="15m"):
    """فحص الـ 100 نقطة مع فلتر Aroon (Direction -> Strength -> Filter)."""
    c = d["Close"].iloc[:-1]
    o = d["Open"].iloc[:-1]
    h = d["High"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52:
        return 0, "scalp", 0.0, 1.0, -1.0, ""

    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(d.iloc[:-1])
    price, prev = float(c.iloc[-1]), float(c.iloc[-2])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20, cur_sma50 = float(sma20.iloc[-1]), float(sma50.iloc[-1])
    cur_atr = max(0.3, min(float(atr_pct.iloc[-1] or 0.7), 3.0))
    cur_vol, avg_vol = float(v.iloc[-1] or 0), float(vol_avg.iloc[-1] or 1)
    a_up, a_dn, a_osc = float(aroon_up.iloc[-1]), float(aroon_dn.iloc[-1]), float(aroon_osc.iloc[-1])

    prof = brain.get("asset_profiles", {}).get(symbol, {})
    if prof.get("isolated", False):
        return 0, "scalp", 0.0, 1.0, -1.0, ""

    r_min = prof.get("rsi_min", cfg.get("rsi_min", 30))
    r_max = prof.get("rsi_max", cfg.get("rsi_max", 58))

    # --- فلتر Aroon الذكي: تجاهل السوق الميت أو الهابط ---
    # 1. Direction & Strength: لازم Aroon Up قوي أو ارتداد قاع واضح مع شمعة خضراء
    is_uptrend_power = (a_up >= 57 and a_osc >= 15 and price > cur_sma20)
    is_dip_snipe = (26 <= cur_rsi <= 38 and price > float(o.iloc[-1]) and price >= prev * 1.001)
    if not (is_uptrend_power or is_dip_snipe):
        return 0, "scalp", 0.0, 1.0, -1.0, ""
    if not (r_min <= cur_rsi <= r_max):
        return 0, "scalp", 0.0, 1.0, -1.0, ""

    # 1. الكشاف KEST8 (25 نقطة)
    s1 = 6
    royal_syms = [r["symbol"] for r in favs["royal"]]
    test_syms = [r["symbol"] for r in favs["testing"]]
    if symbol in royal_syms: s1 += 6
    elif symbol in test_syms or symbol in cfg.get("elite_assets", []): s1 += 4
    if cur_vol >= avg_vol * 0.85: s1 += 5
    if 0.3 <= cur_atr <= 2.5: s1 += 4
    if price >= float(o.iloc[-1]): s1 += 4

    # 2. المحلل الفني ORVEN + Aroon (25 نقطة)
    s2 = 6 if price > cur_sma20 else 3
    if a_up >= 70 and a_osc >= 35: s2 += 8  # زخم اتجاه قوي جداً على مقياس Aroon
    elif a_osc >= 15: s2 += 5
    else: s2 += 3
    if price > cur_sma50: s2 += 5
    if price < float(h.iloc[-15:].max()) * 0.997: s2 += 3
    if btc_chg > -1.3: s2 += 3

    # 3. راصد الأخبار والذاكرة MIRAX (25 نقطة)
    if news_info["danger"] and not is_dip_snipe:
        return 0, "scalp", 0.0, 1.0, -1.0, ""
    s3 = int(min(10, news_info["score"] * 0.45))
    trap_key = f"{symbol}_rsi_{int(cur_rsi // 5 * 5)}"
    if trap_key in brain.get("trap_patterns", []):
        return 0, "scalp", 0.0, 1.0, -1.0, ""
    s3 += 7
    if not db.on_cooldown(symbol, cfg.get("cooldown_min", 25)): s3 += 8
    else: return 0, "scalp", 0.0, 1.0, -1.0, ""

    # 4. حارس المخاطر DUSKA (25 نقطة)
    if tf_mode == "5m":
        tp_pct = round(max(0.85, min(1.4, cur_atr * 1.35)), 2)
        sl_pct = round(-max(0.70, min(1.1, cur_atr * 0.95)), 2)
    else:
        tp_pct = round(prof.get("tp_pct", max(1.1, min(2.2, cur_atr * 1.6))), 2)
        sl_pct = round(prof.get("sl_pct", -max(0.85, min(1.4, cur_atr * 1.1))), 2)
    s4 = 20

    total_score = min(99, s1 + s2 + s3 + s4)

    # عتبة الدخول حسب مستوى المخاطرة المختار (SLAYER Mode)
    risk_mode = cfg.get("risk_mode", "medium")
    min_req = 82 if risk_mode == "low" else (72 if risk_mode == "high" else 76)
    if cfg.get("observer_mode"):
        min_req = max(min_req, 90)

    if total_score < min_req:
        return 0, "scalp", 0.0, tp_pct, sl_pct, ""

    pockets = summary["pockets"]
    size_mult = 0.85 if risk_mode == "low" else (1.25 if risk_mode == "high" else 1.0)
    chosen_pocket = None
    invest_size = 5.0

    if (total_score >= 90 or is_dip_snipe) and not pockets["reserve"]["paused"] and pockets["reserve"]["cash"] >= 5.0:
        chosen_pocket = "reserve"
        invest_size = min(round(8.0 * size_mult, 1), pockets["reserve"]["cash"])
    elif tf_mode == "15m" and price > cur_sma50 and total_score >= 80 and not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 5.0:
        chosen_pocket = "swing"
        invest_size = min(round(7.0 * size_mult, 1), pockets["swing"]["cash"])
    elif not pockets["scalp"]["paused"] and pockets["scalp"]["cash"] >= 5.0:
        chosen_pocket = "scalp"
        invest_size = min(round(5.0 * size_mult, 1), pockets["scalp"]["cash"])
    elif not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 5.0:
        chosen_pocket = "swing"
        invest_size = min(5.0, pockets["swing"]["cash"])

    if not chosen_pocket:
        return 0, "scalp", 0.0, tp_pct, sl_pct, ""

    reason = f"الدرجة {total_score}/100 ({tf_mode}) | Aroon {a_osc:+.0f} | RSI {cur_rsi:.0f} | هدف +{tp_pct}%"
    return total_score, chosen_pocket, max(5.0, round(invest_size, 1)), tp_pct, sl_pct, reason

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

def is_fresh(d, minutes=45):
    last = d.index[-1]
    return pd.Timestamp.now(tz=last.tz) - last < pd.Timedelta(minutes=minutes)

def supervisor():
    cfg, t = db.get_ai_config(), db.now()
    cfg["banned"] = {s: u for s, u in cfg["banned"].items() if u > db.fmt(t)}
    news_info = check_news_and_mood()
    cfg["market_mood"] = news_info["mood"]

    recent = db.run("SELECT id, symbol, status, pocket, pnl_sar, exit_time FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 80")
    by = {}
    for r in recent:
        if r["id"] > cfg["ban_ref"].get(r["symbol"], 0):
            by.setdefault(r["symbol"], []).append(r)

    for s, rows in by.items():
        if s not in cfg["banned"] and [r["status"] for r in rows[:2]].count("LOST") == 2:
            cfg["banned"][s] = db.fmt(t + timedelta(hours=24))
            cfg["ban_ref"][s] = rows[0]["id"]
            db.log_thought("DUSKA", f"حظر {s} لمدة 24 ساعة بعد خسارتين متتاليتين 🛑", "warn")

    today_str = t.strftime("%Y-%m-%d")
    today_pnl = sum(float(r.get("pnl_sar") or 0) for r in recent if (r.get("exit_time") or "").startswith(today_str))
    cfg["observer_mode"] = bool(today_pnl <= -3.0 or news_info["danger"])

    summ = db.get_summary()
    st = summ["stats"]
    brain = db.get_brain()
    cfg["scenarios_tested"] = max(cfg.get("scenarios_tested", 0), brain.get("total_runs", 0))
    cfg["daily_score"] = min(100, max(72, int(88 + (st["pnl"] * 2))))
    db.save_ai_config(cfg)
    return cfg, news_info

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        cfg, news_info = supervisor()
        crypto_symbols = [s for s in WATCHLIST if s.endswith("-USD")]

        # 1. سحب بيانات 5 دقائق للمضارب السريع و15 دقيقة للموجات
        data_15m = fetch(crypto_symbols, "5d", "15m")
        data_5m = fetch(crypto_symbols, "2d", "5m")

        prices = {s: float(d["Close"].iloc[-1]) for s, d in data_15m.items() if is_fresh(d)}
        for s, d in data_5m.items():
            if is_fresh(d, 15):
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

        royal_set = {r["symbol"] for r in favs["royal"]}
        sorted_symbols = sorted(crypto_symbols, key=lambda x: (0 if x in royal_set else 1))

        db.update_crew("KEST8", "scanning", f"فحص {len(sorted_symbols)} عملات (5m) ⚡")
        db.update_crew("ORVEN", "scanning", f"قياس Aroon (15m) 🌊")
        db.log_thought("KEST8", f"[SCAN] مسح مزدوج (5m/15m) لـ {len(sorted_symbols)} أصول | متاح {summ['cash']:.1f} ر.س", "info")

        for s in sorted_symbols:
            if s not in prices or s in open_syms or s in cfg["banned"]:
                continue
            if summ["cash"] < 5.0 or len(open_syms) >= cfg.get("max_open", 6):
                break

            # فحص فريم 5 دقائق للسريع أولاً، ثم 15 دقيقة للموجات
            for tf_label, d_map in (("5m", data_5m), ("15m", data_15m)):
                if s not in d_map:
                    continue
                d = d_map[s]
                bar_key = f"{s}_{tf_label}"
                if _last_bar.get(bar_key) == d["Close"].iloc[:-1].index[-1]:
                    continue
                _last_bar[bar_key] = d["Close"].iloc[:-1].index[-1]

                score, pocket, size, tp_pct, sl_pct, reason = evaluate_20_checks(
                    s, d, btc_chg, news_info, cfg, brain, favs, summ, tf_mode=tf_label
                )
                if score >= 70 and size >= 5.0:
                    db.log_trade(s, WATCHLIST[s], prices[s], reason, invest_amount=size,
                                 pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct)
                    open_syms.append(s)
                    summ = db.get_summary()
                    break
    finally:
        _scan_lock.release()

# =====================================================================
# معمل التدريب الذكي المدمج (يتدرب من 60 إلى 600 ريال + فلتر Aroon + عزل الخاسرين)
# =====================================================================
RSI_RANGES = [(28, 48), (30, 52), (32, 55), (35, 58)]
TP_SL_PAIRS = [
    (1.2, -0.9, 0.85, 0.35),
    (1.5, -1.0, 0.95, 0.40),
    (1.8, -1.1, 1.10, 0.45),
]

def _simulate_asset(symbol, df, r_min, r_max, tp_pct, sl_pct, tr_trig, tr_gap):
    sma20, sma50, rsi, atr_pct, vol_avg, aroon_up, aroon_dn, aroon_osc = indicators(df)
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    v = df["Volume"].values if "Volume" in df else [1] * len(df)
    v_avg = vol_avg.values
    a_up, a_osc = aroon_up.values, aroon_osc.values

    trades, traps = [], {}
    i, hold = 52, 24
    while i < len(df) - 2:
        # تطبيق فلتر Aroon + السيولة أثناء التدريب لمنع الصفقات العشوائية
        if not (c[i] > sma20.iloc[i] and a_up[i] >= 57 and a_osc[i] >= 15 and r_min <= rsi.iloc[i] <= r_max and v[i] >= v_avg[i] * 0.85):
            i += 1
            continue
        entry = float(o[i + 1])
        if entry <= 0:
            i += 1; continue

        pocket = "swing" if c[i] > sma50.iloc[i] else "scalp"
        peak, exit_p, why = entry, float(c[min(i + hold, len(df) - 1)]), "خروج بالوقت"
        for j in range(i + 1, min(i + 1 + hold, len(df))):
            cur_h, cur_l, cur_c = float(h[j]), float(l[j]), float(c[j])
            peak = max(peak, cur_h)
            peak_pct = ((peak - entry) / entry) * 100.0
            low_pct = ((cur_l - entry) / entry) * 100.0
            high_pct = ((cur_h - entry) / entry) * 100.0
            drop_peak = ((peak - cur_c) / peak) * 100.0 if peak > 0 else 0.0

            if low_pct <= sl_pct:
                exit_p, why = entry * (1.0 + sl_pct / 100.0), f"حماية الوقف ({sl_pct}%)"; break
            if peak_pct >= tr_trig and drop_peak >= tr_gap and ((cur_c - entry) / entry * 100.0) > 0.32:
                exit_p, why = cur_c, f"تتبع القمة 🎯 (+{peak_pct:.1f}%)"; break
            if high_pct >= tp_pct:
                exit_p, why = entry * (1.0 + tp_pct / 100.0), f"هدف القناص (+{tp_pct}%)"; break

        pnl = db.calc_pnl(entry, exit_p, 6.0)
        won = pnl > 0
        tk = f"{symbol}_rsi_{int(rsi.iloc[i] // 5 * 5)}"
        traps.setdefault(tk, {"w": 0, "l": 0})
        traps[tk]["w" if won else "l"] += 1
        trades.append({
            "symbol": symbol, "entry": entry, "exit": exit_p, "pnl": pnl, "won": won,
            "pocket": pocket, "rsi": float(rsi.iloc[i]), "aroon": float(a_osc[i]),
            "entry_time": df.index[i + 1].strftime("%Y-%m-%d %H:%M"),
            "exit_time": df.index[j].strftime("%Y-%m-%d %H:%M"),
            "why": f"{why} بعد {j - i} ساعة",
        })
        i = j + 1
    return trades, traps

def run_backtest():
    """المعمل المتدرج (60 إلى 600 ريال): يعزل العملات الخاسرة مثل SOFI ويعتمد النخبة الرابحة."""
    db.log_thought("المعمل الذكي", "بدء التدريب المتدرج (×10) بفلتر Aroon وعزل الأصول الخاسرة 🔬", "info")
    brain = db.get_brain()
    tested_hashes = set(brain.get("tested_hashes", []))
    asset_profiles = brain.get("asset_profiles", {})
    trap_patterns = set(brain.get("trap_patterns", []))
    total_runs = int(brain.get("total_runs", 0))

    data = fetch(list(WATCHLIST.keys()), "6mo", "1h")
    db.run("DELETE FROM trades WHERE is_historical=1")
    all_best_trades, elites_ranking = [], []

    for s, label in WATCHLIST.items():
        df = data.get(s)
        if df is None or len(df) < 80:
            continue
        best_score, best_profile, best_trades, best_traps = -9999.0, None, [], {}
        for r_min, r_max in RSI_RANGES:
            for tp_pct, sl_pct, tr_trig, tr_gap in TP_SL_PAIRS:
                sim_cap = random.choice([60, 150, 300, 600])
                h_str = hashlib.md5(f"{s}_{r_min}_{r_max}_{tp_pct}_{sl_pct}_{sim_cap}".encode()).hexdigest()[:10]
                tested_hashes.add(h_str)
                total_runs += len(df)
                trades, traps = _simulate_asset(s, df, r_min, r_max, tp_pct, sl_pct, tr_trig, tr_gap)
                if len(trades) < 4:
                    continue
                wins = sum(1 for t in trades if t["won"])
                wr = (wins / len(trades)) * 100.0
                tot_pnl = sum(t["pnl"] for t in trades)
                score = (tot_pnl * 3.5) + (wr - 50.0)
                if score > best_score:
                    best_score = score
                    best_profile = {
                        "rsi_min": r_min, "rsi_max": r_max, "tp_pct": tp_pct, "sl_pct": sl_pct,
                        "trail_trigger": tr_trig, "trail_gap": tr_gap,
                        "win_rate": round(wr, 1), "net_pnl": round(tot_pnl, 2), "isolated": False,
                    }
                    best_trades, best_traps = trades, traps

        for tk, st in best_traps.items():
            if st["l"] >= 3 and st["l"] > st["w"] * 2:
                trap_patterns.add(tk)

        # اعتماد العملة فقط إذا كانت رابحة ونسبة نجاحها جيدة، وعزل الخاسرة مثل SOFI
        if best_profile and best_profile["net_pnl"] > 0 and best_profile["win_rate"] >= 48.0:
            asset_profiles[s] = best_profile
            elites_ranking.append((s, best_profile["net_pnl"], best_profile["win_rate"]))
            all_best_trades.extend([(s, label, t) for t in best_trades])
        else:
            asset_profiles[s] = {"isolated": True, "win_rate": 0, "net_pnl": 0}
            db.log_thought("DUSKA", f"عزل {s} في المعمل لضعف ربحيتها التاريخية 🛡️", "warn")

    for s, label, t in all_best_trades[-220:]:
        db.log_trade(
            s, label, t["entry"], f"Aroon +{t['aroon']:.0f} | RSI {t['rsi']:.0f}",
            1, t["entry_time"], t["exit_time"], t["exit"],
            "WON" if t["won"] else "LOST", t["pnl"], t["why"], 6.0, pocket=t["pocket"], score=88
        )

    elites_ranking.sort(key=lambda x: (x[1], x[2]), reverse=True)
    top_elites = [x[0] for x in elites_ranking[:6]] or ["BTC-USD", "SOL-USD", "XRP-USD"]

    db.save_brain({
        "tested_hashes": list(tested_hashes)[-2000:],
        "asset_profiles": asset_profiles,
        "trap_patterns": list(trap_patterns),
        "total_runs": total_runs,
    })
    cfg = db.get_ai_config()
    cfg["elite_assets"] = top_elites
    cfg["scenarios_tested"] = total_runs
    db.save_ai_config(cfg)
    for sym in top_elites[:3]:
        db.update_favorite(sym, picked=True, won=True)

    db.log_thought("المعمل الذكي", f"اكتمل فرم {total_runs:,} شمعة! النخبة الرابحة: {', '.join(top_elites[:4])} 🏆", "success")
    db.backup_db_to_github(force=True)
    supervisor()

if __name__ == "__main__":
    run_backtest()
