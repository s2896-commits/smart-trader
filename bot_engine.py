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
    current_prices = {}
    trades = db.get_all_trades()
    open_symbols = [t['symbol'] for t in trades if t['status'] == 'OPEN' and t.get('is_historical', 0) == 0]

    for symbol, asset_type in WATCHLIST.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="15m")
            if df.empty or len(df) < 20:
                continue

            close = df['Close']
            curr_price = float(close.iloc[-1])
            current_prices[symbol] = curr_price

            sma20 = float(close.rolling(20).mean().iloc[-1])
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rs = gain / loss if loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            if symbol not in open_symbols and len(open_symbols) < 3:
                if curr_price > sma20 and 42 <= rsi <= 65:
                    reason = f"استراتيجية الزخم: السعر فوق متوسط 20 ومؤشر RSI متزن ({round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0)
                elif rsi < 32 and curr_price > float(close.iloc[-2]):
                    reason = f"استراتيجية القاع: ارتداد من تشبع بيعي عند RSI ({round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason, is_historical=0)
        except Exception as e:
            print(f"Scan error {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices

def run_historical_backtest():
    db.clear_old_backtest()
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
            if df.empty or len(df) < 30:
                continue

            close = df['Close']
            sma20 = close.rolling(20).mean()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            count = 0
            for i in range(25, len(df)-6, 18):
                if count >= 2:
                    break
                p_entry = float(close.iloc[i])
                r_val = float(rsi.iloc[i])
                s_val = float(sma20.iloc[i])
                t_entry = df.index[i].strftime("%Y-%m-%d %H:%M")

                if p_entry > s_val and 42 <= r_val <= 64:
                    future = close.iloc[i+1 : i+6]
                    gain_pct = ((float(future.max()) - p_entry) / p_entry) * 100
                    loss_pct = ((float(future.min()) - p_entry) / p_entry) * 100
                    qty = round((20.0 / 3.75) / p_entry, 4)

                    if gain_pct >= 1.5:
                        pnl = round(((p_entry * 1.015) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+3].strftime("%Y-%m-%d %H:%M")
                        lesson = f"نجاح النمط: الدخول عند RSI ({round(r_val,1)}) أعطى اندفاعاً سريعاً للهدف."
                        db.log_trade(symbol, asset_type, p_entry, f"محاكاة زخم (RSI {round(r_val,1)})",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*1.015,
                                     status="WON", pnl_sar=pnl, lesson=lesson)
                        count += 1
                    elif loss_pct <= -1.0:
                        pnl = round(((p_entry * 0.99) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+2].strftime("%Y-%m-%d %H:%M")
                        lesson = f"درس تدريبي: الزخم ضعف عند RSI ({round(r_val,1)}) وتفعل الوقف بنجاح."
                        db.log_trade(symbol, asset_type, p_entry, f"محاكاة كسر غير مكتمل",
                                     is_historical=1, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*0.99,
                                     status="LOST", pnl_sar=pnl, lesson=lesson)
                        count += 1
        except Exception as e:
            print(f"Backtest error {symbol}: {e}")
    db.backup_db_to_github()
