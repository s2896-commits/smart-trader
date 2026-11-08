from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import threading, time, os, requests
import database as db
import bot_engine as bot

SELF_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://smart-trader-wo7s.onrender.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
state = {"last_scan": None, "error": None}

class ChatInput(BaseModel):
    message: str

def worker():
    last_ping = 0
    while True:
        try:
            bot.analyze_and_trade()
            state.update(last_scan=db.fmt(db.now()), error=None)
            db.backup_if_dirty()
        except Exception as e:
            state["error"] = str(e)[:120]
        if time.time() - last_ping > 240:
            try:
                requests.get(f"{SELF_URL}/api/ping", timeout=10)
            except Exception:
                pass
            last_ping = time.time()
        time.sleep(120)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker, daemon=True).start()
    yield
    db.backup_if_dirty(force=True)

app = FastAPI(lifespan=lifespan)

def guard(key):
    if ADMIN_KEY and key != ADMIN_KEY:
        raise HTTPException(401, "bad key")

@app.get("/api/ping")
def ping():
    return {"alive": True}

@app.get("/api/scan")
def scan(bg: BackgroundTasks, key: str = ""):
    guard(key)
    bg.add_task(bot.analyze_and_trade)
    return {"ok": True}

@app.get("/api/backtest")
def backtest(bg: BackgroundTasks, key: str = ""):
    guard(key)
    bg.add_task(bot.run_backtest)
    return {"ok": True}

@app.get("/api/pause")
def pause(key: str = ""):
    guard(key)
    cfg = db.get_ai_config()
    cfg["paused"] = not cfg["paused"]
    db.save_ai_config(cfg)
    return {"paused": cfg["paused"]}

@app.post("/api/chat")
def chat_endpoint(body: ChatInput):
    reply = db.ask_bot_chat(body.message)
    return {"reply": reply, "history": db.get_chat_history()}

@app.get("/api/data")
def data():
    s = db.get_summary()
    return {
        "cloud_ok": db.is_cloud_connected(),
        "cfg": db.get_ai_config(),
        "markets": bot.market_status(),
        "last_scan": state["last_scan"],
        "error": state["error"],
        "start": db.START_CAPITAL,
        "fee": db.FEE_PCT,
        "thoughts": db.get_thoughts(14),
        "favorites": db.get_favorites_grouped(),
        "chat": db.get_chat_history(25),
        "live": {**s, "trades": db.get_trades(0, 60)},
        "lab": db.get_lab(),
    }

PAGE = '''<!DOCTYPE html>
<html dir="rtl" lang="ar"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#050811">
<title>SM-A-X AI Sniper Pro</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#050811;--surface:#0b1120;--card:#111a2e;--line:rgba(255,255,255,.08);--pri:#38bdf8;--pur:#a855f7;
--grn:#10b981;--red:#f43f5e;--amb:#f59e0b;--txt:#f8fafc;--mut:#94a3b8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:'Tajawal',sans-serif;background:var(--bg);color:var(--txt);margin:0;
padding:calc(10px + env(safe-area-inset-top)) 12px calc(92px + env(safe-area-inset-bottom))}
.shell{max-width:540px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:center;padding:6px 2px 12px}
.brand{display:flex;gap:10px;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;background:var(--grn);box-shadow:0 0 10px var(--grn)}
.dot.off{background:var(--amb);box-shadow:0 0 10px var(--amb)}
h1{font-size:17px;font-weight:900;margin:0}.sub{font-size:11px;color:var(--mut)}
button{font-family:inherit;cursor:pointer}
.btn{background:rgba(56,189,248,.14);color:var(--pri);border:1px solid rgba(56,189,248,.35);padding:8px 13px;border-radius:12px;font-size:12px;font-weight:700}
.btn:disabled{opacity:.5}
.warn{background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.4);color:#fcd34d;border-radius:12px;padding:9px 12px;font-size:12px;margin-bottom:10px}
.top-cards{display:grid;grid-template-columns:1.2fr 1fr;gap:8px;margin-bottom:10px}
.tcard{background:linear-gradient(135deg,#0f172a,#1e1b4b);border:1px solid rgba(56,189,248,.25);border-radius:18px;padding:13px}
.tcard.vault{background:linear-gradient(135deg,#064e3b,#0f172a);border-color:rgba(16,185,129,.35)}
.lbl{font-size:11px;color:rgba(255,255,255,.72);display:block;margin-bottom:3px}
.big{font-size:23px;font-weight:900;margin:0}
.term{background:#03060c;border:1px solid rgba(16,185,129,.35);border-radius:16px;padding:11px 13px;margin-bottom:12px;box-shadow:inset 0 0 18px rgba(16,185,129,.05)}
.term-head{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,255,255,.07);padding-bottom:6px;margin-bottom:7px;font-size:12px;font-weight:800;color:var(--grn)}
.term-body{max-height:135px;overflow-y:auto;font-size:11.5px;line-height:1.65}
.tline{margin-bottom:3px;color:#cbd5e1}.tline b{color:var(--pri)}.tline .tm{color:#64748b;font-size:10px;margin-left:5px}
.pockets{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:12px}
.pk{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 8px;text-align:center}
.pk h4{margin:0 0 3px;font-size:11.5px;color:var(--pri)}.pk strong{font-size:14px;display:block}
.pk small{font-size:10px;color:var(--mut);display:block;margin-top:2px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 12px}
.kpi span{font-size:11px;color:var(--mut);display:block}.kpi strong{font-size:17px;font-weight:900}.kpi small{font-size:10px;color:var(--mut);display:block}
.prog{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 13px;margin-bottom:12px;font-size:12px}
.row{display:flex;justify-content:space-between;align-items:center}
.bar{height:7px;background:var(--surface);border-radius:6px;margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pri),var(--grn));border-radius:6px}
.chips{display:flex;gap:6px;margin:4px 0 10px;overflow-x:auto}
.chip{background:var(--card);border:1px solid var(--line);color:var(--mut);padding:6px 13px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap}
.chip.on{color:var(--pri);border-color:rgba(56,189,248,.5);background:rgba(56,189,248,.1)}
.sec{font-size:13px;font-weight:800;color:var(--mut);margin:12px 4px 8px;display:flex;justify-content:space-between}
.t{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:13px;margin-bottom:9px}
.t.OPEN{border-color:rgba(245,158,11,.35)}
.tt{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.sym{font-size:15px;font-weight:900}.as{font-size:11px;color:var(--mut);display:block}
.bd{font-size:11px;font-weight:800;padding:3px 9px;border-radius:8px}
.bd.OPEN{background:rgba(245,158,11,.15);color:var(--amb)}.bd.WON{background:rgba(16,185,129,.15);color:var(--grn)}.bd.LOST{background:rgba(244,63,94,.15);color:var(--red)}
.m{display:grid;grid-template-columns:repeat(3,1fr);background:var(--surface);padding:8px;border-radius:11px;text-align:center;margin-bottom:7px}
.m span{font-size:10px;color:var(--mut);display:block}.m strong{font-size:12.5px}
.note{font-size:11.5px;color:#cbd5e1;background:rgba(255,255,255,.03);padding:6px 9px;border-radius:8px;margin-bottom:4px;border-right:3px solid var(--pri)}
.les{font-size:11px;color:var(--mut);padding:2px 9px;border-right:3px solid #475569}
.empty{text-align:center;padding:28px 14px;color:var(--mut);background:var(--card);border-radius:16px;font-size:12.5px}
.sys{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--card);padding:12px 14px;border-radius:14px;margin-bottom:8px;border:1px solid var(--line);font-size:12.5px;font-weight:700}
.on{color:var(--grn)}.offc{color:var(--mut)}
.hero-lab{background:linear-gradient(135deg,#581c87,#1e1b4b);border-radius:20px;padding:16px;margin-bottom:12px;border:1px solid rgba(168,85,247,.35)}
.labbtn{width:100%;background:#fff;color:#4c1d95;border:0;padding:11px;border-radius:12px;font-size:12.5px;font-weight:900;margin-top:10px}
.chat-box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:12px;height:340px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.msg{max-width:85%;padding:9px 12px;border-radius:14px;font-size:12.5px;line-height:1.55;white-space:pre-line}
.msg.user{align-self:flex-start;background:rgba(56,189,248,.18);border:1px solid rgba(56,189,248,.35);color:#fff}
.msg.bot{align-self:flex-end;background:var(--surface);border:1px solid var(--line);color:#e2e8f0}
.chat-inp{display:flex;gap:7px}
.chat-inp input{flex:1;background:var(--card);border:1px solid var(--line);color:#fff;padding:11px 13px;border-radius:12px;font-family:inherit;font-size:13px}
nav{position:fixed;bottom:0;left:0;right:0;background:rgba(11,17,32,.95);backdrop-filter:blur(16px);border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:7px 6px calc(10px + env(safe-area-inset-bottom));z-index:9}
.nv{background:none;border:0;color:var(--mut);font-size:11px;font-weight:700;display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 12px;border-radius:12px}
.nv.act{color:var(--pri);background:rgba(56,189,248,.12)}
.tab{display:none}.tab.act{display:block}
</style></head><body>
<div class="shell">
 <div class="head">
  <div class="brand"><div class="dot" id="dot"></div><div><h1>قناص التداول الذكي • SM-A-X</h1><span class="sub" id="sub">جاري التحميل...</span></div></div>
  <button class="btn" id="scanBtn" onclick="scanNow()">⚡ فحص الآن</button>
 </div>
 <div id="warns"></div>

 <div id="tab-live" class="tab act">
  <div class="top-cards">
   <div class="tcard"><span class="lbl">رصيد المحفظة الحية</span><h2 class="big" id="w">—</h2><small id="pnl" style="font-weight:800">—</small></div>
   <div class="tcard vault"><span class="lbl">خزنة السحب الشخصي 💰</span><h2 class="big" id="vault" style="color:#34d399">—</h2><small id="split-rem" style="color:#a7f3d0;font-size:10px">—</small></div>
  </div>

  <div class="term">
   <div class="term-head"><span>🧠 شاشة التفكير الحية | المساعدون الأربعة</span><span id="mood-bdg" style="font-size:11px;color:var(--pri)">—</span></div>
   <div class="term-body" id="term-list">...</div>
  </div>

  <div class="pockets" id="pockets-grid"></div>

  <div class="kpis">
   <div class="kpi"><span>نسبة النجاح</span><strong id="k-wr">—</strong><small id="k-n"></small></div>
   <div class="kpi"><span>تقييم البوت اليومي</span><strong id="k-score" style="color:var(--grn)">—</strong><small>التزام وانضباط المخاطر</small></div>
   <div class="kpi"><span id="k-scale-lbl">أداء المرحلة القادمة (×10)</span><strong id="k-pro">—</strong><small>مقياس التدرج الواقعي</small></div>
   <div class="kpi"><span>أكبر تراجع</span><strong id="k-dd">—</strong><small>أقصى انخفاض من القمة</small></div>
  </div>

  <div class="prog"><div class="row"><span>تقدم إثبات الكفاءة (50 صفقة حية)</span><b id="pg-t">0 / 50</b></div><div class="bar"><i id="pg-b" style="width:0"></i></div></div>
  <div class="chips" id="chips"></div>
  <div id="live-list"></div>
 </div>

 <div id="tab-chat" class="tab">
  <div class="sec"><span>💬 تحدث مع البوت أو أعطه أوامر مباشرة</span></div>
  <div class="chips">
   <button class="chip on" onclick="quickAsk('كم معي وملخص الجيوب؟')">📊 ملخص المحفظة</button>
   <button class="chip on" onclick="quickAsk('وش عملات النخبة المفضلة؟')">🏆 عملات النخبة</button>
   <button class="chip on" onclick="quickAsk('وش حالة الأخبار والسوق؟')">📰 حالة الأخبار</button>
   <button class="chip on" onclick="quickAsk('فعل أو ألغ وضع المراقب')">🎯 وضع المراقب</button>
  </div>
  <div class="chat-box" id="chat-box"></div>
  <div class="chat-inp">
   <input id="chat-in" placeholder="اسأل البوت (مثلاً: كم معي؟ أو وقف جيب السريع)..." onkeydown="if(event.key==='Enter')sendChat()">
   <button class="btn" onclick="sendChat()">إرسال</button>
  </div>
 </div>

 <div id="tab-lab" class="tab">
  <div class="hero-lab">
   <span class="lbl">معمل التدرج الواقعي (قاعدة ×10) ودوري الاستراتيجيات</span>
   <div class="row" style="margin-top:6px">
    <div><span class="lbl">صافي محاكاة 60 ر.س</span><h2 class="big" id="h-pnl">—</h2></div>
    <div style="text-align:left"><span class="lbl" id="h-scale-lbl">يعادل بمحفظة 600 ر.س (×10)</span><strong style="font-size:20px;color:#4ade80" id="h-pro">—</strong></div>
   </div>
   <div class="pockets" style="margin-top:10px;margin-bottom:0">
    <div class="pk"><h4>نسبة النجاح</h4><strong id="h-wr">—</strong></div>
    <div class="pk"><h4>معامل الربح</h4><strong id="h-pf">—</strong></div>
    <div class="pk"><h4>الصفقات</h4><strong id="h-n">0</strong></div>
   </div>
   <button class="labbtn" id="btBtn" onclick="runBt()">🔬 تشغيل دوري الاستراتيجيات وتحديث النخبة</button>
  </div>
  <div id="lab-list"></div>
 </div>

 <div id="tab-sys" class="tab">
  <div class="sec"><span>🏆 دوري العملات المفضلة (الدرجات الثلاث)</span></div>
  <div id="fav-tiers"></div>
  <div class="sec"><span>الأسواق الآن</span></div><div id="mk"></div>
  <div class="sec"><span>إعدادات المساعدين الأربعة</span></div><div id="cfg"></div>
  <div class="sec"><span>النظام</span></div><div id="sysrows"></div>
  <button class="btn" style="width:100%;padding:12px" id="pauseBtn" onclick="pauseToggle()">—</button>
 </div>
</div>

<nav>
 <button class="nv act" onclick="tab('live',this)">💼<span>المحفظة</span></button>
 <button class="nv" onclick="tab('chat',this)">💬<span>شات البوت</span></button>
 <button class="nv" onclick="tab('lab',this)">🧪<span>المختبر ×10</span></button>
 <button class="nv" onclick="tab('sys',this)">📡<span>النخبة والنظام</span></button>
</nav>

<script>
let D=null, flt='all';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sg=n=>(n>0?'+':'')+Number(n).toFixed(2);
const col=n=>n>=0?'var(--grn)':'var(--red)';
function tab(n,b){document.querySelectorAll('.tab,.nv').forEach(e=>e.classList.remove('act'));$('tab-'+n).classList.add('act');b.classList.add('act')}

function cards(ts,empty){
 if(!ts||!ts.length)return '<div class="empty">'+empty+'</div>';
 const S={OPEN:'جارية ⏳',WON:'رابحة ✅',LOST:'خاسرة 🛡️'};
 const P={scalp:'جيب السريع ⚡',swing:'جيب الموجات 🌊',reserve:'قناص الاحتياط 🎯'};
 return ts.map(t=>{const c=t.symbol.endsWith('.SR')?' ر.س':'$',p=t.pnl_sar||0,pk=P[t.pocket]||'جيب السريع';
 return `<div class="t ${t.status}"><div class="tt"><div><span class="sym">${esc(t.symbol)}</span><span class="as">${esc(t.asset_type)} • ${pk} • ${esc(t.entry_time)}</span></div><span class="bd ${t.status}">${S[t.status]||t.status}</span></div>
 <div class="m"><div><span>الدخول (${t.invested_sar} ر.س)</span><strong>${t.entry_price}${c}</strong></div><div><span>الخروج</span><strong>${t.exit_price?t.exit_price+c:'مباشر'}</strong></div><div><span>الصافي</span><strong style="color:${col(p)}">${sg(p)} ر.س</strong></div></div>
 <div class="note">💡 ${esc(t.reason)}</div><div class="les">📌 ${esc(t.lesson||'المساعدون يراقبون السعر ويتتبعون القمة...')}</div></div>`}).join('')}

function render(){
 if(!D)return; const L=D.live,s=L.stats,c=D.cfg,lab=D.lab;
 $('w').innerText=L.wallet.toFixed(2)+' ر.س';
 const tot=L.wallet-D.start;$('pnl').innerText='الصافي: '+sg(tot)+' ر.س';$('pnl').style.color=tot>=0?'#4ade80':'#fda4af';
 $('vault').innerText=(L.personal_vault||0).toFixed(2)+' ر.س';
 $('split-rem').innerText='باقي '+(L.next_split_remaining||10).toFixed(2)+' ر.س لتقسيمة الربح القادمة';
 $('mood-bdg').innerText=c.market_mood||'مستقر 🟢';

 const th=D.thoughts||[];
 $('term-list').innerHTML=th.length?th.map(x=>`<div class="tline"><span class="tm">[${esc(x.time)}]</span><b>${esc(x.agent)}:</b> ${esc(x.message)}</div>`).join(''):'<div class="tline"><b>النظام:</b> المساعدون الأربعة في وضع الاستعداد...</div>';

 const pks=L.pockets||{};
 $('pockets-grid').innerHTML=['scalp','swing','reserve'].map(k=>{
  const p=pks[k]||{name:k,allocated:0,cash:0,invested:0};
  return `<div class="pk"><h4>${esc(p.name)}</h4><strong>${Number(p.cash).toFixed(1)} ر.س</strong><small>مخصص: ${Number(p.allocated).toFixed(1)} | مستثمر: ${Number(p.invested).toFixed(1)}</small></div>`;
 }).join('');

 $('k-wr').innerText=s.win_rate==null?'—':s.win_rate+'%';$('k-n').innerText=s.n+' صفقة مغلقة';
 $('k-score').innerText=(c.daily_score||95)+' / 100';
 const scCap=s.scaled_capital||600;
 $('k-scale-lbl').innerText=`أداء المرحلة القادمة (${scCap} ر.س)`;
 $('k-pro').innerText=sg(s.scaled_pnl||0)+' ر.س';$('k-pro').style.color=col(s.scaled_pnl||0);
 $('k-dd').innerText=s.max_dd.toFixed(2)+' ر.س';

 const g=Math.min(s.n,50);$('pg-t').innerText=s.n+' / 50';$('pg-b').style.width=(g/50*100)+'%';
 const F={all:'الكل',OPEN:'جارية',WON:'رابحة',LOST:'خاسرة'};
 $('chips').innerHTML=Object.keys(F).map(k=>`<button class="chip ${flt===k?'on':''}" onclick="flt='${k}';render()">${F[k]}</button>`).join('');
 $('live-list').innerHTML=cards(L.trades.filter(t=>flt==='all'||t.status===flt),'المساعدون الأربعة يمسحون السوق كل دقيقتين بنظام الـ 100 نقطة.');

 const ch=D.chat||[];
 $('chat-box').innerHTML=ch.length?ch.map(m=>`<div class="msg ${m.sender==='user'?'user':'bot'}">${esc(m.message)}</div>`).join(''):'<div class="msg bot">أهلاً يا صالح! أنا جاهز للرد على استفساراتك عن المحفظة والجيوب الثلاثة أو تنفيذ أوامرك مباشرة.</div>';

 $('h-wr').innerText=lab.win_rate==null?'—':lab.win_rate+'%';
 $('h-pnl').innerText=sg(lab.pnl)+' ر.س';
 $('h-scale-lbl').innerText=`يعادل بمحفظة ${lab.scaled_capital||600} ر.س (×10)`;
 $('h-pro').innerText=sg(lab.scaled_pnl||0)+' ر.س';
 $('h-n').innerText=lab.n;$('h-pf').innerText=lab.pf==null?'—':lab.pf;
 $('lab-list').innerHTML=cards(lab.trades,'اضغط الزر الأبيض بالأعلى لتشغيل دوري الاستراتيجيات.');

 const fv=D.favorites||{royal:[],testing:[],trend:[]};
 const row=(a,b,on)=>`<div class="sys"><span>${a}</span><span class="${on?'on':'offc'}">${b}</span></div>`;
 $('fav-tiers').innerHTML=
  row('👑 النخبة الملكية',fv.royal.map(x=>x.symbol).join(' • ')||'تتحدد مع الأرباح',1)+
  row('⏳ تحت الاختبار (5+ اختيارات)',fv.testing.map(x=>x.symbol).join(' • ')||'لا يوجد حالياً',1)+
  row('🔥 هبّة وترند سريع',fv.trend.map(x=>x.symbol).join(' • ')||'لا يوجد حالياً',1);

 const m=D.markets;
 $('mk').innerHTML=row('₿ العملات الرقمية (التركيز الحالي)','مفتوح 24/7',1)+row('🇸🇦 تاسي (تدريب خلفي)',m.tasi?'مفتوح':'مغلق',m.tasi)+row('🇺🇸 الأمريكي (تدريب خلفي)',m.us?'مفتوح':'مغلق',m.us);
 $('cfg').innerHTML=row('🛡️ وضع الطوارئ',c.observer_mode?'المراقب والقناص (92+ نقطة) 🎯':'تداول طبيعي (76+ نقطة) ✅',!c.observer_mode)+row('🎯 نطاق RSI المعتمد',c.rsi_min+' – '+c.rsi_max,1)+row('🔬 سيناريوهات مفحوصة',(c.scenarios_tested||0).toLocaleString()+' شمعة',1);
 $('sysrows').innerHTML=row('☁️ نسخ GitHub',D.cloud_ok?'مربوط 🟢':'غير مفعّل 🔴',D.cloud_ok)+row('🕒 آخر فحص',D.last_scan||'—',!!D.last_scan);
 $('pauseBtn').innerText=c.paused?'▶️ استئناف الدخول بصفقات جديدة':'⏸️ إيقاف الدخول بصفقات جديدة';
 let w='';if(!D.cloud_ok)w+='<div class="warn">⚠️ النسخ السحابي غير مفعّل: أضف GITHUB_TOKEN في Render.</div>';
 if(D.error)w+='<div class="warn">⚠️ تنبيه: '+esc(D.error)+'</div>';
 $('warns').innerHTML=w;$('dot').className='dot'+(c.paused?' off':'');
 $('sub').innerText='آخر فحص: '+(D.last_scan||'—');
}

async function load(){try{D=await (await fetch('/api/data')).json();render()}catch(e){$('sub').innerText='تعذر الاتصال بالسيرفر'}}
async function act(path){
 const go=k=>fetch(path+(path.includes('?')?'&':'?')+'key='+encodeURIComponent(k));
 let k=localStorage.getItem('k')||'',r=await go(k);
 if(r.status===401){k=prompt('مفتاح الإدارة (ADMIN_KEY)');if(!k)return null;localStorage.setItem('k',k);r=await go(k);if(r.status===401){localStorage.removeItem('k');return null}}
 return r}
async function scanNow(){const b=$('scanBtn');b.disabled=true;b.innerText='⏳ جاري الفحص';await act('/api/scan');setTimeout(async()=>{await load();b.disabled=false;b.innerText='⚡ فحص الآن'},6000)}
async function runBt(){const b=$('btBtn');b.disabled=true;b.innerText='⏳ يجري فحص التاريخ وتحديث الدرجات...';await act('/api/backtest');setTimeout(async()=>{await load();b.disabled=false;b.innerText='🔬 تشغيل دوري الاستراتيجيات وتحديث النخبة'},40000)}
async function pauseToggle(){await act('/api/pause');await load()}
async function sendChat(){
 const inp=$('chat-in'),msg=inp.value.trim();if(!msg)return;inp.value='';
 await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
 await load();const box=$('chat-box');box.scrollTop=box.scrollHeight;
}
async function quickAsk(q){$('chat-in').value=q;await sendChat()}
load();setInterval(load,25000);
</script></body></html>
'''

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return PAGE
