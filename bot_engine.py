import yfinance as yf
import database as db

# رادار شامل: أسهم سعودية رخيصة + أسهم أمريكية واعدة + عملات رقمية
WATCHLIST = {
    # 🇸🇦 السوق السعودي (تاسي) - يفتح الأحد 10 صباحاً
    "4300.SR": "أسهم سعودية (دار الأركان)",
    "2222.SR": "أسهم سعودية (أرامكو)",
    "4110.SR": "أسهم سعودية (باتك)",
    "2010.SR": "أسهم سعودية (سابك)",

    # 🇺🇸 السوق الأمريكي (أسهم نمو خفيفة) - يفتح الإثنين
    "PLTR": "أسهم أمريكية (بالنتير)",
    "SOFI": "أسهم أمريكية (سوفاي)",
    "RIVN": "أسهم أمريكية (ريفيان)",

    # 🌐 العملات الرقمية (شغالة 24/7)
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
            # جلب بيانات الشموع
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

            # فحص شروط الدخول المدروس
            if symbol not in open_symbols:
                if curr_price > sma20 and 40 <= rsi <= 68:
                    reason = f"زخم إيجابي + فوق متوسط 20 + مؤشر القوة RSI متزن ({round(rsi, 1)})"
                    db.log_trade(symbol, asset_type, curr_price, reason)
        except Exception as e:
            print(f"فحص {symbol}: {e}")

    db.update_open_trades(current_prices)
    return current_prices
