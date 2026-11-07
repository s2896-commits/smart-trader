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

def analyze_and_trade():
    cfg = db.get_ai_config()
    current_prices = {}
    trades = db.get_all_trades()
    open_trades = [t for t in trades if t['status'] == 'OPEN' and t.get('is_historical', 0) == 0]
    open_symbols = [t['symbol'] for t in open_trades]
    
    # حساب إجمالي المبالغ المستثمرة فعلياً لضمان عدم تجاوز الـ 60 ريال
    currently_invested = sum([t.get('invested_sar', 6.0) for t in open_trades])

    for symbol, asset_type in WATCHLIST.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="15m")
            if df.empty or len(df) < 35:
                continue

            close = df['Close']
            vol = df['Volume']
            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            current_prices[symbol] = curr_price

            if currently_invested >= 54.0 or symbol in cfg.get('banned_symbols', []):
                continue

            sma20 = float(close.rolling(20).mean().iloc[-1])
            sma50 = float(close.rolling(35).mean().iloc[-1])
            avg_vol = float(vol.rolling(20).mean().iloc[-1])
            curr_vol = float(vol.iloc[-1])

            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rs = gain / loss if loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            # الفحص الاستباقي:
            # 1. الاتجاه العام صاعد (السعر فوق متوسط 50)
            # 2. RSI في النطاق الصحي (32 إلى 49)
            # 3. شمعة خضراء وسيولة مقبولة
            is_healthy_trend = curr_price > sma50 and curr_price > sma20
            is_volume_ok = curr_vol >= (avg_vol * 0.7)
            
            if symbol not in open_symbols:
                if is_healthy_trend and is_volume_ok and (32 <= rsi <= 49) and (curr_price > prev_price):
                    reason = f"دخول مدرج (6 ر.س): اتجاه صاعد + RSI آمن ({round(rsi, 1)}) + سيولة كافية"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0, invest_amount=6.0)
                    open_symbols.append(symbol)
                    currently_invested += 6.0
                elif rsi < 28 and curr_price > prev_price:
                    reason = f"قاع صريح (6 ر.س): ارتداد من تشبع بيعي حاد (RSI {round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0, invest_amount=6.0)
                    open_symbols.append(symbol)
                    currently_invested += 6.0
        except Exception as e:
            print(f"Scan error {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices

def run_historical_backtest():
    db.clear_old_backtest()
    cfg = db.get_ai_config()

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
            sma50 = close.rolling(35).mean()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            count = 0
            for i in range(35, len(df)-8, 14):
                if count >= 2:
                    break
                p_entry = float(close.iloc[i])
                p_prev = float(close.iloc[i-1])
                r_val = float(rsi.iloc[i])
                s50_val = float(sma50.iloc[i])
                t_entry = df.index[i].strftime("%Y-%m-%d %H:%M")

                # شرط الفحص الاستباقي الصارم
                if p_entry > p_prev and p_entry > s50_val and (30 <= r_val <= 48):
                    future = close.iloc[i+1 : i+8]
                    gain_pct = ((float(future.max()) - p_entry) / p_entry) * 100
                    loss_pct = ((float(future.min()) - p_entry) / p_entry) * 100
                    qty = round((6.0 / 3.75) / p_entry, 4)

                    if gain_pct >= 1.3:
                        pnl = round(((p_entry * 1.013) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+3].strftime("%Y-%m-%d %H:%M")
                        lesson = f"نجاح استباقي: الدخول بحجم ميكرو (6 ر.س) مع مسار صاعد أصاب الهدف."
                        db.log_trade(symbol, asset_type, p_entry, f"فحص استباقي آمن (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*1.013,
                                     status="WON", pnl_sar=pnl, lesson=lesson, invest_amount=6.0)
                        count += 1
                    elif loss_pct <= -1.2:
                        pnl = round(((p_entry * 0.988) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+2].strftime("%Y-%m-%d %H:%M")
                        lesson = f"حماية ميكرو: تراجع طفيف والخسارة محدودة بـ ({pnl} ر.س) فقط."
                        db.log_trade(symbol, asset_type, p_entry, f"فحص استباقي (تراجع طفيف)",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*0.988,
                                     status="LOST", pnl_sar=pnl, lesson=lesson, invest_amount=6.0)
                        count += 1
        except Exception as e:
            print(f"Backtest error {symbol}: {e}")

    db.backup_db_to_github()
