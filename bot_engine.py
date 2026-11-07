import yfinance as yf
import database as db

WATCHLIST = {
    # العملات الرقمية (شغالة 24/7 في الويكند)
    "BTC-USD": "بيتكوين (كريبتو)",
    "ETH-USD": "إيثيريوم (كريبتو)",
    "SOL-USD": "سولانا (كريبتو)",
    "BNB-USD": "بينانس (كريبتو)",
    "XRP-USD": "ريبل (كريبتو)",
    "DOGE-USD": "دوج كوين (كريبتو)",
    "ADA-USD": "كاردانو (كريبتو)",
    "AVAX-USD": "أفالانش (كريبتو)",
    
    # السوق السعودي (يفتح غداً الأحد 10 صباحاً)
    "4300.SR": "دار الأركان (تاسي)",
    "2222.SR": "أرامكو (تاسي)",
    "2010.SR": "سابك (تاسي)",
    "4110.SR": "باتك (تاسي)",

    # السوق الأمريكي (يفتح الإثنين 5:30 مساءً)
    "PLTR": "بالنتير (أمريكي)",
    "SOFI": "سوفاي (أمريكي)",
    "RIVN": "ريفيان (أمريكي)"
}

def ai_supervisor_optimize():
    trades = db.get_all_trades()
    cfg = db.get_ai_config()
    
    closed = [t for t in trades if t['status'] in ('WON', 'LOST') and t.get('is_historical', 0) == 0]
    won = [t for t in closed if t['status'] == 'WON']
    lost = [t for t in closed if t['status'] == 'LOST']
    win_rate = (len(won) / len(closed)) * 100 if closed else 100.0

    loss_counts = {}
    for t in lost:
        sym = t['symbol']
        loss_counts[sym] = loss_counts.get(sym, 0) + 1
    
    banned = [sym for sym, cnt in loss_counts.items() if cnt >= 3 and sym not in [w['symbol'] for w in won]]
    cfg['banned_symbols'] = banned
    cfg['rsi_min'] = 30
    cfg['rsi_max'] = 58
    cfg['tp_pct'] = 1.2
    cfg['sl_pct'] = -1.2
    cfg['ai_report'] = (
        f"⚡ المشرف الذكي نشط: يراقب 15 أصلاً بنظام الدخول المتدرج (6 ر.س للصفقة). "
        f"نطاق الصيد المرن (RSI بين 30 و 58) لتفادي القمم مع اقتناص الفرص الحية."
    )
    db.save_ai_config(cfg)
    return cfg

def analyze_and_trade():
    cfg = ai_supervisor_optimize()
    current_prices = {}
    trades = db.get_all_trades()
    open_trades = [t for t in trades if t['status'] == 'OPEN' and t.get('is_historical', 0) == 0]
    open_symbols = [t['symbol'] for t in open_trades]
    currently_invested = sum([float(t.get('invested_sar') or 6.0) for t in open_trades])

    for symbol, asset_type in WATCHLIST.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="15m")
            if df.empty or len(df) < 30:
                continue

            close = df['Close']
            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            current_prices[symbol] = curr_price

            # التوقف إذا وصلنا سقف المحفظة (54 ريال مستثمرة) أو الأصل محظور
            if currently_invested >= 54.0 or symbol in cfg.get('banned_symbols', []):
                continue

            sma20 = float(close.rolling(20).mean().iloc[-1])
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rs = gain / loss if loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            if symbol not in open_symbols:
                # المسار 1: صعود زخم آمن (السعر فوق المتوسط + شمعة خضراء + RSI غير متضخم تحت 58)
                if curr_price > sma20 and curr_price >= prev_price and (32 <= rsi <= 58):
                    reason = f"زخم صاعد مرن (6 ر.س): فوق متوسط 20 + RSI آمن ({round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0, invest_amount=6.0)
                    open_symbols.append(symbol)
                    currently_invested += 6.0

                # المسار 2: اقتناص ارتداد من هبوط (RSI منخفض تحت 38 مع بداية شمعة خضراء)
                elif rsi < 38 and curr_price > prev_price:
                    reason = f"ارتداد مبكر (6 ر.س): بداية صعود من منطقة خصم (RSI {round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0, invest_amount=6.0)
                    open_symbols.append(symbol)
                    currently_invested += 6.0
        except Exception as e:
            print(f"Scan error {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices

def run_historical_backtest():
    db.clear_old_backtest()
    sample_assets = {
        "BTC-USD": "بيتكوين (كريبتو)",
        "SOL-USD": "سولانا (كريبتو)",
        "XRP-USD": "ريبل (كريبتو)",
        "DOGE-USD": "دوج كوين (كريبتو)",
        "PLTR": "بالنتير (أمريكي)",
        "4300.SR": "دار الأركان (تاسي)"
    }

    for symbol, asset_type in sample_assets.items():
        try:
            df = yf.Ticker(symbol).history(period="1mo", interval="1h")
            if df.empty or len(df) < 35:
                continue

            close = df['Close']
            sma20 = close.rolling(20).mean()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            count = 0
            for i in range(25, len(df)-8, 12):
                if count >= 2:
                    break
                p_entry = float(close.iloc[i])
                p_prev = float(close.iloc[i-1])
                r_val = float(rsi.iloc[i])
                s20_val = float(sma20.iloc[i])
                t_entry = df.index[i].strftime("%Y-%m-%d %H:%M")

                if p_entry > p_prev and ((p_entry > s20_val and 32 <= r_val <= 56) or r_val < 35):
                    future = close.iloc[i+1 : i+8]
                    gain_pct = ((float(future.max()) - p_entry) / p_entry) * 100
                    loss_pct = ((float(future.min()) - p_entry) / p_entry) * 100
                    qty = round((6.0 / 3.75) / p_entry, 4)

                    if gain_pct >= 1.2:
                        pnl = round(((p_entry * 1.012) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+3].strftime("%Y-%m-%d %H:%M")
                        lesson = f"دخول متدرج ناجح (6 ر.س): اقتناص عند RSI ({round(r_val,1)}) حقق +1.2%."
                        db.log_trade(symbol, asset_type, p_entry, f"فحص ذكي مرن (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*1.012,
                                     status="WON", pnl_sar=pnl, lesson=lesson, invest_amount=6.0)
                        count += 1
                    elif loss_pct <= -1.2:
                        pnl = round(((p_entry * 0.988) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+2].strftime("%Y-%m-%d %H:%M")
                        lesson = f"خسارة ميكرو محمية: تراجع السعر وتفعل الوقف بخسارة ({pnl} ر.س) فقط."
                        db.log_trade(symbol, asset_type, p_entry, f"اختبار زخم (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*0.988,
                                     status="LOST", pnl_sar=pnl, lesson=lesson, invest_amount=6.0)
                        count += 1
        except Exception as e:
            print(f"Backtest error {symbol}: {e}")

    db.backup_db_to_github()
