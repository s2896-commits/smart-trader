import os, json, random, hashlib
import pandas as pd
import yfinance as yf
import database as db
import bot_engine as bot

BRAIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_brain.json")

# شبكة الإعدادات التي سيختبرها المعمل لكل عملة للوصول لأقوى ربح وأعلى نسبة نجاح
RSI_RANGES = [(28, 48), (30, 52), (32, 55), (35, 58), (38, 60)]
TP_SL_PAIRS = [
    (1.2, -0.9, 0.9, 0.35),
    (1.4, -1.0, 1.0, 0.40),
    (1.6, -1.1, 1.1, 0.45),
    (2.0, -1.2, 1.2, 0.50),
]

def simulate_asset(symbol, df, r_min, r_max, tp_pct, sl_pct, tr_trig, tr_gap, sim_capital=60.0):
    """محاكاة دقيقة مع تفعيل تتبع القمة (Trailing Stop) وحجم الصفقة المتدرج (60 إلى 600 ريال)."""
    sma20, sma50, rsi, atr_pct, vol_avg = bot.indicators(df)
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    v = df["Volume"].values if "Volume" in df else [1] * len(df)
    v_avg = vol_avg.values

    trades = []
    traps = {}
    i = 52
    hold = 24
    # نسبة حجم الصفقة من رأس المال العشوائي (60 إلى 600 ريال)
    base_size = max(5.0, round(sim_capital * 0.10, 2))

    while i < len(df) - 2:
        # شرط الدخول الأساسي + فلتر السيولة والمسار
        if not (c[i] > sma20.iloc[i] and c[i] >= c[i - 1] and r_min <= rsi.iloc[i] <= r_max and v[i] >= v_avg[i] * 0.85):
            i += 1
            continue

        entry = float(o[i + 1])
        if entry <= 0:
            i += 1
            continue

        pocket = "swing" if c[i] > sma50.iloc[i] else "scalp"
        size = round(base_size * (1.3 if pocket == "swing" else 1.0), 2)
        peak = entry
        exit_p = float(c[min(i + hold, len(df) - 1)])
        why = "خروج زمني"

        for j in range(i + 1, min(i + 1 + hold, len(df))):
            cur_h, cur_l, cur_c = float(h[j]), float(l[j]), float(c[j])
            peak = max(peak, cur_h)
            peak_pct = ((peak - entry) / entry) * 100.0
            low_pct = ((cur_l - entry) / entry) * 100.0
            high_pct = ((cur_h - entry) / entry) * 100.0
            drop_from_peak = ((peak - cur_c) / peak) * 100.0 if peak > 0 else 0.0

            # 1. فحص وقف الخسارة
            if low_pct <= sl_pct:
                exit_p = entry * (1.0 + sl_pct / 100.0)
                why = f"حماية الوقف ({sl_pct}%)"
                break
            # 2. فحص تتبع القمة الذكي (Trailing Stop)
            if peak_pct >= tr_trig and drop_from_peak >= tr_gap and ((cur_c - entry) / entry * 100.0) > 0.35:
                exit_p = cur_c
                why = f"تتبع القمة 🎯 (+{peak_pct:.1f}%)"
                break
            # 3. فحص هدف الربح
            if high_pct >= tp_pct:
                exit_p = entry * (1.0 + tp_pct / 100.0)
                why = f"هدف القناص (+{tp_pct}%)"
                break

        pnl = db.calc_pnl(entry, exit_p, 6.0)  # موحد على 6 ريال للمقارنة العادلة في المختبر
        won = pnl > 0
        rsi_bucket = int(rsi.iloc[i] // 5 * 5)
        trap_key = f"{symbol}_rsi_{rsi_bucket}"
        traps.setdefault(trap_key, {"w": 0, "l": 0})
        if won:
            traps[trap_key]["w"] += 1
        else:
            traps[trap_key]["l"] += 1

        trades.append({
            "symbol": symbol,
            "entry": entry,
            "exit": exit_p,
            "pnl": pnl,
            "won": won,
            "pocket": pocket,
            "rsi": float(rsi.iloc[i]),
            "entry_time": df.index[i + 1].strftime("%Y-%m-%d %H:%M"),
            "exit_time": df.index[j].strftime("%Y-%m-%d %H:%M"),
            "why": f"{why} بعد {j - i} ساعة",
        })
        i = j + 1

    return trades, traps

def train_all():
    print("🚀 بدء معمل التدريب المتدرج (60 إلى 600 ريال)...")
    brain = db.get_brain()
    tested_hashes = set(brain.get("tested_hashes", []))
    asset_profiles = brain.get("asset_profiles", {})
    trap_patterns = set(brain.get("trap_patterns", []))
    total_runs = int(brain.get("total_runs", 0))

    data = bot.fetch(list(bot.WATCHLIST.keys()), "6mo", "1h")
    db.run("DELETE FROM trades WHERE is_historical=1")

    all_best_trades = []
    elites_ranking = []

    for s, label in bot.WATCHLIST.items():
        df = data.get(s)
        if df is None or len(df) < 80:
            continue

        best_score = -9999.0
        best_profile = None
        best_trades = []
        best_traps = {}

        for r_min, r_max in RSI_RANGES:
            for tp_pct, sl_pct, tr_trig, tr_gap in TP_SL_PAIRS:
                # اختيار رأس مال عشوائي بين 60 و 600 ريال (قاعدة ×10)
                sim_cap = random.choice([60, 120, 250, 400, 600])
                scen_hash = hashlib.md5(f"{s}_{r_min}_{r_max}_{tp_pct}_{sl_pct}_{len(df)}".encode()).hexdigest()[:10]
                tested_hashes.add(scen_hash)
                total_runs += len(df)

                trades, traps = simulate_asset(s, df, r_min, r_max, tp_pct, sl_pct, tr_trig, tr_gap, sim_cap)
                if len(trades) < 5:
                    continue

                wins = sum(1 for t in trades if t["won"])
                wr = (wins / len(trades)) * 100.0
                tot_pnl = sum(t["pnl"] for t in trades)
                # معادلة التقييم: نفضل الربح الإيجابي ونسبة النجاح العالية
                score = (tot_pnl * 3.0) + (wr - 50.0)

                if score > best_score:
                    best_score = score
                    best_profile = {
                        "rsi_min": r_min, "rsi_max": r_max,
                        "tp_pct": tp_pct, "sl_pct": sl_pct,
                        "trail_trigger": tr_trig, "trail_gap": tr_gap,
                        "win_rate": round(wr, 1), "net_pnl": round(tot_pnl, 2),
                        "trades_count": len(trades),
                    }
                    best_trades = trades
                    best_traps = traps

        # استخراج الفخاخ المتكررة (خسارتان أو أكثر بدون ربح مقابل)
        for tk, stat in best_traps.items():
            if stat["l"] >= 3 and stat["l"] > stat["w"] * 2:
                trap_patterns.add(tk)

        # حفظ العملات الرابحة فقط في سجل المختبر والنخبة، وعزل العملات الخاسرة مثل SOFI
        if best_profile and best_profile["net_pnl"] > 0 and best_profile["win_rate"] >= 50.0:
            asset_profiles[s] = best_profile
            elites_ranking.append((s, best_profile["net_pnl"], best_profile["win_rate"]))
            all_best_trades.extend([(s, label, t) for t in best_trades])
            print(f"✅ {s}: نجاح {best_profile['win_rate']}% | صافي +{best_profile['net_pnl']} ر.س | RSI ({best_profile['rsi_min']}-{best_profile['rsi_max']})")
        else:
            # تضييق الخناق على العملة الضعيفة حتى لا تخسر المحفظة
            asset_profiles[s] = {"rsi_min": 32, "rsi_max": 45, "tp_pct": 1.2, "sl_pct": -0.9, "win_rate": 0, "net_pnl": 0}
            print(f"🛡️ عزل {s} من النخبة لضعف نتائجها التاريخية.")

    # تسجيل الصفقات الناجحة المعتمدة في جدول المختبر لعرضها في التطبيق
    for s, label, t in all_best_trades[-250:]:
        db.log_trade(
            s, label, t["entry"],
            f"مختبر ({t['pocket']}) | RSI {t['rsi']:.0f}",
            1, t["entry_time"], t["exit_time"], t["exit"],
            "WON" if t["won"] else "LOST", t["pnl"],
            t["why"], 6.0, pocket=t["pocket"], score=88
        )

    elites_ranking.sort(key=lambda x: (x[1], x[2]), reverse=True)
    top_elites = [x[0] for x in elites_ranking[:6]] or ["BTC-USD", "SOL-USD", "XRP-USD"]

    brain_data = {
        "tested_hashes": list(tested_hashes)[-2000:],
        "asset_profiles": asset_profiles,
        "trap_patterns": list(trap_patterns),
        "total_runs": total_runs,
    }
    with open(BRAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(brain_data, f, ensure_ascii=False, indent=2)

    cfg = db.get_ai_config()
    cfg["elite_assets"] = top_elites
    cfg["scenarios_tested"] = total_runs
    db.save_ai_config(cfg)

    for sym in top_elites[:3]:
        db.update_favorite(sym, picked=True, won=True)

    db.log_thought("المعمل الذكي", f"تم فرم {total_runs:,} شمعة! النخبة الآن: {', '.join(top_elites[:3])} 🏆", "success")
    db.backup_db_to_github(force=True)
    print(f"\n🎯 اكتمل التدريب! تم فحص {total_runs:,} شمعة وحفظ العقل في ai_brain.json ورفعه للسحابة.")

if __name__ == "__main__":
    train_all()
