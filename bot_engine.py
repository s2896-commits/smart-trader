import yfinance as yf
import database as db

# قائمة أصول رخيصة وتناسب ميزانية حقيقية وصغيرة
WATCHLIST = {
    "PLTR": "أسهم رخيصة",     # بالنتير (سهم نمو سعره معقول)
    "SOFI": "أسهم رخيصة",     # سوفاي (بنك رقمي سعره تحت 15$)
    "RIVN": "أسهم رخيصة",     # ريفيان (سيارات كهربائية سعره تحت 15$)
    "ADA-USD": "عملات صغيرة", # كاردانو (سعره سنتات)
    "XRP-USD": "عملات صغيرة", # ريبل (سعره دولار أو أقل)
    "DOGE-USD": "عملات صغيرة" # دوج (سنتات)
}

def analyze_and_trade():
    current_prices = {}
    open_symbols = [t['symbol'] for t in db.get_all_trades() if t['status'] == 'OPEN']

    for symbol, asset_type in WATCHLIST.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="15m")
            if df.empty or len(df) < 20:
                continue

            close = df['Close']
            vol = df['Volume']
            curr_price = float(close.iloc[-1])
            current_prices[symbol] = curr_price

            sma20 = float(close.rolling(20).mean().iloc[-1])
            avg_vol = float(vol.rolling(20).mean().iloc[-1])
            curr_vol = float(vol.iloc[-1])

            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
            rs = gain / loss if loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            # شروط الدخول الحذر (سعر متماسك + زخم صحي مع سيولة)
            if symbol not in open_symbols:
                if curr_price > sma20 and 42 <= rsi <= 65:
                    vol_desc = "سيولة قوية أعلى من المعتاد" if curr_vol >= avg_vol else "حركة سعرية هادئة"
                    reason = f"أصل مناسب للمحفظة + فوق متوسط 20 + RSI متزن ({round(rsi,1)}) + {vol_desc}"
                    db.log_trade(symbol, asset_type, curr_price, reason)
        except Exception as e:
            print(f"خطأ في فحص {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices
