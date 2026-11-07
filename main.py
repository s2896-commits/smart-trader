from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
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
            print(f"Auto-scan error: {e}")
        time.sleep(60)

threading.Thread(target=background_scanner, daemon=True).start()

@app.get("/api/backtest")
def run_backtest():
    try:
        bot.run_historical_backtest()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/data")
def get_data(scan: bool = False):
    if scan:
        try:
            bot.analyze_and_trade()
        except Exception:
            pass
    trades = db.get_all_trades()
    won = len([t for t in trades if t['status'] == 'WON'])
    lost = len([t for t in trades if t['status'] == 'LOST'])
    open_t = len([t for t in trades if t['status'] == 'OPEN'])
    closed = won + lost
    win_rate = round((won / closed) * 100, 1) if closed > 0 else (100.0 if won > 0 else 0.0)
    
    total_pnl_sar = round(sum([float(t.get('pnl_sar') or t.get('pnl') or 0.0) for t in trades]), 2)
    wallet_balance_sar = round(60.0 + total_pnl_sar, 2)

    return JSONResponse({
        "wallet_sar": wallet_balance_sar,
        "total_pnl_sar": total_pnl_sar,
        "win_rate": win_rate,
        "open_t": open_t,
        "total_trades": len(trades),
        "trades": trades
    })

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>رادار التداول التجريبي (60 ريال)</title>
        <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #090d16; --card: #131b2e; --border: #1e293b;
                --accent: #38bdf8; --green: #10b981; --red: #ef4444;
                --amber: #f59e0b; --text: #f8fafc; --muted: #94a3b8;
            }
            * { box-sizing: border-box; }
            body { font-family: 'Tajawal', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 16px; padding-bottom: 40px; }
            .container { max-width: 600px; margin: 0 auto; }
            .top-bar {
                display: flex; justify-content: space-between; align-items: center;
                background: rgba(19, 27, 46, 0.9); padding: 14px 16px;
                border-radius: 16px; border: 1px solid var(--border); margin-bottom: 16px;
                position: sticky; top: 10px; z-index: 100;
            }
            .btn-group { display: flex; gap: 8px; }
            .btn { border: none; padding: 8px 12px; border-radius: 10px; font-family: inherit; font-size: 11px; font-weight: 700; cursor: pointer; color: #fff; }
            .btn-scan { background: #0284c7; }
            .btn-backtest { background: #8b5cf6; }
            .stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
            .stat-card { background: var(--card); border: 1px solid var(--border); padding: 14px; border-radius: 16px; }
            .stat-label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
            .stat-val { font-size: 20px; font-weight: 800; }
            .trade-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 16px; margin-bottom: 12px; }
            .trade-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
            .sym-name { font-size: 16px; font-weight: 800; }
            .badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; }
            .badge.OPEN { background: rgba(245, 158, 11, 0.15); color: var(--amber); }
            .badge.WON { background: rgba(16, 185, 129, 0.15); color: var(--green); }
            .badge.LOST { background: rgba(239, 68, 68, 0.15); color: var(--red); }
            .price-row { display: grid; grid-template-columns: repeat(3, 1fr); background: rgba(9, 13, 22, 0.6); padding: 10px; border-radius: 10px; margin-bottom: 10px; text-align: center; }
            .p-item span { display: block; font-size: 10px; color: var(--muted); }
            .p-item strong { font-size: 13px; }
            .info-box { font-size: 12px; line-height: 1.4; color: #cbd5e1; background: rgba(255,255,255,0.02); padding: 8px; border-radius: 6px; border-right: 3px solid var(--accent); margin-bottom: 6px; }
            .lesson-box { font-size: 12px; color: var(--muted); padding: 6px 8px; border-right: 3px solid #64748b; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="top-bar">
                <div>
                    <h1 style="margin:0;font-size:15px;font-weight:800">رادار التدريب (60 ريال)</h1>
                    <span style="font-size:11px;color:var(--muted)" id="timer-txt">تحديث تلقائي...</span>
                </div>
                <div class="btn-group">
                    <button class="btn btn-backtest" id="bt-btn" onclick="runBacktest()">⏳ دراسة الماضي</button>
                    <button class="btn btn-scan" onclick="manualScan()">⚡ فحص</button>
                </div>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">رصيد المحفظة (أساس 60 ر.س)</div>
                    <div class="stat-val" id="wallet-val" style="color:var(--accent)">60.00 ر.س</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">صافي الأرباح / الخسائر</div>
                    <div class="stat-val" id="pnl-val">0.00 ر.س</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">نسبة النجاح</div>
                    <div class="stat-val" id="win-rate" style="color:var(--green)">0%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">إجمالي العمليات والدروس</div>
                    <div class="stat-val" id="total-trades">0</div>
                </div>
            </div>

            <div id="trades-container"></div>
        </div>

        <script>
            let countdown = 30;
            async function fetchData(doScan = false) {
                try {
                    const res = await fetch('/api/data?scan=' + doScan);
                    const d = await res.json();
                    document.getElementById('wallet-val').innerText = d.wallet_sar + ' ر.س';
                    const pnlEl = document.getElementById('pnl-val');
                    pnlEl.innerText = (d.total_pnl_sar >= 0 ? '+' : '') + d.total_pnl_sar + ' ر.س';
                    pnlEl.style.color = d.total_pnl_sar >= 0 ? 'var(--green)' : 'var(--red)';
                    document.getElementById('win-rate').innerText = d.win_rate + '%';
                    document.getElementById('total-trades').innerText = d.total_trades;

                    const container = document.getElementById('trades-container');
                    if (d.trades.length === 0) {
                        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--muted)">اضغط "⏳ دراسة الماضي" لدراسة أفضل أوقات الدخول لآخر شهر فوراً!</div>';
                    } else {
                        container.innerHTML = d.trades.map(t => {
                            const statusText = t.status === 'OPEN' ? 'مفتوحة ⏳' : (t.status === 'WON' ? 'رابحة ✅' : 'حماية وقف 🛡️');
                            const pnl = t.pnl_sar !== undefined ? t.pnl_sar : (t.pnl || 0);
                            const inv = t.invested_sar || 20;
                            const pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                            return `
                            <div class="trade-card">
                                <div class="trade-header">
                                    <div>
                                        <span class="sym-name">${t.symbol}</span>
                                        <span style="font-size:11px;color:var(--muted)"> (${t.asset_type})</span>
                                    </div>
                                    <span class="badge ${t.status}">${statusText}</span>
                                </div>
                                <div class="price-row">
                                    <div class="p-item">
                                        <span>الدخول (${inv} ر.س)</span>
                                        <strong>${t.entry_price}$</strong>
                                    </div>
                                    <div class="p-item">
                                        <span>الخروج</span>
                                        <strong>${t.exit_price ? t.exit_price + '$' : 'حي الآن'}</strong>
                                    </div>
                                    <div class="p-item">
                                        <span>الربح بالريال</span>
                                        <strong style="color:${pnlColor}">${pnl > 0 ? '+' : ''}${pnl} ر.س</strong>
                                    </div>
                                </div>
                                <div class="info-box">💡 <b>السبب والوقت:</b> ${t.reason} <span style="font-size:10px;color:var(--muted)">(${t.entry_time})</span></div>
                                <div class="lesson-box">📌 <b>الدرس والتوقيت:</b> ${t.lesson || 'قيد المتابعة...'}</div>
                            </div>`;
                        }).join('');
                    }
                } catch(e) { console.error(e); }
                countdown = 30;
            }

            async function runBacktest() {
                const btn = document.getElementById('bt-btn');
                btn.innerText = '⏳ جاري الدراسة...';
                btn.disabled = true;
                await fetch('/api/backtest');
                await fetchData(false);
                btn.innerText = '✅ تمت الدراسة';
                setTimeout(() => { btn.innerText = '⏳ دراسة الماضي'; btn.disabled = false; }, 3000);
            }

            function manualScan() { fetchData(true); }
            fetchData(false);
            setInterval(() => {
                countdown--;
                if (countdown <= 0) { fetchData(true); }
                else { document.getElementById('timer-txt').innerText = 'تحديث خلال ' + countdown + ' ث...'; }
            }, 1000);
        </script>
    </body>
    </html>
    '''
