import threading
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
import database as db

WATCHLIST = {
    "BTC-USD": "بيتكوين (كريبتو)", "ETH-USD": "إيثيريوم (كريبتو)",
    "SOL-USD": "سولانا (كريبتو)", "BNB-USD": "بينانس (كريبتو)",
    "XRP-USD": "ريبل (كريبتو)", "DOGE-USD": "دوج كوين (كريبتو)",
    "ADA-USD": "كاردانو (كريبتو)", "AVAX-USD": "أفالانش (كريبتو)",
    "4300.SR": "دار الأركان (تاسي)", "2222.SR": "أرامكو (تاسي)",
    "2010.SR": "سابك (تاسي)", "4110.SR": "باتك (تاسي)",
    "PLTR": "بالنتير (أمريكي)", "SOFI": "سوفاي (أمريكي)", "RIVN": "ريفيان (أمريكي)",
}
TZ_SA, TZ_US = ZoneInfo("Asia/Riyadh"), ZoneInfo("America/New_York")
_scan_lock = threading.Lock()
_last_bar = {}

def asset_class(s):
    return "crypto" if s.endswith("-USD") else "tasi" if s.endswith(".SR") else "us"

def market_status():
    sa, us = datetime.now(TZ_SA), datetime.now(TZ_US)
    return {"crypto": True,
            "tasi": sa.weekday() in (6, 0, 1, 2, 3) and dtime(10, 0) <= sa.time() < dtime(15, 0),
            "us": us.weekday() < 5 and dtime(9, 30) <= us.time() < dtime(16, 0)}

def indicators(close):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, 1e-9))
    return close.rolling(20).mean(), rsi

def is_entry(price, prev, sma, rsi, cfg):
    return bool(price > sma and price >= prev and cfg["rsi_min"] <= rsi <= cfg["rsi_max"])

def fetch(period, interval):
    df = yf.download(list(WATCHLIST), period=period, interval=interval,
                     group_by="ticker", progress=False, threads=True,
                     auto_adjust=True, timeout=25)
    out = {}
    for s in WATCHLIST:
        try:
            d = df[s].dropna(subset=["Close"])
            if len(d) >= 40:
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
    recent = db.run("SELECT id, symbol, status FROM trades WHERE is_historical=0 AND status!='OPEN' ORDER BY id DESC LIMIT 80")
    by = {}
    for r in recent:
        if r["id"] > cfg["ban_ref"].get(r["symbol"], 0):
            by.setdefault(r["symbol"], []).append(r)
    for s, rows in by.items():
        if s not in cfg["banned"] and [r["status"] for r in rows[:3]].count("LOST") == 3:
            cfg["banned"][s] = db.fmt(t + timedelta(hours=24))
            cfg["ban_ref"][s] = rows[0]["id"]
    st = db.get_summary()["stats"]
    wr = f"{st['win_rate']}%" if st["n"] else "—"
    note = "العيّنة صغيرة: لا تعديل للمعايير قبل 30 صفقة مغلقة." if st["n"] < 30 else "العيّنة كافية للمراجعة."
    ban = f" | محظور 24س: {', '.join(cfg['banned'])}" if cfg["banned"] else ""
    cfg["ai_report"] = f"{st['n']} صفقة مغلقة | نجاح {wr}{ban}. {note}"
    db.save_ai_config(cfg)
    return cfg

def analyze_and_trade():
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        cfg = supervisor()
        data = fetch("5d", "15m")
        prices = {s: float(d["Close"].iloc[-1]) for s, d in data.items() if is_fresh(d)}
        db.update_open_trades(prices)
        if cfg["paused"]:
            return
        summ = db.get_summary()
        cash, size = summ["cash"], cfg["trade_size"]
        open_syms = db.open_symbols()
        counts = {}
        for s in open_syms:
            counts[asset_class(s)] = counts.get(asset_class(s), 0) + 1
        for s, d in data.items():
            if s not in prices or s in open_syms or s in cfg["banned"]:
                continue
            if cash < size or len(open_syms) >= cfg["max_open"]:
                break
            if counts.get(asset_class(s), 0) >= cfg["max_per_class"] or db.on_cooldown(s, cfg["cooldown_min"]):
                continue
            c = d["Close"].iloc[:-1]
            if _last_bar.get(s) == c.index[-1]:
                continue
            _last_bar[s] = c.index[-1]
            sma, rsi = indicators(c)
            if is_entry(c.iloc[-1], c.iloc[-2], sma.iloc[-1], rsi.iloc[-1], cfg):
                db.log_trade(s, WATCHLIST[s], prices[s],
                             f"زخم صاعد: فوق SMA20 + RSI {rsi.iloc[-1]:.0f}", invest_amount=size)
                open_syms.append(s)
                counts[asset_class(s)] = counts.get(asset_class(s), 0) + 1
                cash -= size
    finally:
        _scan_lock.release()

def run_backtest():
    cfg = db.get_ai_config()
    db.run("DELETE FROM trades WHERE is_historical=1")
    data = fetch("6mo", "1h")
    hold = int(cfg["max_hold_h"])
    for s, label in WATCHLIST.items():
        d = data.get(s)
        if d is None or len(d) < 60:
            continue
        try:
            sma, rsi = indicators(d["Close"])
            o, h, l, c = (d[k].values for k in ("Open", "High", "Low", "Close"))
            idx, i = d.index, 25
            while i < len(d) - 2:
                if not is_entry(c[i], c[i - 1], sma.iloc[i], rsi.iloc[i], cfg):
                    i += 1
                    continue
                entry = o[i + 1]
                tp, sl = entry * (1 + cfg["tp_pct"] / 100), entry * (1 + cfg["sl_pct"] / 100)
                ex, why = c[min(i + hold, len(d) - 1)], "خروج بالوقت"
                for j in range(i + 1, min(i + 1 + hold, len(d))):
                    if l[j] <= sl:
                        ex, why = sl, "وقف الخسارة"
                        break
                    if h[j] >= tp:
                        ex, why = tp, "هدف الربح"
                        break
                pnl = db.calc_pnl(entry, ex, cfg["trade_size"])
                db.log_trade(s, label, entry, f"زخم (RSI {rsi.iloc[i]:.0f})", 1,
                             idx[i + 1].strftime("%Y-%m-%d %H:%M"), idx[j].strftime("%Y-%m-%d %H:%M"),
                             ex, "WON" if pnl > 0 else "LOST", pnl,
                             f"{why} بعد {j - i} ساعة", cfg["trade_size"])
                i = j + 1
        except Exception as e:
            print(f"Backtest error {s}: {e}")
