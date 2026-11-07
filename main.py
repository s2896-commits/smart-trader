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
    total_pnl = round(sum([t['pnl'] for t in trades]), 2)
    return JSONResponse({
        "win_rate": win_rate,
        "total_pnl": total_pnl,
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
        <title>رادار التداول الذكي</title>
        <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #090d16;
                --card: #131b2e;
                --border: #1e293b;
                --accent: #38bdf8;
                --green: #10b981;
                --red: #ef4444;
                --amber: #f59e0b;
                --text: #f8fafc;
                --muted: #94a3b8;
            }
            * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
            body {
                font-family: 'Tajawal', sans-serif;
                background: var(--bg);
                color: var(--text);
                margin: 0;
                padding: 16px;
                padding-bottom: 40px;
            }
            .container { max-width: 600px; margin: 0 auto; }
            .top-bar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                background: rgba(19, 27, 46, 0.85);
                backdrop-filter: blur(12px);
                padding: 14px 16px;
                border-radius: 16px;
                border: 1px solid var(--border);
                margin-bottom: 16px;
                position: sticky;
                top: 10px;
                z-index: 100;
            }
            .brand { display: flex; align-items: center; gap: 10px; }
            .pulse-dot {
                width: 10px; height: 10px;
                background: var(--green);
                border-radius: 50%;
                box-shadow: 0 0 10px var(--green);
                animation: pulse 1.5s infinite;
            }
            @keyframes pulse {
                0% { transform: scale(0.95); opacity: 0.7; }
                50% { transform: scale(1.2); opacity: 1; }
                100% { transform: scale(0.95); opacity: 0.7; }
            }
            .brand h1 { margin: 0; font-size: 16px; font-weight: 800; }
            .status-sub { font-size: 11px; color: var(--muted); display: block; }
            .scan-btn {
                background: linear-gradient(135deg, #0284c7, #2563eb);
                color: #fff;
                border: none;
                padding: 8px 14px;
                border-radius: 10px;
                font-family: inherit;
                font-size: 12px;
                font-weight: 700;
                cursor: pointer;
            }
            .scan-btn:disabled { opacity: 0.6; }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: var(--card);
                border: 1px solid var(--border);
                padding: 14px;
                border-radius: 16px;
            }
            .stat-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
            .stat-val { font-size: 22px; font-weight: 800; }
            .section-title {
                font-size: 15px;
                font-weight: 700;
                margin-bottom: 12px;
                color: var(--muted);
                display: flex;
                justify-content: space-between;
            }
            .trades-list { display: flex; flex-direction: column; gap: 12px; }
            .trade-card {
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 16px;
            }
            .trade-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 12px;
            }
            .sym-box { display: flex; align-items: center; gap: 8px; }
            .sym-name { font-size: 17px; font-weight: 800; }
            .sym-type {
                font-size: 11px;
                background: rgba(56, 189, 248, 0.12);
                color: var(--accent);
                padding: 2px 8px;
                border-radius: 6px;
            }
            .badge {
                font-size: 11px;
                font-weight: 700;
                padding: 4px 10px;
                border-radius: 8px;
            }
            .badge.OPEN { background: rgba(245, 158, 11, 0.15); color: var(--amber); }
            .badge.WON { background: rgba(16, 185, 129, 0.15); color: var(--green); }
            .badge.LOST { background: rgba(239, 68, 68, 0.15); color: var(--red); }
            .price-row {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                background: rgba(9, 13, 22, 0.6);
                padding: 10px 12px;
                border-radius: 12px;
                margin-bottom: 12px;
                text-align: center;
            }
            .p-item span { display: block; font-size: 11px; color: var(--muted); }
            .p-item strong { font-size: 14px; font-weight: 700; }
            .info-box {
                font-size: 12px;
                line-height: 1.5;
                color: #cbd5e1;
                background: rgba(255,255,255,0.02);
                padding: 8px 10px;
                border-radius: 8px;
                border-right: 3px solid var(--accent);
                margin-bottom: 6px;
            }
            .lesson-box {
                font-size: 12px;
                line-height: 1.5;
                color: var(--muted);
                padding: 6px 10px;
                border-right: 3px solid #64748b;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="top-bar">
                <div class="brand">
                    <div class="pulse-dot"></div>
                    <div>
                        <h1>رادار التداول الذكي</h1>
                        <span class="status-sub" id="timer-txt">تحديث تلقائي خلال 30 ث...</span>
                    </div>
                </div>
                <button class="scan-btn" id="scan-btn" onclick="manualScan()">⚡ فحص فوري</button>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">صافي الربح الكلي</div>
                    <div class="stat-val" id="total-pnl" style="color:var(--green)">0.0$</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">نسبة النجاح</div>
                    <div class="stat-val" id="win-rate" style="color:var(--accent)">0%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">صفقات نشطة</div>
                    <div class="stat-val" id="open-t" style="color:var(--amber)">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">إجمالي الصفقات</div>
                    <div class="stat-val" id="total-trades">0</div>
                </div>
            </div>

            <div class="section-title">
                <span>سجل العمليات الحية</span>
                <span id="last-up" style="font-size:11px"></span>
            </div>

            <div class="trades-list" id="trades-container"></div>
        </div>

        <script>
            let countdown = 30;

            async function fetchData(doScan = false) {
                const btn = document.getElementById('scan-btn');
                if (doScan) {
                    btn.disabled = true;
                    btn.innerText = '⏳ جاري الفحص...';
                }
                try {
                    const res = await fetch('/api/data?scan=' + doScan);
                    const data = await res.json();

                    const pnlEl = document.getElementById('total-pnl');
                    pnlEl.innerText = (data.total_pnl >= 0 ? '+' : '') + data.total_pnl + '$';
                    pnlEl.style.color = data.total_pnl >= 0 ? 'var(--green)' : 'var(--red)';

                    document.getElementById('win-rate').innerText = data.win_rate + '%';
                    document.getElementById('open-t').innerText = data.open_t;
                    document.getElementById('total-trades').innerText = data.total_trades;

                    const container = document.getElementById('trades-container');
                    if (data.trades.length === 0) {
                        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--muted)">جاري البحث عن أول فرصة...</div>';
                    } else {
                        container.innerHTML = data.trades.map(t => {
                            const statusText = t.status === 'OPEN' ? 'قيد المراقبة ⏳' : (t.status === 'WON' ? 'رابحة ✅' : 'مغلقة بحماية 🛡️');
                            const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
                            const pnlSign = t.pnl > 0 ? '+' : '';
                            return 
                            <div class="trade-card">
                                <div class="trade-header">
                                    <div class="sym-box">
                                        <span class="sym-name"></span>
                                        <span class="sym-type"></span>
                                    </div>
                                    <span class="badge "></span>
                                </div>
                                <div class="price-row">
                                    <div class="p-item">
                                        <span>سعر الدخول</span>
                                        <strong>$</strong>
                                    </div>
                                    <div class="p-item">
                                        <span>سعر الخروج</span>
                                        <strong></strong>
                                    </div>
                                    <div class="p-item">
                                        <span>الربح/الخسارة</span>
                                        <strong style="color:">$</strong>
                                    </div>
                                </div>
                                <div class="info-box">💡 <b>السبب:</b> </div>
                                <div class="lesson-box">📌 <b>المتابعة:</b> </div>
                            </div>;
                        }).join('');
                    }
                    const now = new Date();
                    document.getElementById('last-up').innerText = 'آخر تحديث: ' + now.toLocaleTimeString('ar-SA');
                } catch (e) {
                    console.error(e);
                } finally {
                    if (doScan) {
                        btn.disabled = false;
                        btn.innerText = '⚡ فحص فوري';
                    }
                    countdown = 30;
                }
            }

            function manualScan() { fetchData(true); }

            fetchData(true);
            setInterval(() => {
                countdown--;
                if (countdown <= 0) {
                    fetchData(true);
                } else {
                    document.getElementById('timer-txt').innerText = فحص تلقائي خلال  ث...;
                }
            }, 1000);
        </script>
    </body>
    </html>
    '''
