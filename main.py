from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
import database as db
import bot_engine as bot
import threading
import time
import os
import requests

app = FastAPI()
SELF_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://smart-trader-wo7s.onrender.com")

def background_worker():
    ping_counter = 0
    while True:
        try:
            bot.analyze_and_trade()
        except Exception as e:
            print(f"Scan error: {e}")
        
        # منبه ذاتي كل 5 دقائق لمنع سيرفر Render من النوم
        ping_counter += 1
        if ping_counter >= 5:
            try:
                requests.get(f"{SELF_URL}/api/ping", timeout=10)
            except Exception:
                pass
            ping_counter = 0
        time.sleep(60)

threading.Thread(target=background_worker, daemon=True).start()

@app.get("/api/ping")
def ping():
    return {"alive": True}

@app.get("/api/backtest")
def run_backtest(background_tasks: BackgroundTasks):
    background_tasks.add_task(bot.run_historical_backtest)
    return {"status": "started"}

@app.get("/api/data")
def get_data(scan: bool = False):
    if scan:
        try:
            bot.analyze_and_trade()
        except Exception:
            pass
    all_trades = db.get_all_trades()
    live_trades = [t for t in all_trades if t.get('is_historical', 0) == 0]
    hist_trades = [t for t in all_trades if t.get('is_historical', 0) == 1]

    # حسابات المحفظة الحية (60 ريال)
    l_won = len([t for t in live_trades if t['status'] == 'WON'])
    l_lost = len([t for t in live_trades if t['status'] == 'LOST'])
    l_open = len([t for t in live_trades if t['status'] == 'OPEN'])
    l_closed = l_won + l_lost
    l_win_rate = round((l_won / l_closed) * 100, 1) if l_closed > 0 else (100.0 if l_won > 0 else 0.0)
    
    live_pnl = round(sum([float(t.get('pnl_sar') or 0.0) for t in live_trades]), 2)
    invested_now = round(l_open * 20.0, 2)
    wallet_total = round(60.0 + live_pnl, 2)
    cash_available = round(max(0.0, wallet_total - invested_now), 2)

    # حسابات مختبر التدريب
    h_won = len([t for t in hist_trades if t['status'] == 'WON'])
    h_lost = len([t for t in hist_trades if t['status'] == 'LOST'])
    h_total = h_won + h_lost
    h_win_rate = round((h_won / h_total) * 100, 1) if h_total > 0 else 0.0
    h_pnl = round(sum([float(t.get('pnl_sar') or 0.0) for t in hist_trades]), 2)

    return JSONResponse({
        "cloud_ok": db.is_cloud_connected(),
        "live": {
            "wallet": wallet_total,
            "cash": cash_available,
            "invested": invested_now,
            "pnl": live_pnl,
            "win_rate": l_win_rate,
            "open_count": l_open,
            "closed_count": l_closed,
            "trades": live_trades
        },
        "lab": {
            "win_rate": h_win_rate,
            "sim_pnl": h_pnl,
            "total": h_total,
            "trades": hist_trades
        }
    })

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>SM-A-X Trader Pro</title>
        <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #060911; --surface: #0f172a; --card: #151f38;
                --border: rgba(255,255,255,0.07); --primary: #38bdf8;
                --purple: #a855f7; --green: #10b981; --red: #f43f5e;
                --amber: #f59e0b; --text: #f8fafc; --muted: #94a3b8;
            }
            * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
            body {
                font-family: 'Tajawal', sans-serif; background: var(--bg); color: var(--text);
                margin: 0; padding: 14px 14px 90px 14px;
            }
            .app-shell { max-width: 520px; margin: 0 auto; }
            
            /* Header */
            .header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 10px 4px; margin-bottom: 14px;
            }
            .brand-box { display: flex; align-items: center; gap: 10px; }
            .live-dot {
                width: 10px; height: 10px; border-radius: 50%; background: var(--green);
                box-shadow: 0 0 12px var(--green); animation: pulse 2s infinite;
            }
            @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
            .app-title { font-size: 18px; font-weight: 900; letter-spacing: 0.5px; margin: 0; }
            .sub-status { font-size: 11px; color: var(--muted); }
            .action-btn {
                background: rgba(56, 189, 248, 0.12); color: var(--primary);
                border: 1px solid rgba(56, 189, 248, 0.3); padding: 8px 14px;
                border-radius: 12px; font-family: inherit; font-size: 12px; font-weight: 700; cursor: pointer;
            }

            /* Hero Wallet Card */
            .hero-card {
                background: linear-gradient(135deg, #0284c7 0%, #1e1b4b 100%);
                border-radius: 22px; padding: 20px; margin-bottom: 16px;
                box-shadow: 0 12px 30px -10px rgba(2, 132, 199, 0.4);
                border: 1px solid rgba(255,255,255,0.12);
            }
            .hero-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
            .hero-label { font-size: 12px; color: rgba(255,255,255,0.75); display: block; margin-bottom: 4px; }
            .hero-balance { font-size: 30px; font-weight: 900; margin: 0; }
            .pnl-pill {
                background: rgba(0,0,0,0.3); padding: 5px 12px; border-radius: 20px;
                font-size: 13px; font-weight: 800;
            }
            .hero-grid {
                display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
                background: rgba(0,0,0,0.25); padding: 12px; border-radius: 14px; text-align: center;
            }
            .hero-item span { font-size: 11px; color: rgba(255,255,255,0.7); display: block; }
            .hero-item strong { font-size: 14px; font-weight: 800; }

            /* Lab Hero */
            .lab-hero {
                background: linear-gradient(135deg, #6d28d9 0%, #1e1b4b 100%);
                border-radius: 22px; padding: 20px; margin-bottom: 16px;
                border: 1px solid rgba(168, 85, 247, 0.3);
            }
            .lab-btn {
                width: 100%; background: #fff; color: #4c1d95; border: none;
                padding: 12px; border-radius: 12px; font-family: inherit;
                font-size: 13px; font-weight: 900; margin-top: 14px; cursor: pointer;
            }

            /* Trade Cards */
            .section-head { font-size: 14px; font-weight: 800; color: var(--muted); margin: 14px 4px 10px; display: flex; justify-content: space-between; }
            .t-card {
                background: var(--card); border: 1px solid var(--border);
                border-radius: 18px; padding: 16px; margin-bottom: 12px;
            }
            .t-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
            .t-sym { font-size: 16px; font-weight: 900; }
            .t-asset { font-size: 11px; color: var(--muted); display: block; }
            .badge { font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 8px; }
            .badge.OPEN { background: rgba(245, 158, 11, 0.15); color: var(--amber); }
            .badge.WON { background: rgba(16, 185, 129, 0.15); color: var(--green); }
            .badge.LOST { background: rgba(244, 63, 94, 0.15); color: var(--red); }
            .t-metrics {
                display: grid; grid-template-columns: repeat(3, 1fr);
                background: var(--surface); padding: 10px; border-radius: 12px;
                text-align: center; margin-bottom: 10px;
            }
            .t-metrics span { font-size: 10px; color: var(--muted); display: block; }
            .t-metrics strong { font-size: 13px; font-weight: 800; }
            .t-note { font-size: 12px; color: #cbd5e1; background: rgba(255,255,255,0.03); padding: 8px 10px; border-radius: 8px; margin-bottom: 6px; border-right: 3px solid var(--primary); }
            .t-lesson { font-size: 11px; color: var(--muted); padding: 4px 10px; border-right: 3px solid #475569; }

            /* Bottom Navigation */
            .bottom-nav {
                position: fixed; bottom: 0; left: 0; right: 0;
                background: rgba(15, 23, 42, 0.92); backdrop-filter: blur(16px);
                border-top: 1px solid var(--border); display: flex;
                justify-content: space-around; padding: 10px 8px 14px; z-index: 999;
            }
            .nav-item {
                background: none; border: none; color: var(--muted);
                font-family: inherit; font-size: 11px; font-weight: 700;
                display: flex; flex-direction: column; align-items: center; gap: 4px;
                cursor: pointer; padding: 6px 16px; border-radius: 12px;
            }
            .nav-item.active { color: var(--primary); background: rgba(56, 189, 248, 0.1); }
            .tab-view { display: none; }
            .tab-view.active { display: block; }
            .sys-row {
                display: flex; justify-content: space-between; align-items: center;
                background: var(--card); padding: 14px 16px; border-radius: 14px;
                margin-bottom: 10px; border: 1px solid var(--border); font-size: 13px; font-weight: 700;
            }
        </style>
    </head>
    <body>
        <div class="app-shell">
            <div class="header">
                <div class="brand-box">
                    <div class="live-dot"></div>
                    <div>
                        <h1 class="app-title">رادار التداول الذكي</h1>
                        <span class="sub-status" id="timer-txt">متصل بالسحابة • تحديث آلي</span>
                    </div>
                </div>
                <button class="action-btn" onclick="fetchData(true)">⚡ فحص الآن</button>
            </div>

            <!-- الشاشة 1: المحفظة الحية -->
            <div id="tab-live" class="tab-view active">
                <div class="hero-card">
                    <div class="hero-top">
                        <div>
                            <span class="hero-label">إجمالي المحفظة الحية (رأس المال 60 ر.س)</span>
                            <h2 class="hero-balance" id="l-wallet">60.00 ر.س</h2>
                        </div>
                        <div class="pnl-pill" id="l-pnl">+0.00 ر.س</div>
                    </div>
                    <div class="hero-grid">
                        <div class="hero-item"><span>الكاش المتاح</span><strong id="l-cash">60.0 ر.س</strong></div>
                        <div class="hero-item"><span>في صفقات</span><strong id="l-inv">0.0 ر.س</strong></div>
                        <div class="hero-item"><span>نسبة النجاح</span><strong id="l-win">0%</strong></div>
                    </div>
                </div>

                <div class="section-head">
                    <span>الصفقات الحية الجارية والمغلقة</span>
                    <span id="l-count">0 عمليات</span>
                </div>
                <div id="live-list"></div>
            </div>

            <!-- الشاشة 2: مختبر التدريب -->
            <div id="tab-lab" class="tab-view">
                <div class="lab-hero">
                    <span class="hero-label">مختبر التدريب ودراسة الشارتات (معزول عن رصيدك)</span>
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                        <div>
                            <span style="font-size:11px; color:rgba(255,255,255,0.7)">نسبة نجاح الاستراتيجية بالماضي</span>
                            <h2 style="margin:2px 0 0; font-size:26px; font-weight:900" id="h-win">0%</h2>
                        </div>
                        <div style="text-align:left">
                            <span style="font-size:11px; color:rgba(255,255,255,0.7)">الربح التدريبي المفترض</span>
                            <strong style="display:block; font-size:18px" id="h-pnl">0.00 ر.س</strong>
                        </div>
                    </div>
                    <button class="lab-btn" id="bt-btn" onclick="runBacktest()">🔬 تشغيل محاكاة الشهر الماضي وتوليد الدروس</button>
                </div>

                <div class="section-head">
                    <span>الدروس المستخرجة من بيانات الماضي</span>
                    <span id="h-count">0 دروس</span>
                </div>
                <div id="lab-list"></div>
            </div>

            <!-- الشاشة 3: حالة النظام والأسواق -->
            <div id="tab-sys" class="tab-view">
                <div class="section-head"><span>حالة الربط السحابي والأسواق</span></div>
                <div class="sys-row">
                    <span>☁️ الخزنة السحابية الدائمة (GitHub)</span>
                    <span id="cloud-status">جاري الفحص...</span>
                </div>
                <div class="sys-row">
                    <span>⏰ منبه منع نوم السيرفر (24/7)</span>
                    <span style="color:var(--green)">نشط (نبض كل 5 د) ✅</span>
                </div>
                <div class="sys-row">
                    <span>🌐 سوق العملات الرقمية (SOL, XRP, DOGE)</span>
                    <span style="color:var(--green)">مفتوح 24/7 🟢</span>
                </div>
                <div class="sys-row">
                    <span>🇸🇦 السوق السعودي تاسي (أرامكو، سابك، الأركان)</span>
                    <span style="color:var(--amber)">الأحد - الخميس (10ص - 3م)</span>
                </div>
                <div class="sys-row">
                    <span>🇺🇸 السوق الأمريكي (PLTR, SOFI)</span>
                    <span style="color:var(--amber)">الإثنين - الجمعة (5:30م - 12ص)</span>
                </div>
            </div>
        </div>

        <!-- شريط التنقل السفلي -->
        <div class="bottom-nav">
            <button class="nav-item active" onclick="switchTab('live', this)">💼<span>المحفظة الحية</span></button>
            <button class="nav-item" onclick="switchTab('lab', this)">🧪<span>مختبر التدريب</span></button>
            <button class="nav-item" onclick="switchTab('sys', this)">📡<span>الرادار والنظام</span></button>
        </div>

        <script>
            let timer = 30;

            function switchTab(tab, btn) {
                document.querySelectorAll('.tab-view').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
                document.getElementById('tab-' + tab).classList.add('active');
                btn.classList.add('active');
            }

            function renderCards(trades, emptyMsg) {
                if (!trades || trades.length === 0) {
                    return `<div style="text-align:center;padding:35px 15px;color:var(--muted);background:var(--card);border-radius:16px;font-size:13px">${emptyMsg}</div>`;
                }
                return trades.map(t => {
                    const statusMap = { 'OPEN': 'جارية الآن ⏳', 'WON': 'رابحة ✅', 'LOST': 'حماية وقف 🛡️' };
                    const pnl = t.pnl_sar || 0;
                    const pColor = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                    return `
                    <div class="t-card">
                        <div class="t-top">
                            <div>
                                <span class="t-sym">${t.symbol}</span>
                                <span class="t-asset">${t.asset_type} • ${t.entry_time || ''}</span>
                            </div>
                            <span class="badge ${t.status}">${statusMap[t.status] || t.status}</span>
                        </div>
                        <div class="t-metrics">
                            <div><span>سعر الدخول</span><strong>${t.entry_price}$</strong></div>
                            <div><span>سعر الخروج</span><strong>${t.exit_price ? t.exit_price + '$' : 'مباشر'}</strong></div>
                            <div><span>الصافي بالريال</span><strong style="color:${pColor}">${pnl > 0 ? '+' : ''}${pnl} ر.س</strong></div>
                        </div>
                        <div class="t-note">💡 ${t.reason}</div>
                        <div class="t-lesson">📌 ${t.lesson || 'يراقب حركة السعر اللحظية...'}</div>
                    </div>`;
                }).join('');
            }

            async function fetchData(scan = false) {
                try {
                    const res = await fetch('/api/data?scan=' + scan);
                    const d = await res.json();

                    // تحديث المحفظة الحية
                    document.getElementById('l-wallet').innerText = d.live.wallet.toFixed(2) + ' ر.س';
                    const pnlEl = document.getElementById('l-pnl');
                    pnlEl.innerText = (d.live.pnl >= 0 ? '+' : '') + d.live.pnl.toFixed(2) + ' ر.س';
                    pnlEl.style.color = d.live.pnl >= 0 ? '#4ade80' : '#fda4af';
                    document.getElementById('l-cash').innerText = d.live.cash.toFixed(1) + ' ر.س';
                    document.getElementById('l-inv').innerText = d.live.invested.toFixed(1) + ' ر.س';
                    document.getElementById('l-win').innerText = d.live.win_rate + '%';
                    document.getElementById('l-count').innerText = d.live.trades.length + ' عمليات';
                    document.getElementById('live-list').innerHTML = renderCards(d.live.trades, 'لا توجد صفقات حية حالياً — الرادار يفحص السوق كل دقيقة لصيد أول فرصة حقيقية.');

                    // تحديث مختبر التدريب
                    document.getElementById('h-win').innerText = d.lab.win_rate + '%';
                    document.getElementById('h-pnl').innerText = (d.lab.sim_pnl >= 0 ? '+' : '') + d.lab.sim_pnl.toFixed(2) + ' ر.س';
                    document.getElementById('h-count').innerText = d.lab.total + ' دروس';
                    document.getElementById('lab-list').innerHTML = renderCards(d.lab.trades, 'اضغط الزر الأبيض بالأعلى لتشغيل محاكاة الشهر الماضي واستخراج الدروس.');

                    // حالة السحابة
                    const cEl = document.getElementById('cloud-status');
                    cEl.innerText = d.cloud_ok ? 'مربوطة ومحفوظة 🟢' : 'غير مفعلة (أضف GITHUB_TOKEN) 🔴';
                    cEl.style.color = d.cloud_ok ? 'var(--green)' : 'var(--red)';
                } catch(e) { console.error(e); }
                timer = 30;
            }

            async function runBacktest() {
                const btn = document.getElementById('bt-btn');
                btn.innerText = '⏳ جاري فحص شارتات الشهر الماضي...';
                btn.disabled = true;
                await fetch('/api/backtest');
                setTimeout(async () => {
                    await fetchData(false);
                    btn.innerText = '✅ تم تحديث دروس المختبر';
                    setTimeout(() => { btn.innerText = '🔬 تشغيل محاكاة الشهر الماضي وتوليد الدروس'; btn.disabled = false; }, 2500);
                }, 4000);
            }

            fetchData(false);
            setInterval(() => {
                timer--;
                if (timer <= 0) fetchData(true);
                else document.getElementById('timer-txt').innerText = 'نبض حي • فحص تلقائي خلال ' + timer + ' ث';
            }, 1000);
        </script>
    </body>
    </html>
    '''
