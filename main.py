from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import database as db
import bot_engine as bot
import threading
import time

app = FastAPI()

def background_scanner():
    while True:
        try:
            bot.analyze_and_trade()
        except Exception as e:
            print(f"Error in auto-scan: {e}")
        time.sleep(180)

threading.Thread(target=background_scanner, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def dashboard():
    trades = db.get_all_trades()
    won = len([t for t in trades if t['status'] == 'WON'])
    lost = len([t for t in trades if t['status'] == 'LOST'])
    open_t = len([t for t in trades if t['status'] == 'OPEN'])
    closed = won + lost
    win_rate = round((won / closed) * 100, 1) if closed > 0 else 0.0
    total_pnl = round(sum([t['pnl'] for t in trades]), 2)

    rows_html = ""
    for t in trades:
        badge_color = "#f59e0b" if t['status'] == "OPEN" else ("#10b981" if t['status'] == "WON" else "#ef4444")
        status_ar = "قيد المراقبة ⏳" if t['status'] == "OPEN" else ("رابحة ✅" if t['status'] == "WON" else "مغلقة بحماية 🛡️")
        rows_html += f'''
        <tr>
            <td><b>{t['symbol']}</b> <span style="font-size:12px;color:#94a3b8">({t['asset_type']})</span></td>
            <td>{t['entry_price']}$</td>
            <td>{t['exit_price'] or '—'}</td>
            <td style="color:{badge_color};font-weight:bold">{status_ar}</td>
            <td style="color:{'#10b981' if t['pnl']>=0 else '#ef4444'}">{t['pnl']}$</td>
            <td>{t['reason']}</td>
            <td>{t['lesson'] or 'يراقب الهدف ووقف الخسارة اللحظي...'}</td>
        </tr>
        '''

    return f'''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="30">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>رادار التداول الذكي</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
            .btn {{ background: #3b82f6; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-weight: bold; }}
            .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }}
            .card {{ background: #1e293b; padding: 18px; border-radius: 12px; border: 1px solid #334155; }}
            .card h3 {{ margin: 0; font-size: 14px; color: #94a3b8; }}
            .card p {{ margin: 8px 0 0; font-size: 26px; font-weight: bold; }}
            table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; }}
            th, td {{ padding: 12px 15px; text-align: right; border-bottom: 1px solid #334155; font-size: 14px; }}
            th {{ background: #0f172a; color: #38bdf8; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>🤖 لوحة البوت الذكي (يفحص تلقائياً كل 3 دقائق)</h2>
            <a class="btn" href="/scan">🔍 فحص يدوي الآن</a>
        </div>
        <div class="cards">
            <div class="card"><h3>نسبة النجاح</h3><p style="color:#38bdf8">{win_rate}%</p></div>
            <div class="card"><h3>صافي الربح التجريبي</h3><p style="color:#10b981">{total_pnl}$</p></div>
            <div class="card"><h3>صفقات نشطة حالياً</h3><p style="color:#f59e0b">{open_t}</p></div>
            <div class="card"><h3>إجمالي الصفقات</h3><p>{len(trades)}</p></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>الأصل</th><th>سعر الدخول</th><th>سعر الخروج</th><th>الحالة</th><th>الربح/الخسارة</th><th>سبب الدخول (قرار البوت)</th><th>الدرس المستفاد / المراجعة</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="7" style="text-align:center">جاري أول فحص للسوق في الخلفية، سيتم تحديث الجدول تلقائياً...</td></tr>'}
            </tbody>
        </table>
    </body>
    </html>
    '''

@app.get("/scan")
def trigger_scan():
    bot.analyze_and_trade()
    return RedirectResponse(url="/")
