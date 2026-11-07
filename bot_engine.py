import yfinance as yf
import database as db

WATCHLIST = {
    "4300.SR": "دار الأركان",
    "2222.SR": "أرامكو السعودية",
    "2010.SR": "سابك",
    "PLTR": "بالنتير (PLTR)",
    "SOFI": "سوفاي (SOFI)",
    "ADA-USD": "كاردانو (ADA)",
    "XRP-USD": "ريبل (XRP)",
    "DOGE-USD": "دوج كوين (DOGE)",
    "SOL-USD": "سولانا (SOL)"
}

def analyze_and_trade():
    current_prices = {}
    trades = db.get_all_trades()
    open_symbols = [t['symbol'] for t in trades if t['status'] == 'OPEN']

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
                    reason = f"دخول مباشر: فوق متوسط 20 + RSI ممتاز ({round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason)
                elif rsi < 32 and curr_price > float(close.iloc[-2]):
                    reason = f"ارتداد قاع: تشبع بيعي ({round(rsi, 1)}) مع بداية صعود"
                    db.log_trade(symbol, asset_type, curr_price, reason)
        except Exception as e:
            print(f"Scan error {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices

def run_historical_backtest():
    for symbol, asset_type in WATCHLIST.items():
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

            for i in range(25, len(df)-5, 12):
                p_entry = float(close.iloc[i])
                r_val = float(rsi.iloc[i])
                s_val = float(sma20.iloc[i])
                t_entry = df.index[i].strftime("%Y-%m-%d %H:%M")

                if p_entry > s_val and 40 <= r_val <= 62:
                    future_prices = close.iloc[i+1 : i+6]
                    max_p = float(future_prices.max())
                    min_p = float(future_prices.min())
                    
                    gain_pct = ((max_p - p_entry) / p_entry) * 100
                    loss_pct = ((min_p - p_entry) / p_entry) * 100

                    invest_usd = 20.0 / 3.75
                    qty = round(invest_usd / p_entry, 4)

                    if gain_pct >= 1.5:
                        pnl = round(((p_entry * 1.015) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+3].strftime("%Y-%m-%d %H:%M")
                        lesson = f"توقيت مثالي بالماضي: الشراء عند RSI={round(r_val,1)} حقق الهدف (+1.5%)."
                        db.log_trade(symbol, asset_type, p_entry, f"دراسة ماضية: زخم RSI {round(r_val,1)}",
                                     is_historical=True, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*1.015,
                                     status="WON", pnl_sar=pnl, lesson=lesson)
                        break
                    elif loss_pct <= -1.0:
                        pnl = round(((p_entry * 0.99) - p_entry) * qty * 3.75, 2)
                        t_exit = df.index[i+2].strftime("%Y-%m-%d %H:%M")
                        lesson = "درس مستفاد: تراجع السعر -1% وحمى الوقف بقية الـ 60 ريال."
                        db.log_trade(symbol, asset_type, p_entry, "دراسة ماضية: كسر متوسط 20 لم يكتمل",
                                     is_historical=True, entry_time=t_entry, exit_time=t_exit, exit_price=p_entry*0.99,
                                     status="LOST", pnl_sar=pnl, lesson=lesson)
                        break
        except Exception as e:
            print(f"Backtest error {symbol}: {e}")
    db.backup_db_to_github()
