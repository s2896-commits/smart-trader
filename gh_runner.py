import os, json
import database as db
import bot_engine as bot
import main as app_main

def run_cycle():
    # 1. تشغيل فحص السوق والصفقات (5m / 15m + Aroon)
    bot.analyze_and_trade()

    # 2. إذا لم يكن هناك تدريب سابق في المعمل، شغله مرة واحدة تلقائياً
    brain = db.get_brain()
    if not brain.get("asset_profiles"):
        bot.run_backtest()

    # 3. تجهيز البيانات الحية وحقنها مباشرة داخل صفحة الواجهة
    s = db.get_summary()
    payload = {
        "cloud_ok": True,
        "cfg": db.get_ai_config(),
        "markets": bot.market_status(),
        "last_scan": db.fmt(db.now()),
        "error": None,
        "start": db.START_CAPITAL,
        "fee": db.FEE_PCT,
        "thoughts": db.get_thoughts(16),
        "favorites": db.get_favorites_grouped(),
        "chat": db.get_chat_history(25),
        "live": {**s, "trades": db.get_trades(0, 60)},
        "lab": db.get_lab(),
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # تعديل رابط جلب البيانات في الصفحة ليقرأ من GitHub مباشرة مع كسر الكاش
    html = app_main.PAGE.replace("fetch('/api/data')", "fetch('./data.json?t='+Date.now())")
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ تم تحديث الصفقات وبناء لوحة Grok الحية بنجاح!")

if __name__ == "__main__":
    run_cycle()
