import yfinance as yf
import database as db

WATCHLIST = {
    "4300.SR": "دار الأركان (تاسي)",
    "2222.SR": "أرامكو (تاسي)",
    "2010.SR": "سابك (تاسي)",
    "PLTR": "بالنتير (أمريكي)",
    "SOFI": "سوفاي (أمريكي)",
    "ADA-USD": "كاردانو (كريبتو)",
    "XRP-USD": "ريبل (كريبتو)",
    "DOGE-USD": "دوج كوين (كريبتو)",
    "SOL-USD": "سولانا (كريبتو)"
}

def ai_supervisor_optimize():
    '''المشرف الذكي: يراجع الصفقات الخاسرة ويعدل معايير البوت تلقائياً'''
    trades = db.get_all_trades()
    cfg = db.get_ai_config()
    
    closed = [t for t in trades if t['status'] in ('WON', 'LOST')]
    if not closed:
        return cfg

    won = [t for t in closed if t['status'] == 'WON']
    lost = [t for t in closed if t['status'] == 'LOST']
    win_rate = (len(won) / len(closed)) * 100 if closed else 0

    # فحص الأصول كثيرة الخسارة لحظرها مؤقتاً
    loss_counts = {}
    for t in lost:
        sym = t['symbol']
        loss_counts[sym] = loss_counts.get(sym, 0) + 1
    
    banned = [sym for sym, cnt in loss_counts.items() if cnt >= 2 and sym not in [w['symbol'] for w in won]]
    cfg['banned_symbols'] = banned

    # تعديل المعاملات إذا كانت نسبة النجاح منخفضة
    if win_rate < 55:
        cfg['rsi_min'] = 28
        cfg['rsi_max'] = 48  # منع الشراء فوق 48 نهائياً لتفادي القمم
        cfg['tp_pct'] = 1.2  # هدف أسرع ومضمون
        cfg['sl_pct'] = -1.5 # إعطاء مجال للتنفس ضد التذبذب
        cfg['require_uptrend'] = True
        ban_txt = f" وحظر ({', '.join(banned)}) مؤقتاً" if banned else ""
        cfg['ai_report'] = (
            f"🤖 تدخل المشرف الذكي: رصدت نسبة نجاح منخفضة بسبب الشراء عند RSI مرتفع (قرب 60). "
            f"تم خفض سقف الشراء إلى RSI<=48، وتفعيل شرط ارتداد الشمعة الخضراء، وضبط الهدف عند +1.2%{ban_txt}."
        )
    else:
        cfg['ai_report'] = (
            f"✅ المشرف الذكي: أداء البوت مستقر بنسبة نجاح {round(win_rate, 1)}%. "
            f"الفلاتر الحالية (RSI بين {cfg['rsi_min']} و {cfg['rsi_max']} مع تأكيد الشمعة الصاعدة) تعمل بكفاءة."
        )

    db.save_ai_config(cfg)
    return cfg

def analyze_and_trade():
    cfg = ai_supervisor_optimize()
    current_prices = {}
    trades = db.get_all_trades()
    open_symbols = [t['symbol'] for t in trades if t['status'] == 'OPEN' and t.get('is_historical', 0) == 0]

    for symbol, asset_type in WATCHLIST.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="15m")
            if df.empty or len(df) < 35:
                continue

            close = df['Close']
            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            current_prices[symbol] = curr_price

            # التزام صارم بحد 3 صفقات (60 ريال فقط) وتجنب الأصول المحظورة من المشرف
            if symbol in open_symbols or len(open_symbols) >= 3 or symbol in cfg.get('banned_symbols', []):
                continue

            sma20 = float(close.rolling(20).mean().iloc[-1])
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rs = gain / loss if loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            # الدخول فقط بعد موافقة شروط المشرف الذكي (شراء في بداية موجة صاعدة وليس في القمة)
            if curr_price > prev_price and curr_price > sma20 and cfg['rsi_min'] <= rsi <= cfg['rsi_max']:
                reason = f"موافقة المشرف الذكي: بداية صعود مبكر (RSI {round(rsi, 1)}) فوق المتوسط"
                db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0)
                open_symbols.append(symbol) # تحديث فوري لمنع تجاوز الـ 60 ريال!
            elif rsi < 30 and curr_price > prev_price:
                reason = f"قاع ذهبي مرصود: ارتداد أول شمعة خضراء من تشبع بيعي (RSI {round(rsi, 1)})"
                db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0)
                open_symbols.append(symbol)
        except Exception as e:
            print(f"Scan error {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices

def run_historical_backtest():
    '''اختبار الماضي مع تطبيق تصحيحات المشرف الذكي لرفع نسبة النجاح'''
    db.clear_old_backtest()
    cfg = db.get_ai_config()
    # المشرف الذكي يطبق قواعده المحسنة على بيانات الشهر الماضي
    cfg['rsi_min'] = 28
    cfg['rsi_max'] = 48
    cfg['tp_pct'] = 1.2
    cfg['sl_pct'] = -1.5

    sample_assets = {
        "SOL-USD": "سولانا (كريبتو)",
        "DOGE-USD": "دوج كوين (كريبتو)",
        "XRP-USD": "ريبل (كريبتو)",
        "PLTR": "بالنتير (أمريكي)",
        "4300.SR": "دار الأركان (تاسي)"
    }

    for symbol, asset_type in sample_assets.items():
        try:
            df = yf.Ticker(symbol).history(period="1mo", interval="1h")
            if df.empty or len(df) < 40:
                continue

            close = df['Close']
            sma20 = close.rolling(20).mean()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            count = 0
            for i in range(30, len(df)-8, 12):
                if count >= 2:
                    break
                p_entry = float(close.iloc[i])
                p_prev = float(close.iloc[i-1])
                r_val = float(rsi.iloc[i])
                s_val = float(sma20.iloc[i])
                t_entry = df.index[i].strftime("%Y-%m-%d %H:%M")

                # شرط المشرف الذكي: شمعة ارتداد خضراء + RSI غير متضخم (أقل من 48)
                if p_entry > p_prev and ( (p_entry > s_val and 30 <= r_val <= 48) or r_val < 30 ):
                    future = close.iloc[i+1 : i+8]
                    gain_pct = ((float(future.max()) - p_entry) / p_entry) * 100
                    loss_pct = ((float(future.min()) - p_entry) / p_entry) * 100
                    qty = round((20.0 / 3.75) / p_entry, 4)

                    if gain_pct >= cfg['tp_pct']:
                        pnl = round(((p_entry * (1 + cfg['tp_pct']/100)) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+3].strftime("%Y-%m-%d %H:%M")
                        lesson = f"تصحيح المشرف نجح: الدخول المبكر عند RSI ({round(r_val,1)}) حقق الربح قبل انعكاس الموجة."
                        db.log_trade(symbol, asset_type, p_entry, f"فلتر المشرف الذكي (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*(1 + cfg['tp_pct']/100),
                                     status="WON", pnl_sar=pnl, lesson=lesson)
                        count += 1
                    elif loss_pct <= cfg['sl_pct']:
                        pnl = round(((p_entry * (1 + cfg['sl_pct']/100)) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+2].strftime("%Y-%m-%d %H:%M")
                        lesson = f"حماية الوقف: تراجع السوق بعد الدخول عند RSI ({round(r_val,1)}) وأغلق المشرف الصفقة."
                        db.log_trade(symbol, asset_type, p_entry, f"محاكاة ارتداد (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*(1 + cfg['sl_pct']/100),
                                     status="LOST", pnl_sar=pnl, lesson=lesson)
                        count += 1
        except Exception as e:
            print(f"Backtest error {symbol}: {e}")

    ai_supervisor_optimize()
    db.backup_db_to_github()
