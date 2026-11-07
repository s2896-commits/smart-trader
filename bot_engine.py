import yfinance as yf
import database as db

WATCHLIST = {
    # 🇸🇦 السوق السعودي (تاسي)
    "4300.SR": "أسهم سعودية (دار الأركان)",
    "2222.SR": "أسهم سعودية (أرامكو)",
    "4110.SR": "أسهم سعودية (باتك)",
    "2010.SR": "أسهم سعودية (سابك)",

    # 🇺🇸 السوق الأمريكي
    "PLTR": "أسهم أمريكية (بالنتير)",
    "SOFI": "أسهم أمريكية (سوفاي)",
    "RIVN": "أسهم أمريكية (ريفيان)",

    # 🌐 العملات الرقمية
    "ADA-USD": "عملات رقمية (كاردانو)",
    "XRP-USD": "عملات رقمية (ريبل)",
    "DOGE-USD": "عملات رقمية (دوج)",
    "SOL-USD": "عملات رقمية (سولانا)"
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

            if symbol not in open_symbols:
                # 1. استراتيجية الزخم مع زخم سيولة
                if curr_price > sma20 and 45 <= rsi <= 65 and curr_vol > (avg_vol * 0.8):
                    reason = f"نمط زخم: فوق متوسط 20 + RSI صحي ({round(rsi, 1)}) + سيولة نشطة"
                    db.log_trade(symbol, asset_type, curr_price, reason)

                # 2. استراتيجية ارتداد القاع (شراء في مناطق تشبع البيع مع تحسن الزخم)
                elif rsi < 32 and curr_price > float(close.iloc[-2]):
                    reason = f"نمط ارتداد قاع: تشبع بيعي قوي ({round(rsi, 1)}) مع بداية ارتداد سعري"
                    db.log_trade(symbol, asset_type, curr_price, reason)

        except Exception as e:
            print(f"فحص {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices
