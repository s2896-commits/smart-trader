from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import threading, time
import database as db
import bot_engine as bot

state = {"last_scan": None, "error": None}

class ChatInput(BaseModel):
    message: str

def worker():
    while True:
        try:
            bot.analyze_and_trade()
            state.update(last_scan=db.fmt(db.now()), error=None)
            db.backup_if_dirty()
        except Exception as e:
            state["error"] = str(e)[:120]
        time.sleep(90)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker, daemon=True).start()
    yield
    db.backup_if_dirty(force=True)

app = FastAPI(lifespan=lifespan)

@app.get("/api/scan")
def scan(bg: BackgroundTasks):
    bg.add_task(bot.analyze_and_trade)
    return {"ok": True}

@app.get("/api/reset_exam")
def reset_exam_api():
    db.reset_exam_clean()
    return {"ok": True}

@app.get("/api/pause")
def set_pause_api(paused: int = 0):
    st = db.toggle_bot_pause(bool(paused))
    return {"ok": True, "paused": st}

@app.get("/api/risk")
def set_risk(mode: str = "medium"):
    if mode in ("low", "medium", "high"):
        cfg = db.get_ai_config()
        cfg["risk_mode"] = mode
        db.save_ai_config(cfg)
    return {"ok": True, "risk_mode": mode}

@app.get("/api/capital")
def set_capital_api(amount: float = 60.0):
    cap = db.set_capital_override(amount)
    return {"ok": True, "capital": cap}

@app.get("/api/prep_withdraw")
def set_prep_withdraw_api(enabled: int = 0):
    st = db.toggle_prep_withdraw(bool(enabled))
    return {"ok": True, "prep_withdraw_mode": st}

@app.get("/api/kill_switch")
def kill_switch_api():
    closed_cnt = db.emergency_close_all()
    return {"ok": True, "closed": closed_cnt}

@app.get("/api/withdraw")
def withdraw_api(amount: float = 0.0):
    ok, pulled = db.execute_withdrawal(amount if amount > 0 else None, mode="يدوي 💸")
    return {"ok": ok, "withdrawn": pulled}

@app.get("/api/auto_withdraw")
def auto_withdraw_api(enabled: int = 1, limit: float = 10.0):
    cfg = db.configure_auto_withdraw(bool(enabled), limit)
    return {"ok": True, "enabled": cfg["auto_withdraw_enabled"], "limit": cfg["auto_withdraw_limit"]}

@app.get("/api/close_trade")
def close_trade_api(id: int, pnl: float = None):
    return {"ok": db.close_trade_manual(id, live_pnl=pnl)}

@app.post("/api/chat")
def chat_endpoint(body: ChatInput):
    return {"reply": db.ask_bot_chat(body.message), "history": db.get_chat_history()}

@app.get("/api/data")
def data():
    s = db.get_summary()
    return {
        "cloud_ok": True,
        "version": db.VERSION,
        "cfg": db.get_ai_config(),
        "markets": bot.market_status(),
        "last_scan": state["last_scan"] or db.fmt(db.now()),
        "error": state["error"],
        "start": s.get("active_capital", db.START_CAPITAL),
        "fee": db.FEE_PCT,
        "thoughts": db.get_thoughts(16),
        "favorites": db.get_favorites_grouped(),
        "chat": db.get_chat_history(25),
        "live": {**s, "trades": db.get_trades(0, 50)},
        "lab": db.get_lab(),
    }

PAGE = r'''<!DOCTYPE html>
<html dir="rtl" lang="ar"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#04070e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Grok Bot v13.0 • امتحان التخرج النظيف (20 ر.س باينانس)</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#04070e;--surface:#090e1a;--card:#0e1628;--line:rgba(255,255,255,.09);--pri:#38bdf8;--pur:#a855f7;
--grn:#10b981;--red:#f43f5e;--amb:#f59e0b;--txt:#f8fafc;--mut:#94a3b8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:'Tajawal',sans-serif;background:var(--bg);color:var(--txt);margin:0;
padding:calc(10px + env(safe-area-inset-top)) 12px calc(165px + env(safe-area-inset-bottom));overflow-x:hidden}
.shell{max-width:540px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:center;padding:4px 0 8px;gap:6px}
.brand{display:flex;gap:9px;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;background:var(--grn);box-shadow:0 0 12px var(--grn);animation:pulse 2s infinite;flex-shrink:0}
@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.25)}}
h1{font-size:14.5px;font-weight:900;margin:0}.sub{font-size:9.5px;color:var(--mut);display:block}
button{font-family:inherit;cursor:pointer}
.btn{background:rgba(56,189,248,.14);color:var(--pri);border:1px solid rgba(56,189,248,.35);padding:6px 9px;border-radius:11px;font-size:10px;font-weight:800;white-space:nowrap}

.qa-strip{display:flex;justify-content:space-between;align-items:center;gap:6px;background:linear-gradient(90deg,#06281e,#0c192c);border:1px solid rgba(16,185,129,.45);border-radius:12px;padding:7px 10px;margin-bottom:9px;font-size:10px;font-weight:800}
.ver-pill{background:linear-gradient(135deg,#f59e0b,#10b981);color:#04070e;padding:2px 8px;border-radius:7px;font-size:9.5px;font-weight:900}

.brief-card{background:linear-gradient(135deg,#0f172a,#17153b);border:1px solid rgba(56,189,248,.45);border-radius:14px;padding:9px 11px;margin-bottom:9px}
.brief-hd{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:900;color:#38bdf8;margin-bottom:5px;border-bottom:1px solid rgba(255,255,255,.07);padding-bottom:4px}
.brief-line{font-size:10px;color:#e2e8f0;margin:3px 0;line-height:1.45}

.ctrl-strip{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:9px}
.c-act-btn{padding:9px 8px;border-radius:12px;font-size:11px;font-weight:900;border:0;display:flex;align-items:center;justify-content:center;gap:5px}
.c-act-btn.run{background:linear-gradient(135deg,#059669,#10b981);color:#022c22}
.c-act-btn.paused{background:linear-gradient(135deg,#d97706,#f59e0b);color:#04070e}
.c-act-btn.kill{background:rgba(244,63,94,.16);color:#fda4af;border:1px solid rgba(244,63,94,.45)}

.day-week-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-bottom:9px;text-align:center}
.dw-box{background:#070c18;border:1px solid var(--line);border-radius:11px;padding:6px 4px}
.dw-box span{font-size:8.5px;color:var(--mut);display:block}
.dw-box strong{font-size:11.5px;display:block;margin-top:2px}

.top-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:9px}
.mcard{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 8px;text-align:center}
.mcard.pri{background:linear-gradient(135deg,#0c192c,#111c35);border-color:rgba(56,189,248,.3)}
.mcard.vlt{background:linear-gradient(135deg,#052e24,#0b172a);border-color:rgba(16,185,129,.35)}
.lbl{font-size:10px;color:var(--mut);display:block;margin-bottom:3px}
.big{font-size:16.5px;font-weight:900;margin:0}

.vip-card{background:linear-gradient(135deg,#1e1b4b,#091526);border:1.5px solid rgba(245,158,11,.6);border-radius:16px;padding:11px;margin-bottom:10px}
.vip-hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;border-bottom:1px solid rgba(255,255,255,.08);padding-bottom:5px}
.vip-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;text-align:center;background:rgba(0,0,0,.28);padding:7px;border-radius:10px;margin-bottom:8px}
.vip-grid span{font-size:8.5px;color:#cbd5e1;display:block}.vip-grid strong{font-size:11px;display:block;margin-top:2px}
.calc-bar{display:flex;justify-content:space-between;align-items:center;gap:5px;flex-wrap:wrap;font-size:10px;color:#e2e8f0}
.cbtn{background:rgba(255,255,255,.07);border:1px solid var(--line);color:var(--mut);padding:3px 8px;border-radius:7px;font-size:10px;font-weight:800}
.cbtn.on{background:rgba(245,158,11,.25);color:#fbbf24;border-color:#f59e0b}

.split-board{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;background:#070c18;border:1px solid var(--line);border-radius:14px;padding:9px;margin-bottom:10px;text-align:center}
.sb-col{padding:4px;border-radius:10px}
.sb-col.win{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.25)}
.sb-col.loss{background:rgba(244,63,94,.08);border:1px solid rgba(244,63,94,.25)}
.sb-col.net{background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.25)}
.sb-col span{font-size:9.5px;color:var(--mut);display:block}
.sb-col strong{font-size:12.5px;display:block;margin:2px 0}
.sb-col small{font-size:9px;font-weight:700}

.goal-bar{background:var(--card);border:1px solid rgba(245,158,11,.4);border-radius:13px;padding:9px 11px;margin-bottom:10px;font-size:11px}
.g-track{height:8px;background:#050811;border-radius:6px;margin:6px 0;overflow:hidden;border:1px solid var(--line)}
.g-fill{height:100%;background:linear-gradient(90deg,#f59e0b,#10b981,#38bdf8);border-radius:6px;transition:width .4s}
.g-marks{display:flex;justify-content:space-between;font-size:9.5px;color:var(--mut);font-weight:700}

.crew-bar{display:grid;grid-template-columns:repeat(5,1fr);gap:5px;margin-bottom:10px}
.bot-card{background:#070c18;border:1px solid var(--line);border-radius:12px;padding:6px 3px;text-align:center;min-width:0}
.bot-card.working{border-color:rgba(16,185,129,.55)}
.stg-pill{font-size:7.5px;font-weight:900;color:#34d399;background:rgba(16,185,129,.12);border-radius:5px;padding:1.5px 3px;margin-bottom:3px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bub{font-size:7.8px;color:#e2e8f0;background:rgba(255,255,255,.05);border-radius:5px;padding:2px 3px;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ava{width:24px;height:20px;margin:0 auto 3px;border-radius:6px;display:flex;align-items:center;justify-content:center;gap:3px}
.eye{width:3.5px;height:5px;background:#fff;border-radius:2px;animation:blink 3.5s infinite}
@keyframes blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(0.1)}}
.bname{font-size:9.5px;font-weight:900;display:block}
.brole{font-size:8px;color:var(--mut);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.chart-box,.term,.obsidian-box{background:#03060c;border:1px solid rgba(16,185,129,.28);border-radius:15px;padding:10px;margin-bottom:9px}
.obsidian-box{border-color:rgba(245,158,11,.45);background:radial-gradient(circle at center,#131129 0%,#04070e 75%)}
.box-hd{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:800;color:var(--grn);border-bottom:1px solid rgba(255,255,255,.06);padding-bottom:5px;margin-bottom:6px}
.term-body{height:115px;overflow-y:auto;font-size:11px;line-height:1.6}
.tline{margin-bottom:3px;color:#cbd5e1}.tline b{color:var(--pri)}.tline .tm{color:#64748b;font-size:9.5px;margin-left:4px}

.pockets{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
.pk{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:8px 5px;text-align:center}
.pk.res10{border-color:rgba(245,158,11,.45);background:rgba(245,158,11,.06)}
.pk h4{margin:0 0 3px;font-size:9px;color:var(--pri)}.pk strong{font-size:12.5px;display:block}
.pk small{font-size:8px;color:var(--mut);display:block;margin-top:2px;line-height:1.3}

.risk-row{display:flex;gap:5px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:13px;padding:7px 9px;margin-bottom:10px;font-size:11px;font-weight:800}
.rbtn{flex:1;background:var(--surface);border:1px solid var(--line);color:var(--mut);padding:6px 4px;border-radius:8px;font-size:10.5px;font-weight:800}
.rbtn.on{background:rgba(16,185,129,.18);color:#34d399;border-color:rgba(16,185,129,.55)}

.chips{display:flex;gap:6px;margin:4px 0 10px;overflow-x:auto;padding-bottom:2px}
.chip{background:var(--card);border:1px solid var(--line);color:var(--mut);padding:6px 13px;border-radius:18px;font-size:11px;font-weight:700;white-space:nowrap}
.chip.on{color:var(--pri);border-color:rgba(56,189,248,.5);background:rgba(56,189,248,.14)}

.hero-lab{background:linear-gradient(135deg,#3b0764,#0f172a);border-radius:16px;padding:13px;margin-bottom:10px;border:1px solid rgba(168,85,247,.45)}
.t{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px;margin-bottom:9px}
.t.OPEN{border-color:rgba(245,158,11,.45)}
.tt{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;gap:6px}
.sym{font-size:14px;font-weight:900}.as{font-size:10px;color:var(--mut);display:block}
.bd{font-size:10px;font-weight:800;padding:3px 8px;border-radius:8px;white-space:nowrap}
.bd.OPEN{background:rgba(245,158,11,.15);color:var(--amb)}.bd.WON{background:rgba(16,185,129,.15);color:var(--grn)}.bd.LOST{background:rgba(244,63,94,.15);color:var(--red)}
.m{display:grid;grid-template-columns:repeat(3,1fr);background:var(--surface);padding:7px;border-radius:10px;text-align:center;margin-bottom:6px}
.m span{font-size:9px;color:var(--mut);display:block}.m strong{font-size:11.5px}
.note{font-size:10.5px;color:#cbd5e1;background:rgba(255,255,255,.03);padding:5px 8px;border-radius:7px;margin-bottom:3px;border-right:3px solid var(--pri)}
.les{font-size:10px;color:var(--mut);padding:2px 8px;border-right:3px solid #475569}
.close-one-btn{width:100%;margin-top:7px;background:rgba(56,189,248,.16);color:#38bdf8;border:1px solid rgba(56,189,248,.45);padding:6px;border-radius:9px;font-size:10.5px;font-weight:900}
.empty{text-align:center;padding:22px 12px;color:var(--mut);background:var(--card);border-radius:14px;font-size:11.5px}
.sys{display:flex;justify-content:space-between;align-items:center;background:var(--card);padding:11px 13px;border-radius:13px;margin-bottom:7px;border:1px solid var(--line);font-size:11.5px;font-weight:700;gap:8px}
.blur-num{filter:blur(6px);user-select:none}

nav{position:fixed;bottom:0;left:0;right:0;background:rgba(9,14,26,.97);backdrop-filter:blur(16px);border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:6px 6px calc(10px + env(safe-area-inset-bottom));z-index:99}
.nv{background:none;border:0;color:var(--mut);font-size:10.5px;font-weight:800;display:flex;flex-direction:column;align-items:center;gap:2px;padding:5px 10px;border-radius:11px}
.nv.act{color:var(--pri);background:rgba(56,189,248,.12)}
.tab{display:none}.tab.act{display:block}
</style></head><body>
<div class="shell">
 <div class="head">
  <div class="brand"><div class="dot" id="hb-dot"></div><div><h1>Grok Bot v13.0 • SM-A-X</h1><span class="sub" id="sub">جاري الاتصال المباشر بباينانس...</span></div></div>
  <div style="display:flex;gap:5px">
   <button class="btn" id="priv-btn" onclick="togglePrivacy()">🔓 الأرقام ظاهرة</button>
   <button class="btn" onclick="liveBinanceTick(true)">⚡ تحديث</button>
  </div>
 </div>

 <div class="qa-strip">
  <div><span class="ver-pill" id="ver-bdg">v13.0 • امتحان التخرج</span> <span id="qa-summary" style="margin-right:5px;color:#34d399">🏁 0/10 صفقات باينانس</span></div>
  <span id="hb-status" style="color:var(--grn)">⚡ بث باينانس نشط</span>
 </div>

 <div class="brief-card">
  <div class="brief-hd"><span>📋 تقرير امتحان الـ 10 صفقات النظيف</span><span style="color:#fbbf24;font-size:9.5px">عمولة BNB 0.075% ⚡</span></div>
  <div class="brief-line" id="br-done">🏁 الامتحان النظيف: 0/10 صفقات بـ 60.00 ر.س</div>
  <div class="brief-line" id="br-watch">🛡️ تقسيمة باينانس: 40 ر.س عادي (20×2) + 20 ر.س فزعة 93%+</div>
  <div class="brief-line" id="br-next">🎯 البطلان فقط: انفجار الحيتان 3x + قناص القيعان المشدد</div>
 </div>

 <div class="day-week-bar">
  <div class="dw-box"><span>🏁 التقدم</span><strong id="dw-prog" style="color:#fbbf24">0 / 10</strong></div>
  <div class="dw-box"><span>📅 ربح الامتحان</span><strong class="sec-num" id="dw-today" style="color:var(--grn)">+0.00 ر.س</strong></div>
  <div class="dw-box"><span>🔥 نسبة الفوز</span><strong id="dw-elite" style="color:var(--pri)">0%</strong></div>
  <div class="dw-box"><span>🧺 قفل السلة</span><strong style="color:#fbbf24">+0.70 ر.س</strong></div>
 </div>

 <div class="ctrl-strip">
  <button class="c-act-btn run" id="bot-run-btn" onclick="toggleBotRun()">🟢 الامتحان يعمل (إيقاف مؤقت)</button>
  <button class="c-act-btn kill" onclick="emergencyKill()">🛑 إغلاق السلة وإرجاع الكاش</button>
 </div>

 <div id="tab-live" class="tab act">
  <div class="top-metrics">
   <div class="mcard pri"><span class="lbl">رصيد الامتحان (60.00)</span><h2 class="big sec-num" id="w">60.00 ر.س</h2><small class="sec-num" id="pnl" style="font-size:10px;font-weight:800">الصافي: +0.00 ر.س</small></div>
   <div class="mcard"><span class="lbl">حجم الصفقة الحقيقي</span><h2 class="big" style="color:var(--pri)">20 ر.س</h2><small id="best-th" style="font-size:9px;color:var(--grn)">انفجار الحيتان 3x 💎</small></div>
   <div class="mcard vlt"><span class="lbl">معامل الربح (PF)</span><h2 class="big" id="pf-top" style="color:#34d399">0.00</h2><small id="split-rem" style="font-size:9px;color:#a7f3d0">عملات باينانس فقط</small></div>
  </div>

  <div class="goal-bar">
   <div style="display:flex;justify-content:space-between"><span>🏁 شريط امتحان التخرج النظيف (<b id="pg-t">0/10</b>)</span><b id="goal-pct" style="color:var(--grn)">1.00x</b></div>
   <div class="g-track"><div class="g-fill" id="pg-b" style="width:5%"></div></div>
   <div class="g-marks"><span>البداية 60 ر.س</span><span>3 صفقات</span><span>5 صفقات</span><span>8 صفقات</span><span>النتيجة 10 👑</span></div>
  </div>

  <div class="split-board">
   <div class="sb-col win"><span>✅ الصفقات الناجحة</span><strong id="sb-w-cnt" style="color:var(--grn)">0 (0%)</strong><small class="sec-num" id="sb-w-sar" style="color:#6ee7b7">+0.00 ر.س</small></div>
   <div class="sb-col loss"><span>🛡️ الصفقات الخاسرة</span><strong id="sb-l-cnt" style="color:var(--red)">0 (0%)</strong><small class="sec-num" id="sb-l-sar" style="color:#fda4af">-0.00 ر.س</small></div>
   <div class="sb-col net"><span>⚖️ صافي الامتحان</span><strong id="sb-net-wr" style="color:var(--pri)">+0.00 ر.س</strong><small id="sb-net-sar">أفضل صفقة: +0.00 ر.س</small></div>
  </div>

  <div class="crew-bar" id="crew-bar"></div>
  <div class="pockets" id="pockets-grid"></div>

  <div class="vip-card">
   <div class="vip-hd">
    <div>
     <strong style="font-size:12px;color:#fbbf24">🎯 رادار توصيات صالح الشخصي (باينانس)</strong>
     <span id="vip-status" style="font-size:9.5px;color:#34d399;display:block">🟢 يبحث عن أقوى عملة سيولة الآن</span>
    </div>
    <span class="bd OPEN" id="vip-score">ضمان 94%</span>
   </div>
   <div class="vip-grid">
    <div><span>العملة المرشحة</span><strong id="vip-sym" style="color:var(--pri)">BTC/USDT</strong></div>
    <div><span>سعر الدخول</span><strong id="vip-entry" style="color:#f8fafc">مباشر</strong></div>
    <div><span>هدف 1 / هدف 2</span><strong id="vip-tp" style="color:var(--grn)">+1.9% / +3.5%</strong></div>
    <div><span>وقف الحماية</span><strong id="vip-sl" style="color:var(--red)">-1.05%</strong></div>
   </div>
   <div class="calc-bar">
    <span>🧮 لو دخلت بـ:</span>
    <div style="display:flex;gap:4px">
     <button class="cbtn" id="my-20" onclick="setMyBet(20)">20 ر.س</button>
     <button class="cbtn on" id="my-50" onclick="setMyBet(50)">50 ر.س</button>
     <button class="cbtn" id="my-100" onclick="setMyBet(100)">100 ر.س</button>
     <button class="cbtn" id="my-200" onclick="setMyBet(200)">200 ر.س</button>
    </div>
    <strong id="my-calc-res" style="color:#4ade80;font-size:10px;width:100%;margin-top:3px;text-align:center"></strong>
   </div>
  </div>

  <div class="chart-box">
   <div class="box-hd"><span>📈 منحنى أداء الامتحان النظيف</span><span class="sec-num" id="k-pro" style="color:#4ade80">بمحفظة ×10: +0.00 ر.س</span></div>
   <svg id="pnl-svg" viewBox="0 0 260 95" style="width:100%;height:95px;overflow:visible"></svg>
  </div>

  <div class="term">
   <div class="box-hd"><span>⚡ رادار باينانس الحي (عملات رقمية فقط)</span><span id="mood-bdg" style="color:var(--pri)">بث حي 🟢</span></div>
   <div class="term-body" id="term-list">جاري تحميل سجل الامتحان...</div>
  </div>

  <div class="risk-row">
   <span>🎚️ تشديد الفلتر:</span>
   <button class="rbtn" id="rk-low" onclick="setRisk('low')">🛡️ حذر (88+)</button>
   <button class="rbtn on" id="rk-medium" onclick="setRisk('medium')">🎯 متوازن (86+)</button>
   <button class="rbtn" id="rk-high" onclick="setRisk('high')">🔥 نشط (83+)</button>
  </div>

  <div class="chips" id="chips"></div>
  <div id="live-list"></div>
 </div>

 <div id="tab-lab" class="tab">
  <div class="obsidian-box">
   <div class="box-hd"><span style="color:#fbbf24">🧠 خريطة دماغ القائد v13.0 (البطلان فقط)</span><span style="color:var(--pri)">780+ عملة باينانس</span></div>
   <svg id="obsidian-svg" viewBox="0 0 280 150" style="width:100%;height:150px"></svg>
  </div>

  <div class="hero-lab">
   <span class="lbl" style="color:#e9d5ff">🧪 نتيجة الامتحان الصافية (بدون شوائب قديمة)</span>
   <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
    <div><span class="lbl">صافي ربح الامتحان</span><h2 class="big" id="lab-real-pnl">+0.00 ر.س</h2></div>
    <div style="text-align:left"><span class="lbl">يعادل بمحفظة 600 ر.س (×10)</span><strong style="font-size:18px;color:#4ade80" id="lab-real-10x">+0.00 ر.س</strong></div>
   </div>
   <div class="pockets" style="margin-top:9px;margin-bottom:0">
    <div class="pk"><h4>نسبة الفوز</h4><strong style="color:var(--grn)" id="lab-real-wr">0%</strong></div>
    <div class="pk"><h4>معامل الربح</h4><strong id="lab-real-pf">0.00</strong></div>
    <div class="pk"><h4>صفقات الامتحان</h4><strong id="lab-real-n">0 / 10</strong></div>
   </div>
  </div>

  <div class="sys"><span>🚫 النظريات المعزولة</span><span style="color:var(--red);font-size:10px" id="disabled-th">جدار الحيتان • خطف السيولة • زخم 1H • اختراق القمم</span></div>
  <div class="sys"><span>🚀 أعلى عملات باينانس سيولة الآن</span><span style="color:var(--pri);font-size:10px" id="radar-gems">جاري المسح...</span></div>
  <div id="theory-rank"></div>
 </div>

 <div id="tab-sys" class="tab">
  <div class="sys">
   <span>🔄 إعادة تصفير امتحان الـ 10 صفقات (60.00 ر.س)</span>
   <button class="btn" style="background:rgba(245,158,11,.2);color:#fbbf24;border-color:#f59e0b" onclick="resetExamNow()">تصفير وبدء امتحان جديد</button>
  </div>
  <div class="sys">
   <span>💰 الميزانية المتكيفة: <b id="cap-val" style="color:var(--grn)">60 ر.س</b></span>
   <div style="display:flex;gap:4px">
    <button class="btn" onclick="setCap(60)">60</button>
    <button class="btn" onclick="setCap(100)">100</button>
    <button class="btn" onclick="setCap(150)">150</button>
   </div>
  </div>
  <div id="qa-checks-list"></div>
  <div class="sys"><span>🔔 قناة إشعارات ntfy</span><span style="color:var(--grn)">smax_trader_vip_999</span></div>
  <div id="fav-tiers"></div>
  <div id="sysrows"></div>
 </div>
</div>

<nav>
 <button class="nv act" onclick="tab('live',this)">🏁<span>غرفة الامتحان</span></button>
 <button class="nv" onclick="tab('lab',this)">🧠<span>مقارنة البطلين</span></button>
 <button class="nv" onclick="tab('sys',this)">🛠️<span>الفاحص والتصفير</span></button>
</nav>

<script>
let D=null, flt='all', livePrices={}, liveTickCount=0;
let privMode = localStorage.getItem('priv_mode')==='1';
let myBetSar = parseFloat(localStorage.getItem('my_bet_sar_v13')||'50');
let liveVipSignal = null;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sg=n=>(n>0?'+':'')+Number(n).toFixed(2);
const col=n=>n>=0?'var(--grn)':'var(--red)';
function tab(n,b){document.querySelectorAll('.tab,.nv').forEach(e=>e.classList.remove('act'));$('tab-'+n).classList.add('act');b.classList.add('act');window.scrollTo(0,0)}

const BOTS=[
 {id:'DUSKA',color:'#10b981',pk:null,defStage:'🏁 قائد الامتحان'},
 {id:'BRAVA',color:'#f59e0b',pk:'reserve',defStage:'💎 أولوية أولى'},
 {id:'KEST8',color:'#f43f5e',pk:'scalp',defStage:'🎯 قيعان مشددة'},
 {id:'ORVEN',color:'#38bdf8',pk:'swing',defStage:'⏳ فزعة 93%+'},
 {id:'MIRAX',color:'#a855f7',pk:null,defStage:'🛡️ قفل +0.70'}
];

function setMyBet(amt){
 myBetSar = amt;
 localStorage.setItem('my_bet_sar_v13', String(amt));
 updateVipCardUI();
}

function updateVipCardUI(){
 [20,50,100,200].forEach(v=>{if($('my-'+v))$('my-'+v).className='cbtn'+(myBetSar===v?' on':'');});
 const sig = liveVipSignal || (D && D.live && D.live.vip_signal) || {symbol:'BTC-USD',score:94,entry:0,tp1_pct:1.9,tp2_pct:3.5,sl_pct:-1.05,status:'🟢 جاهز لقنص عملات باينانس'};
 const cleanSym = String(sig.symbol||'BTC-USD').replace('-USD','').replace(/[0-9]+/g,'');
 const curP = livePrices[cleanSym+'USDT'] || sig.entry || 0;
 $('vip-sym').innerText = cleanSym + ' / USDT';
 $('vip-score').innerText = `ضمان ${sig.score||94}%`;
 $('vip-status').innerText = sig.status || '🟢 منطقة شراء قاعية مناسبة';
 $('vip-entry').innerText = curP > 0 ? (curP < 1 ? curP.toFixed(4) : curP.toFixed(2)) + '$' : 'مباشر';
 const tp1 = Number(sig.tp1_pct||1.9), tp2 = Number(sig.tp2_pct||3.5), sl = Math.abs(Number(sig.sl_pct||1.05));
 $('vip-tp').innerText = `+${tp1.toFixed(1)}% / +${tp2.toFixed(1)}%`;
 $('vip-sl').innerText = `-${sl.toFixed(1)}%`;
 const feeSar = myBetSar * 0.0015;
 const net1 = (myBetSar * (tp1/100)) - feeSar;
 const net2 = (myBetSar * (tp2/100)) - feeSar;
 const riskSar = (myBetSar * (sl/100)) + feeSar;
 $('my-calc-res').innerText = `ربحك الصافي بـ ${myBetSar} ر.س (بعد عمولة BNB): +${net1.toFixed(2)} إلى +${net2.toFixed(2)} ر.س | الوقف: -${riskSar.toFixed(2)} ر.س`;
}

function applyPrivacy(){
 $('priv-btn').innerText = privMode ? '🔒 الأرقام مخفية' : '🔓 الأرقام ظاهرة';
 document.querySelectorAll('.sec-num').forEach(el=>{
  if(privMode) el.classList.add('blur-num');
  else el.classList.remove('blur-num');
 });
}
function togglePrivacy(){
 privMode = !privMode;
 localStorage.setItem('priv_mode', privMode?'1':'0');
 applyPrivacy();
}

function drawObsidianGraph(openTrades){
 const svg=$('obsidian-svg');if(!svg)return;
 const cx=140, cy=72;
 let lines='', nodes='';
 for(let i=0;i<36;i++){
  const ang=(i/36)*Math.PI*2;
  const r=52+(i%3)*6;
  const x=(cx+Math.cos(ang)*r).toFixed(1), y=(cy+Math.sin(ang)*r).toFixed(1);
  lines+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="rgba(56,189,248,0.14)" stroke-width="0.6"/>`;
  nodes+=`<circle cx="${x}" cy="${y}" r="2" fill="#38bdf8" opacity="0.7"/>`;
 }
 const coreNodes=(openTrades&&openTrades.length)?openTrades.slice(0,4):[{symbol:'BTC'},{symbol:'SOL'},{symbol:'ETH'},{symbol:'BNB'}];
 coreNodes.forEach((t,idx)=>{
  const ang=(idx/coreNodes.length)*Math.PI*2 - 0.4;
  const x=(cx+Math.cos(ang)*30).toFixed(1), y=(cy+Math.sin(ang)*30).toFixed(1);
  lines+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#f59e0b" stroke-width="1.3"/>`;
  nodes+=`<circle cx="${x}" cy="${y}" r="4.2" fill="#10b981"/><text x="${x}" y="${y-7}" fill="#f8fafc" font-size="6.5" text-anchor="middle">${esc(String(t.symbol||'').replace('-USD',''))}</text>`;
 });
 nodes+=`<circle cx="${cx}" cy="${cy}" r="11" fill="rgba(245,158,11,0.25)"/><circle cx="${cx}" cy="${cy}" r="6.5" fill="#f59e0b"/><text x="${cx}" y="142" fill="#fbbf24" font-size="8" font-weight="bold" text-anchor="middle">v13.0 • انفجار الحيتان 3x + القيعان المشددة (20 ر.س)</text>`;
 svg.innerHTML=lines+nodes;
}

function drawChart(curve,wallet,baseCap){
 const svg=$('pnl-svg');if(!svg)return;
 const pts=(curve&&curve.length>1)?curve:[0,wallet-baseCap];
 const min=Math.min(...pts,-0.4),max=Math.max(...pts,0.4),rng=Math.max(max-min,0.4);
 const W=240,H=82;
 const coords=pts.map((v,i)=>[10+(i/(pts.length-1))*W, H-8-((v-min)/rng)*(H-22)]);
 const path='M '+coords.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' L ');
 const area=path+` L ${coords[coords.length-1][0].toFixed(1)},${H} L 10,${H} Z`;
 const last=coords[coords.length-1];
 svg.innerHTML=`<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#10b981" stop-opacity="0.38"/><stop offset="100%" stop-color="#10b981" stop-opacity="0.0"/></linearGradient></defs>
 <path d="${area}" fill="url(#g)"/><path d="${path}" fill="none" stroke="#10b981" stroke-width="2.2"/>
 <circle cx="${last[0]}" cy="${last[1]}" r="3.5" fill="#34d399"/><text x="${Math.min(195,last[0]-10)}" y="${Math.max(12,last[1]-6)}" fill="#4ade80" font-size="9.5" font-weight="bold">${wallet.toFixed(2)} ر.س</text>`;
}

function cards(ts,empty){
 if(!ts||!ts.length)return '<div class="empty">'+empty+'</div>';
 const S={OPEN:'صفقة امتحان جارية (20 ر.س) ⏳',WON:'ناجحة ✅',LOST:'خاسرة 🛡️'};
 const P={reserve:'انفجار الحيتان 3x 💎',scalp:'قناص القيعان المشدد 🎯',swing:'خزان الفزعة 93%+ 🔥'};
 const closedLocal = JSON.parse(localStorage.getItem('closed_ids_v13')||'[]');
 return ts.filter(t=>!(t.status==='OPEN' && closedLocal.includes(t.id))).map(t=>{
  let p=Number(t.pnl_sar||0);
  let curPriceTxt = t.exit_price ? t.exit_price+'$' : 'مباشر';
  if(t.status==='OPEN'){
   const cleanSym=String(t.symbol||'').replace('-USD','').replace(/[0-9]+/g,'')+'USDT';
   if(livePrices[cleanSym] && t.entry_price>0){
    const lp=livePrices[cleanSym];
    curPriceTxt = lp.toFixed(4)+'$ ⚡';
    const ratio=(lp-t.entry_price)/t.entry_price;
    const fee = t.invested_sar * 0.0015;
    p = ratio>=0 ? Number(((t.invested_sar*ratio) - fee).toFixed(2)) : Math.max(-0.30, Number(((t.invested_sar*ratio) - fee).toFixed(2)));
   }
  }
  const pk=P[t.pocket]||'خزان باينانس';
  const closeBtn = t.status==='OPEN' ? `<button class="close-one-btn" onclick="closeSingleTrade(${t.id}, '${esc(t.symbol)}', ${p})">⚡ إغلاق هذه الصفقة الآن (${sg(p)} ر.س)</button>` : '';
  return `<div class="t ${t.status}"><div class="tt"><div><span class="sym">${esc(t.symbol)}</span><span class="as">${esc(t.asset_type)} • ${pk} • ضمان ${t.score||90}%</span></div><span class="bd ${t.status}">${S[t.status]||t.status}</span></div>
  <div class="m"><div><span>مبلغ الصفقة (${t.invested_sar} ر.س)</span><strong>${t.entry_price}$</strong></div><div><span>السعر الآن/الخروج</span><strong style="color:var(--pri)">${curPriceTxt}</strong></div><div><span>الصافي بعد BNB</span><strong style="color:${col(p)}">${sg(p)} ر.س</strong></div></div>
  <div class="note">💡 ${esc(t.reason)}</div><div class="les">📌 ${esc(t.lesson||'تحت رقابة المصعد التصاعدي وقفل السلة (+0.70 ر.س)...')}</div>${closeBtn}</div>`;
 }).join('')}

function render(){
 if(!D)return; const L=D.live,s=L.stats,c=D.cfg,qa=L.qa||{};
 const baseCap=parseFloat(localStorage.getItem('cap_override_v13') || L.active_capital || D.start || 60);
 const examTarget=L.exam_target||10;
 $('cap-val').innerText=baseCap.toFixed(0)+' ر.س';
 $('ver-bdg').innerText='v13.0 • امتحان 20 ر.س';
 if(qa.badge)$('qa-summary').innerText=qa.badge;

 const botPaused = localStorage.getItem('bot_paused_v13')==='1' || Boolean(L.paused);
 const runBtn = $('bot-run-btn');
 if(runBtn){
  runBtn.className = 'c-act-btn ' + (botPaused ? 'paused' : 'run');
  runBtn.innerText = L.exam_done ? '🏁 اكتمل الامتحان (10/10)' : (botPaused ? '⏸️ متوقف مؤقتاً (اضغط للتشغيل)' : '🟢 الامتحان يعمل (إيقاف مؤقت)');
 }

 const closedLocal = JSON.parse(localStorage.getItem('closed_ids_v13')||'[]');
 let liveFloating = L.floating||0;
 const openList = (L.trades||[]).filter(t=>t.status==='OPEN' && !closedLocal.includes(t.id));
 if(Object.keys(livePrices).length && openList.length){
  let sumFl=0;
  openList.forEach(t=>{
   const cleanSym=String(t.symbol||'').replace('-USD','').replace(/[0-9]+/g,'')+'USDT';
   if(livePrices[cleanSym] && t.entry_price>0){
    const ratio=(livePrices[cleanSym]-t.entry_price)/t.entry_price;
    const fee = t.invested_sar * 0.0015;
    sumFl += ratio>=0 ? ((t.invested_sar*ratio) - fee) : Math.max(-0.30, ((t.invested_sar*ratio) - fee));
   }else{sumFl += Number(t.pnl_sar||0);}
  });
  liveFloating = Number(sumFl.toFixed(2));
 } else if(!openList.length){
  liveFloating = 0;
 }

 const adjWallet = Number((baseCap + s.pnl + liveFloating).toFixed(2));
 const tot=s.pnl+liveFloating;
 $('w').innerText=adjWallet.toFixed(2)+' ر.س';
 $('pnl').innerText='الصافي: '+sg(tot)+' ر.س';$('pnl').style.color=tot>=0?'#4ade80':'#fda4af';
 $('pf-top').innerText=Number(s.pf||0).toFixed(2);
 $('best-th').innerText=s.best_theory||'انفجار الحيتان 3x 💎';
 $('k-pro').innerText=`بمحفظة ×10: ${sg(tot*10)} ر.س`;

 const cb = L.commander_brief || {};
 if(cb.done) $('br-done').innerText = cb.done;
 if(cb.watch) $('br-watch').innerText = cb.watch;
 if(cb.next) $('br-next').innerText = cb.next;

 $('dw-prog').innerText = `${s.n} / ${examTarget}`;
 $('dw-today').innerText = sg(tot) + ' ر.س';
 $('dw-today').style.color = col(tot);
 $('dw-elite').innerText = (s.win_rate || 0) + '%';

 updateVipCardUI();

 $('sb-w-cnt').innerText=`${s.won||0} (${s.win_rate||0}%)`;
 $('sb-w-sar').innerText=`+${(s.gross_win||0).toFixed(2)} ر.س`;
 $('sb-l-cnt').innerText=`${s.lost||0} (${s.loss_rate||0}%)`;
 $('sb-l-sar').innerText=`-${(s.gross_loss||0).toFixed(2)} ر.س`;
 $('sb-net-wr').innerText=`${sg(s.pnl||0)} ر.س`;
 $('sb-net-wr').style.color=col(s.pnl||0);
 $('sb-net-sar').innerText=`أفضل صفقة: +${(s.best_win||0).toFixed(2)} ر.س`;

 $('lab-real-pnl').innerText = sg(s.pnl||0) + ' ر.س';
 $('lab-real-10x').innerText = sg((s.pnl||0)*10) + ' ر.س';
 $('lab-real-wr').innerText = (s.win_rate||0) + '%';
 $('lab-real-pf').innerText = Number(s.pf||0).toFixed(2);
 $('lab-real-n').innerText = `${s.n} / ${examTarget}`;

 drawChart(s.curve, adjWallet, baseCap);
 drawObsidianGraph(openList);

 const th=D.thoughts||[];
 $('term-list').innerHTML=th.length?th.map(x=>`<div class="tline"><span class="tm">[${esc(x.time)}]</span><b>${esc(x.agent)}:</b> ${esc(x.message)}</div>`).join(''):'';

 const crew=c.crew_state||{}, pks=L.pockets||{};
 $('crew-bar').innerHTML=BOTS.map(b=>{
  const st=crew[b.id]||{role:'كتيبة',status:'working',bubble:'نشط',stage:b.defStage};
  const stageTxt = st.stage || b.defStage;
  const pkInfo=b.pk&&pks[b.pk]?`${sg(pks[b.pk].pnl||0)} ر.س`:'قائد';
  return `<div class="bot-card ${st.status}"><span class="stg-pill">${esc(stageTxt)}</span><div class="bub">${esc(st.bubble)}</div>
  <div class="ava" style="background:${b.color}22;border:1px solid ${b.color}"><i class="eye" style="background:${b.color}"></i><i class="eye" style="background:${b.color}"></i></div>
  <b class="bname">${b.id}</b><span class="brole">${esc(st.role)}</span><small style="font-size:8.5px;color:${b.color};font-weight:800">${pkInfo}</small></div>`;
 }).join('');

 const mult=(adjWallet/baseCap).toFixed(2);$('goal-pct').innerText=mult+'x';
 $('pg-t').innerText = `${s.n}/${examTarget}`;
 $('pg-b').style.width = Math.min(100, Math.max(4, (s.n/examTarget)*100)) + '%';

 const tk = L.tanks || {normal_alloc:40, normal_cash:40, boost_alloc:20, boost_cash:20};
 $('pockets-grid').innerHTML = `
  <div class="pk"><h4>خزان باينانس العادي 🎯</h4><strong style="color:#f8fafc">${Number(tk.normal_alloc).toFixed(0)} ر.س (20×2)</strong><small>متاح الآن: <b style="color:var(--grn)">${Number(tk.normal_cash).toFixed(1)} ر.س</b></small></div>
  <div class="pk res10"><h4 style="color:#fbbf24">خزان الفزعة 93%+ 🔥</h4><strong style="color:#fbbf24">${Number(tk.boost_alloc).toFixed(0)} ر.س (20×1)</strong><small>متاح للمضمون: <b style="color:var(--grn)">${Number(tk.boost_cash).toFixed(1)} ر.س</b></small></div>
  <div class="pk"><h4>ربح السلة المفتوحة 🧺</h4><strong style="color:${col(liveFloating)}">${sg(liveFloating)} ر.س</strong><small>يقفل جماعياً عند <b style="color:var(--grn)">+0.70</b></small></div>
 `;

 const curRisk=localStorage.getItem('risk_override_v13')||c.risk_mode||'medium';
 ['low','medium','high'].forEach(m=>$('rk-'+m).className='rbtn'+(curRisk===m?' on':''));

 const F={all:`الكل (${L.trades.length})`,OPEN:`جارية ⚡ (${openList.length})`,WON:`ناجحة ✅ (${s.won||0})`,LOST:`خاسرة 🛡️ (${s.lost||0})`};
 $('chips').innerHTML=Object.keys(F).map(k=>`<button class="chip ${flt===k?'on':''}" onclick="flt='${k}';render()">${F[k]}</button>`).join('');
 $('live-list').innerHTML=cards(L.trades.filter(t=>flt==='all'||t.status===flt),'بانتظار أول فرصة مضمونة في امتحان الـ 10 صفقات...');

 const disList=qa.disabled_theories||c.disabled_theories||[];
 $('disabled-th').innerText=disList.join(' • ');

 const ths=s.theories||{};
 $('theory-rank').innerHTML=Object.keys(ths).length?Object.entries(ths).map(([k,v])=>{
  return `<div class="sys"><span>⚡ ${esc(k)}</span><span style="color:${col(v.pnl)}">فوز ${v.w} | خسارة ${v.l} | ${sg(v.pnl)} ر.س</span></div>`;
 }).join(''):'<div class="empty">سيظهر أداء انفجار الحيتان 3x وقناص القيعان هنا بمجرد إغلاق أول صفقة في الامتحان.</div>';

 const checks=qa.checks||[];
 $('qa-checks-list').innerHTML=checks.map(ch=>`<div class="sys"><div><strong style="display:block;color:var(--pri)">🛠️ ${esc(ch.name)}</strong><small style="color:var(--mut);font-size:10px">${esc(ch.detail)}</small></div><span style="color:var(--grn);white-space:nowrap">${esc(ch.status)}</span></div>`).join('');

 const fv=D.favorites||{royal:[]};
 $('fav-tiers').innerHTML=`<div class="sys"><span>👑 النخبة الملكية</span><span style="color:var(--grn)">${fv.royal.map(x=>x.symbol).join(' • ')||'BTC • SOL • ETH'}</span></div>`;
 $('sysrows').innerHTML=`<div class="sys"><span>🕒 آخر مزامنة سحابية</span><span>${D.last_scan||'—'}</span></div>`;
 applyPrivacy();
}

async function resetExamNow(){
 if(!confirm('🏁 هل تريد تصفير الرصيد إلى 60.00 ر.س وبدء امتحان 10 صفقات جديد؟'))return;
 localStorage.removeItem('bot_paused_v13');
 localStorage.removeItem('closed_ids_v13');
 try{await fetch('/api/reset_exam')}catch(e){}
 load(true);
}

async function closeSingleTrade(id, sym, pnlVal){
 if(!confirm(`⚡ هل تريد إغلاق صفقة ${sym} الآن على (${sg(pnlVal)} ر.س)؟`))return;
 const arr = JSON.parse(localStorage.getItem('closed_ids_v13')||'[]');
 if(!arr.includes(id)) arr.push(id);
 localStorage.setItem('closed_ids_v13', JSON.stringify(arr));
 try{await fetch(`/api/close_trade?id=${id}&pnl=${pnlVal}`)}catch(e){}
 render();
}

async function toggleBotRun(){
 const cur = localStorage.getItem('bot_paused_v13')==='1';
 const next = !cur;
 localStorage.setItem('bot_paused_v13', next?'1':'0');
 try{await fetch('/api/pause?paused='+(next?1:0))}catch(e){}
 render();
}

async function liveBinanceTick(manual=false){
 try{
  const r=await fetch('https://data-api.binance.vision/api/v3/ticker/24hr');
  if(r.ok){
   const arr=await r.json();
   const gems=[];
   let bestPullback = null;
   const badSet=new Set(['USDC','FDUSD','TUSD','BUSD','DAI','USDT','WBTC','PAXG','USD1','USDE','GRAM','PEPE']);
   arr.forEach(x=>{
    if(x.symbol && x.symbol.endsWith('USDT')){
     const lp = parseFloat(x.lastPrice);
     livePrices[x.symbol]=lp;
     const sym=x.symbol.slice(0,-4);
     const chg=parseFloat(x.priceChangePercent||0), vol=parseFloat(x.quoteVolume||0);
     const highP=parseFloat(x.highPrice||lp), lowP=parseFloat(x.lowPrice||lp);
     if(/^[A-Z]{2,5}$/.test(sym) && !sym.endsWith('B') && !badSet.has(sym) && vol>25000000){
      if(chg>=1.5 && chg<=11 && gems.length<5) gems.push(`${sym} (+${chg.toFixed(0)}%)`);
      const posInRange = highP>lowP ? (lp-lowP)/(highP-lowP) : 0.5;
      if(vol>60000000 && posInRange>=0.12 && posInRange<=0.48 && chg>=-3.5 && chg<=5.5){
       if(!bestPullback || vol > bestPullback.vol){
        bestPullback = {symbol:sym+'-USD', entry:lp, vol:vol, score:94, tp1_pct:1.9, tp2_pct:3.5, sl_pct:-1.05, status:`🟢 منطقة دخول مباشر (${sym}) — سيولة عالية`};
       }
      }
     }
    }
   });
   if(bestPullback) liveVipSignal = bestPullback;
   liveTickCount++;
   const nowTime=new Date().toLocaleTimeString('ar-SA',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
   $('hb-status').innerText=`⚡ بث مباشر (${nowTime})`;
   $('sub').innerText=`بث باينانس (${nowTime}) • امتحان 20 ر.س • نبضة #${liveTickCount}`;
   if(gems.length && $('radar-gems')) $('radar-gems').innerText=gems.join(' • ');
   render();
  }
 }catch(e){}
 if(manual) load(true);
}

async function emergencyKill(){
 if(!confirm('🛑 هل تريد إغلاق جميع الصفقات المفتوحة الآن؟'))return;
 try{await fetch('/api/kill_switch')}catch(e){}
 load(true);
}

async function setCap(next){
 localStorage.setItem('cap_override_v13',String(next));
 try{await fetch('/api/capital?amount='+next)}catch(e){}
 render();
}

async function setRisk(m){
 localStorage.setItem('risk_override_v13',m);
 try{await fetch('/api/risk?mode='+m)}catch(e){}
 render();
}

async function load(manual=false){
 try{
  if(manual){try{await fetch('/api/scan')}catch(e){}}
  let r=await fetch('./data.json?t='+Date.now(), {cache:'no-store'});
  if(!r.ok) r=await fetch('/api/data?t='+Date.now(), {cache:'no-store'});
  D=await r.json();
  render();
 }catch(e){}
}
updateVipCardUI();
load();
setTimeout(()=>liveBinanceTick(false), 800);
setInterval(()=>liveBinanceTick(false), 15000);
setInterval(load, 30000);
</script></body></html>
'''

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return PAGE
