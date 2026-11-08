import threading, time, re, requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
import database as db

# التركيز الحالي في التداول الحي على العملات الرقمية (24/7)، مع إبقاء الأسهم للمختبر والتدريب
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
_news_cache = {"ts": 0, "score": 20, "mood": "مستقر 🟢", "danger": False, "headline": "الأجواء هادئة في السوق"}

def asset_class(s):
    return "crypto" if s.endswith("-USD") else "tasi" if s.endswith(".SR") else "us"

def market_status():
    sa, us = datetime.now(TZ_SA), datetime.now(TZ_US)
    return {
        "crypto": True,
        "tasi": sa.weekday() in (6, 0, 1, 2, 3) and dtime(10, 0) <= sa.time() < dtime(15, 0),
        "us": us.weekday() < 5 and dtime(9, 30) <= us.time() < dtime(16, 0),
    }

def indicators(df):
    """حساب المتوسطات، مؤشر RSI، ومتوسط التذبذب ATR لتحديد وقف الخسارة الذكي."""
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
    return sma20, sma50, rsi, atr_pct, vol_avg

def check_news_and_mood():
    """المساعد 3 (راصد الأخبار): يفحص مؤشر الخوف والطمع والأخبار العاجلة كل 60 ثانية."""
    global _news_cache
    if time.time() - _news_cache["ts"] < 60:
        return _news_cache

    score = 20
    danger = False
    mood = "مستقر 🟢"
    headline = "لا توجد أخبار سلبية خطيرة"

    # 1. فحص مؤشر الخوف والطمع (Fear & Greed)
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if r.status_code == 200:
            fng = int(r.json()["data"][0]["value"])
            if fng < 20:
                score = 12
                mood = f"خوف شديد ({fng}) 🟡"
            elif fng > 60:
                score = 24
                mood = f"تفاؤل وسيولة ({fng}) 🟢"
            else:
                mood = f"متوازن ({fng}) 🟢"
    except Exception:
        pass

    # 2. مسح عناوين الأخبار السريع
    try:
        rss = requests.get("https://cointelegraph.com/rss", timeout=4).text[:8000].lower()
        bad_words = len(re.findall(r"\b(hack|exploit|crash|ban|bankrupt|sec lawsuit)\b", rss))
        good_words = len(re.findall(r"\b(etf|approval|surge|bullish|adoption|partnership|record)\b", rss))
        if bad_words >= 3 and bad_words > good_words * 2:
            danger = True
            score = 5
            mood = "تحذير أخبار سلبية 🔴"
            headline = "رصد كلمات خطر في الأخبار العاجلة — تفعيل الحذر"
        elif good_words > bad_words:
            score = min(25, score + 3)
            headline = "الأخبار الإيجابية تدعم السيولة اليوم"
    except Exception:
        pass

    _news_cache = {"ts": time.time(), "score": score, "mood": mood, "danger": danger, "headline": headline}
    return _news_cache

def evaluate_20_checks(symbol, d, btc_chg, news_info, cfg, brain, favs, summary):
    """فريق المساعدين الأربعة (20 فحصاً = 100 نقطة) + تحديد الجيب ووقف الخسارة."""
    c = d["Close"].iloc[:-1]
    o = d["Open"].iloc[:-1]
    h = d["High"].iloc[:-1]
    v = d["Volume"].iloc[:-1] if "Volume" in d else pd.Series(1, index=c.index)
    if len(c) < 52:
        return 0, "scalp", 0.0, 1.2, -1.2, ""

    sma20, sma50, rsi, atr_pct, vol_avg = indicators(d.iloc[:-1])
    price = float(c.iloc[-1])
    prev = float(c.iloc[-2])
    cur_rsi = float(rsi.iloc[-1])
    cur_sma20 = float(sma20.iloc[-1])
    cur_sma50 = float(sma50.iloc[-1])
    cur_atr = max(0.35, min(float(atr_pct.iloc[-1] or 0.8), 3.0))
    cur_vol = float(v.iloc[-1] or 0)
    avg_vol = float(vol_avg.iloc[-1] or 1)

    # جلب الإعدادات الخاصة بالعملة من ملف العقل إن وجدت
    prof = brain.get("asset_profiles", {}).get(symbol, {})
    r_min = prof.get("rsi_min", cfg.get("rsi_min", 32))
    r_max = prof.get("rsi_max", cfg.get("rsi_max", 58))

    # فحص شرط الدخول الأساسي قبل جمع النقاط
    if not (price > cur_sma20 and price >= prev and r_min <= cur_rsi <= r_max):
        return 0, "scalp", 0.0, 1.2, -1.2, ""

    # --- المساعد 1: الكشاف (25 نقطة - 5 فحوصات) ---
    s1 = 5  # 1. السوق مفتوح ومتاح
    royal_syms = [r["symbol"] for r in favs["royal"]]
    test_syms = [r["symbol"] for r in favs["testing"]]
    if symbol in royal_syms:
        s1 += 6  # 2. عملة نخبة ملكية
    elif symbol in test_syms or symbol in cfg.get("elite_assets", []):
        s1 += 4
    if cur_vol >= avg_vol * 0.9:
        s1 += 5  # 3. سيولة نشطة
    if 0.4 <= cur_atr <= 2.5:
        s1 += 5  # 4. تذبذب صحي غير ميت
    if price >= float(o.iloc[-1]):
        s1 += 4  # 5. شمعة خضراء إيجابية

    # --- المساعد 2: المحلل الفني (25 نقطة - 5 فحوصات) ---
    s2 = 6  # 6. فوق متوسط 20
    if 36 <= cur_rsi <= 52:
        s2 += 6  # 7. RSI في المنطقة الذهبية الآمنة
    else:
        s2 += 3
    if price > cur_sma50:
        s2 += 5  # 8. مسار صاعد عام (فوق متوسط 50)
    recent_high = float(h.iloc[-20:].max())
    if price < recent_high * 0.995:
        s2 += 4  # 9. السعر ليس متضخماً في قمة لحظية
    if btc_chg > -1.2:
        s2 += 4  # 10. البيتكوين مستقر ولا يضغط السوق

    # --- المساعد 3: راصد الأخبار والذاكرة (25 نقطة - 5 فحوصات) ---
    if news_info["danger"]:
        return 0, "scalp", 0.0, 1.2, -1.2, "تم الإلغاء: راصد الأخبار أعلن حالة خطر"
    s3 = int(min(10, news_info["score"] * 0.4))  # 11 & 12. نقاط الأخبار ومؤشر الخوف
    trap_key = f"{symbol}_rsi_{int(cur_rsi // 5 * 5)}"
    if trap_key in brain.get("trap_patterns", []):
        db.log_thought("راصد الذاكرة", f"تجنب فخ تاريخي مرصود في {symbol} عند RSI {cur_rsi:.0f} 🛡️", "warn")
        return 0, "scalp", 0.0, 1.2, -1.2, ""
    s3 += 6  # 13. خالٍ من فخاخ الماضي
    if not db.on_cooldown(symbol, cfg.get("cooldown_min", 45)):
        s3 += 5  # 14. خارج فترة التبريد
    s3 += 4  # 15. سجل يومي نظيف

    # --- المساعد 4: المدقق المالي وإدارة المخاطر (25 نقطة - 5 فحوصات) ---
    # تحديد وقف الخسارة والهدف ديناميكياً حسب سرعة العملة (ATR)
    sl_pct = round(-max(0.8, min(1.5, cur_atr * 1.1)), 2)
    tp_pct = round(max(1.0, min(2.4, cur_atr * 1.6)), 2)
    s4 = 15  # 16-19. اجتياز معادلة العائد للمخاطرة وتغطية الرسوم

    prelim_score = s1 + s2 + s3 + s4
    total_score = min(99, prelim_score + (6 if price > cur_sma50 and cur_vol > avg_vol else 2))

    # فحص وضع المراقب والقناص (وقت الخطر لا يدخل إلا فوق 92 نقطة)
    if cfg.get("observer_mode") and total_score < 92:
        db.log_thought("المدقق", f"وضع المراقب نشط: {symbol} جابت {total_score}/100 (المطلوب 92+ للدخول)", "info")
        return 0, "scalp", 0.0, tp_pct, sl_pct, ""

    # اختيار الجيب المناسب والمبلغ حسب القوة
    pockets = summary["pockets"]
    chosen_pocket = None
    invest_size = 5.0

    if total_score >= 90 and not pockets["reserve"]["paused"] and pockets["reserve"]["cash"] >= 5.0:
        chosen_pocket = "reserve"
        invest_size = min(10.0, pockets["reserve"]["cash"])
    elif price > cur_sma50 and total_score >= 82 and not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 5.0:
        chosen_pocket = "swing"
        invest_size = min(8.0 if total_score >= 86 else 6.0, pockets["swing"]["cash"])
    elif not pockets["scalp"]["paused"] and pockets["scalp"]["cash"] >= 5.0:
        chosen_pocket = "scalp"
        invest_size = min(5.0, pockets["scalp"]["cash"])
    elif not pockets["swing"]["paused"] and pockets["swing"]["cash"] >= 5.0:
        chosen_pocket = "swing"
        invest_size = min(5.0, pockets["swing"]["cash"])

    if not chosen_pocket or total_score < 76:
        return 0, "scalp", 0.0, tp_pct, sl_pct, ""

    tier_badge = "👑 نخبة" if symbol in royal_syms else ("⏳ اختبار" if symbol in test_syms else "🔥 نشط")
    reason = f"الدرجة {total_score}/100 ({tier_badge}) | RSI {cur_rsi:.0f} | هدف +{tp_pct}% ووقف {sl_pct}%"
    return total_score, chosen_pocket, round(invest_size, 2), tp_pct, sl_pct, reason

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
    """المشرف الذكي وغرفة الطوارئ: يدير الحظر، فحص الجيوب، ووضع المراقب."""
    cfg, t = db.get_ai_config(), db.now()
    # ضمان وجود المفتاح القديم لمنع أي تعارض
    cfg.setdefault("trade_size", 5.0)
    cfg["banned"] = {s: u for s, u in cfg["banned"].items() if u > db.fmt(t)}

    news_info = check_news_and_mood()
    cfg["market_mood"] = news_info["mood"]

    recent = db.run("SELECT id, symbol, status, pocket, pnl_sar, exit_time FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 80")
    by = {}
    for r in recent:
        if r["id"] > cfg["ban_ref"].get(r["symbol"], 0):
            by.setdefault(r["symbol"], []).append(r)

    # حظر العملة 24 ساعة إذا خسرت مرتين متتاليتين
    for s, rows in by.items():
        if s not in cfg["banned"] and [r["status"] for r in rows[:2]].count("LOST") == 2:
            cfg["banned"][s] = db.fmt(t + timedelta(hours=24))
            cfg["ban_ref"][s] = rows[0]["id"]
            db.log_thought("غرفة الطوارئ", f"حظر {s} لمدة 24 ساعة بعد خسارتين متتاليتين 🛑", "warn")

    # فحص خسائر اليوم لتفعيل وضع المراقب والقناص بدل الإيقاف التام
    today_str = t.strftime("%Y-%m-%d")
    today_pnl = sum(float(r.get("pnl_sar") or 0) for r in recent if (r.get("exit_time") or "").startswith(today_str))
    if today_pnl <= -3.0 or news_info["danger"]:
        if not cfg.get("observer_mode"):
            cfg["observer_mode"] = True
            db.log_thought("غرفة الطوارئ", "تفعيل (وضع المراقب والقناص 🎯): يدرس السوق ويدخل فقط الفرص النادرة فوق 92/100", "warn")
    else:
        cfg["observer_mode"] = False

    summ = db.get_summary()
    st = summ["stats"]
    wr = f"{st['win_rate']}%" if st["n"] else "—"
    brain = db.get_brain()
    scen = max(cfg.get("scenarios_tested", 0), brain.get("total_runs", 0))
    cfg["scenarios_tested"] = scen
    cfg["daily_score"] = min(100, max(70, int(88 + (st["pnl"] * 2))))

    mode_txt = "وضع المراقب والقناص نشط 🎯" if cfg.get("observer_mode") else "الجيوب الثلاثة والمساعدون الـ 4 نشطون ✅"
    cfg["ai_report"] = (
        f"{mode_txt} | المزاج: {news_info['mood']} | "
        f"الحية: {st['n']} (نجاح {wr}) | خزنة السحب: {summ['personal_vault']:.2f} ر.س"
    )
    db.save_ai_config(cfg)
    return cfg, news_info

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        cfg, news_info = supervisor()
        # التركيز في التداول الفعلي حالياً على العملات الرقمية (10 عملات)
        crypto_symbols = [s for s in WATCHLIST if s.endswith("-USD")]
        data = fetch(crypto_symbols, "5d", "15m")
        prices = {s: float(d["Close"].iloc[-1]) for s, d in data.items() if is_fresh(d)}
        db.update_open_trades(prices)

        if cfg.get("paused"):
            return

        # فحص حركة البيتكوين في آخر ساعة كقائد للسوق
        btc_chg = 0.0
        if "BTC-USD" in data and len(data["BTC-USD"]) >= 5:
            b_close = data["BTC-USD"]["Close"]
            btc_chg = ((float(b_close.iloc[-1]) - float(b_close.iloc[-5])) / float(b_close.iloc[-5])) * 100
            if btc_chg <= -2.5:
                cfg["observer_mode"] = True
                db.save_ai_config(cfg)
                db.log_thought("غرفة الطوارئ", f"هبوط حاد في البيتكوين ({btc_chg:.1f}%) — التحويل لوضع المراقب الحذر 🛡️", "warn")

        summ = db.get_summary()
        open_syms = db.open_symbols()
        favs = db.get_favorites_grouped()
        brain = db.get_brain()

        # ترتيب الفحص: النخبة الملكية أولاً، ثم تحت الاختبار، ثم البقية
        royal_set = {r["symbol"] for r in favs["royal"]}
        test_set = {r["symbol"] for r in favs["testing"]}
        sorted_symbols = sorted(
            data.keys(),
            key=lambda x: (0 if x in royal_set else (1 if x in test_set else 2))
        )

        db.log_thought("الكشاف", f"مسح {len(sorted_symbols)} عملة رقمية | السيولة المتاحة: {summ['cash']:.1f} ر.س", "info")

        for s in sorted_symbols:
            if s not in prices or s in open_syms or s in cfg["banned"]:
                continue
            if summ["cash"] < 5.0 or len(open_syms) >= cfg.get("max_open", 6):
                break
            d = data[s]
            c = d["Close"].iloc[:-1]
            if _last_bar.get(s) == c.index[-1]:
                continue
            _last_bar[s] = c.index[-1]

            score, pocket, size, tp_pct, sl_pct, reason = evaluate_20_checks(
                s, d, btc_chg, news_info, cfg, brain, favs, summ
            )
            if score >= 76 and size >= 5.0:
                db.log_thought("المدقق", f"اعتماد {s} بدرجة {score}/100 في جيب ({pocket}) بمبلغ {size} ر.س ✅", "success")
                db.log_trade(s, WATCHLIST[s], prices[s], reason, invest_amount=size,
                             pocket=pocket, score=score, tp_pct=tp_pct, sl_pct=sl_pct)
                open_syms.append(s)
                summ = db.get_summary()
    finally:
        _scan_lock.release()

def run_backtest():
    """دوري الاستراتيجيات: يفحص العملات والأسهم معاً لبناء الخبرة وتحديث المفضلة."""
    cfg = db.get_ai_config()
    db.log_thought("المعمل", "بدء دوري الاستراتيجيات وفحص العملات والأسهم... 🔬", "info")
    db.run("DELETE FROM trades WHERE is_historical=1")
    data = fetch(list(WATCHLIST.keys()), "6mo", "1h")
    hold = int(cfg.get("max_hold_h", 24))

    candidates = [
        {"rsi_min": 30, "rsi_max": 54, "tp_pct": 1.3, "sl_pct": -1.1},
        {"rsi_min": 32, "rsi_max": 58, "tp_pct": 1.5, "sl_pct": -1.2},
        {"rsi_min": 28, "rsi_max": 52, "tp_pct": 1.2, "sl_pct": -1.0},
    ]

    best_cfg = candidates[0]
    best_total_pnl = -9999.0
    total_scenarios = 0

    for cand in candidates:
        cand_pnl = 0.0
        for s, d in data.items():
            total_scenarios += len(d)
            sma20, sma50, rsi, atr_pct, _ = indicators(d)
            o, h, l, c = (d[k].values for k in ("Open", "High", "Low", "Close"))
            i = 52
            while i < len(d) - 2:
                if not (c[i] > sma20.iloc[i] and c[i] >= c[i - 1] and cand["rsi_min"] <= rsi.iloc[i] <= cand["rsi_max"]):
                    i += 1
                    continue
                entry = o[i + 1]
                tp, sl = entry * (1 + cand["tp_pct"] / 100), entry * (1 + cand["sl_pct"] / 100)
                ex = c[min(i + hold, len(d) - 1)]
                for j in range(i + 1, min(i + 1 + hold, len(d))):
                    if l[j] <= sl:
                        ex = sl; break
                    if h[j] >= tp:
                        ex = tp; break
                cand_pnl += db.calc_pnl(entry, ex, 6.0)
                i = j + 1
        if cand_pnl > best_total_pnl:
            best_total_pnl = cand_pnl
            best_cfg = cand

    cfg.update(best_cfg)
    cfg["scenarios_tested"] = cfg.get("scenarios_tested", 0) + total_scenarios

    asset_scores = {}
    for s, label in WATCHLIST.items():
        d = data.get(s)
        if d is None or len(d) < 60:
            continue
        try:
            sma20, sma50, rsi, atr_pct, _ = indicators(d)
            o, h, l, c = (d[k].values for k in ("Open", "High", "Low", "Close"))
            idx, i = d.index, 52
            asset_pnl = 0.0
            while i < len(d) - 2:
                if not (c[i] > sma20.iloc[i] and c[i] >= c[i - 1] and cfg["rsi_min"] <= rsi.iloc[i] <= cfg["rsi_max"]):
                    i += 1
                    continue
                entry = o[i + 1]
                pocket = "swing" if c[i] > sma50.iloc[i] else "scalp"
                size = 8.0 if pocket == "swing" else 5.0
                tp, sl = entry * (1 + cfg["tp_pct"] / 100), entry * (1 + cfg["sl_pct"] / 100)
                ex, why = c[min(i + hold, len(d) - 1)], "خروج بالوقت"
                for j in range(i + 1, min(i + 1 + hold, len(d))):
                    if l[j] <= sl:
                        ex, why = sl, "وقف الخسارة"; break
                    if h[j] >= tp:
                        ex, why = tp, "هدف القناص"; break
                pnl = db.calc_pnl(entry, ex, size)
                asset_pnl += pnl
                db.log_trade(s, label, entry, f"مختبر ({pocket}) | RSI {rsi.iloc[i]:.0f}", 1,
                             idx[i + 1].strftime("%Y-%m-%d %H:%M"), idx[j].strftime("%Y-%m-%d %H:%M"),
                             ex, "WON" if pnl > 0 else "LOST", pnl,
                             f"{why} بعد {j - i} ساعة", size, pocket=pocket, score=85)
                i = j + 1
            asset_scores[s] = asset_pnl
        except Exception as e:
            print(f"Backtest error {s}: {e}")

    elites = [s for s, p in sorted(asset_scores.items(), key=lambda x: x[1], reverse=True) if p > 0]
    cfg["elite_assets"] = elites[:6] if elites else list(WATCHLIST.keys())[:5]
    for s in cfg["elite_assets"][:3]:
        db.update_favorite(s, picked=True, won=True)
    db.save_ai_config(cfg)
    db.log_thought("المعمل", f"اكتمل فحص {total_scenarios:,} شمعة وتحديث النخبة الملكية بنجاح 🏆", "success")
    supervisor()
