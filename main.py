from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
import threading, time, os, requests
import database as db
import bot_engine as bot

SELF_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://smart-trader-wo7s.onrender.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")  # اختياري: يحمي الأزرار (فحص/مختبر/إيقاف)
state = {"last_scan": None, "error": None}


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


@app.get("/api/data")
def data():
    s = db.get_summary()
    return {"cloud_ok": db.is_cloud_connected(), "cfg": db.get_ai_config(),
            "markets": bot.market_status(), "last_scan": state["last_scan"],
            "error": state["error"], "start": db.START_CAPITAL, "fee": db.FEE_PCT,
            "live": {**s, "trades": db.get_trades(0, 60)}, "lab": db.get_lab()}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return PAGE


PAGE = '''<!DOCTYPE html>
<html dir="rtl" lang="ar"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#060911">
<title>SM-A-X Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#060911;--surface:#0f172a;--card:#151f38;--line:rgba(255,255,255,.07);--pri:#38bdf8;--pur:#a855f7;
--grn:#10b981;--red:#f43f5e;--amb:#f59e0b;--txt:#f8fafc;--mut:#94a3b8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:'Tajawal',sans-serif;background:var(--bg);color:var(--txt);margin:0;
padding:calc(12px + env(safe-area-inset-top)) 14px calc(92px + env(safe-area-inset-bottom))}
.shell{max-width:520px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:center;padding:6px 2px 12px}
.brand{display:flex;gap:10px;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;background:var(--grn);box-shadow:0 0 10px var(--grn)}
.dot.off{background:var(--amb);box-shadow:0 0 10px var(--amb)}
h1{font-size:18px;font-weight:900;margin:0}.sub{font-size:11px;color:var(--mut)}
button{font-family:inherit}
.btn{background:rgba(56,189,248,.12);color:var(--pri);border:1px solid rgba(56,189,248,.3);padding:8px 14px;border-radius:12px;font-size:12px;font-weight:700}
.btn:disabled{opacity:.5}
.warn{background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.4);color:#fcd34d;border-radius:12px;padding:9px 12px;font-size:12px;margin-bottom:10px}
.ai{background:linear-gradient(135deg,rgba(16,185,129,.12),rgba(56,189,248,.08));border:1px solid rgba(16,185,129,.35);border-radius:16px;padding:11px 14px;margin-bottom:12px;font-size:12px;line-height:1.6}
.ai b{color:var(--grn);display:block;font-size:13px;margin-bottom:2px}
.hero{background:linear-gradient(135deg,#0284c7,#1e1b4b);border-radius:22px;padding:18px;margin-bottom:12px;border:1px solid rgba(255,255,255,.12)}
.hero.lab{background:linear-gradient(135deg,#6d28d9,#1e1b4b);border-color:rgba(168,85,247,.3)}
.row{display:flex;justify-content:space-between;align-items:flex-start}
.lbl{font-size:12px;color:rgba(255,255,255,.75);display:block;margin-bottom:3px}
.big{font-size:30px;font-weight:900;margin:0}
.pill{background:rgba(0,0,0,.3);padding:5px 12px;border-radius:20px;font-size:13px;font-weight:800}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;background:rgba(0,0,0,.25);padding:11px;border-radius:14px;text-align:center;margin-top:10px}
.grid3 span,.kpi span{font-size:11px;color:var(--mut);display:block}.grid3 strong{font-size:14px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 13px}
.kpi strong{font-size:18px;font-weight:900}.kpi small{font-size:10px;color:var(--mut)}
.prog{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 13px;margin-bottom:12px;font-size:12px}
.bar{height:7px;background:var(--surface);border-radius:6px;margin-top:7px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pri),var(--grn));border-radius:6px}
.chips{display:flex;gap:6px;margin:4px 0 10px;overflow-x:auto}
.chip{background:var(--card);border:1px solid var(--line);color:var(--mut);padding:6px 13px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap}
.chip.on{color:var(--pri);border-color:rgba(56,189,248,.5);background:rgba(56,189,248,.1)}
.sec{font-size:14px;font-weight:800;color:var(--mut);margin:12px 4px 8px;display:flex;justify-content:space-between}
.t{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px;margin-bottom:10px}
.t.OPEN{border-color:rgba(245,158,11,.35)}
.tt{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.sym{font-size:16px;font-weight:900}.as{font-size:11px;color:var(--mut);display:block}
.bd{font-size:11px;font-weight:800;padding:4px 10px;border-radius:8px}
.bd.OPEN{background:rgba(245,158,11,.15);color:var(--amb)}.bd.WON{background:rgba(16,185,129,.15);color:var(--grn)}.bd.LOST{background:rgba(244,63,94,.15);color:var(--red)}
.m{display:grid;grid-template-columns:repeat(3,1fr);background:var(--surface);padding:9px;border-radius:12px;text-align:center;margin-bottom:8px}
.m span{font-size:10px;color:var(--mut);display:block}.m strong{font-size:13px}
.note{font-size:12px;color:#cbd5e1;background:rgba(255,255,255,.03);padding:7px 10px;border-radius:8px;margin-bottom:5px;border-right:3px solid var(--pri)}
.les{font-size:11px;color:var(--mut);padding:3px 10px;border-right:3px solid #475569}
.empty{text-align:center;padding:32px 14px;color:var(--mut);background:var(--card);border-radius:16px;font-size:13px}
.sys{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--card);padding:13px 15px;border-radius:14px;margin-bottom:9px;border:1px solid var(--line);font-size:13px;font-weight:700}
.on{color:var(--grn)}.offc{color:var(--mut)}
.labbtn{width:100%;background:#fff;color:#4c1d95;border:0;padding:12px;border-radius:12px;font-size:13px;font-weight:900;margin-top:12px}
.hint{font-size:11px;color:var(--mut);line-height:1.7;margin:2px 4px 10px}
nav{position:fixed;bottom:0;left:0;right:0;background:rgba(15,23,42,.93);backdrop-filter:blur(16px);border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:8px 8px calc(12px + env(safe-area-inset-bottom));z-index:9}
.nv{background:none;border:0;color:var(--mut);font-size:11px;font-weight:700;display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 16px;border-radius:12px}
.nv.act{color:var(--pri);background:rgba(56,189,248,.1)}
.tab{display:none}.tab.act{display:block}
@media(prefers-reduced-motion:no-preference){.dot{animation:p 2s infinite}@keyframes p{50%{opacity:.4}}}
</style></head><body>
<div class="shell">
 <div class="head"><div class="brand"><div class="dot" id="dot"></div><div><h1>رادار التداول الذكي</h1><span class="sub" id="sub">جاري التحميل...</span></div></div>
 <button class="btn" id="scanBtn" onclick="scanNow()">⚡ فحص الآن</button></div>
 <div id="warns"></div>
 <div class="ai"><b>🧠 المشرف</b><span id="ai">...</span></div>

 <div id="tab-live" class="tab act">
  <div class="hero"><div class="row"><div><span class="lbl">إجمالي المحفظة التجريبية</span><h2 class="big" id="w">—</h2></div><div class="pill" id="pnl">—</div></div>
   <div id="curve" style="margin-top:8px"></div>
   <div class="grid3"><div><span>الكاش المتاح</span><strong id="cash">—</strong></div><div><span>في صفقات</span><strong id="inv">—</strong></div><div><span>مفتوحة الآن</span><strong id="opn">—</strong></div></div></div>
  <div class="kpis">
   <div class="kpi"><span>نسبة النجاح</span><strong id="k-wr">—</strong><small id="k-n"></small></div>
   <div class="kpi"><span>معامل الربحية</span><strong id="k-pf">—</strong><small>أكبر من 1 = رابح</small></div>
   <div class="kpi"><span>متوسط الربح للصفقة</span><strong id="k-ex">—</strong><small>بعد الرسوم</small></div>
   <div class="kpi"><span>أكبر تراجع</span><strong id="k-dd">—</strong><small>من القمة للقاع</small></div></div>
  <div class="prog"><div class="row"><span>تقدم مرحلة التدريب</span><b id="pg-t">0 / 50</b></div><div class="bar"><i id="pg-b" style="width:0"></i></div></div>
  <div class="chips" id="chips"></div>
  <div id="live-list"></div>
 </div>

 <div id="tab-lab" class="tab">
  <div class="hero lab"><span class="lbl">مختبر الماضي (معزول عن المحفظة)</span>
   <div class="row" style="align-items:center"><div><span class="lbl">نسبة النجاح</span><h2 class="big" id="h-wr">—</h2></div>
   <div style="text-align:left"><span class="lbl">صافي افتراضي</span><strong style="font-size:18px" id="h-pnl">—</strong></div></div>
   <div class="grid3"><div><span>صفقات</span><strong id="h-n">0</strong></div><div><span>معامل الربحية</span><strong id="h-pf">—</strong></div><div><span>أكبر تراجع</span><strong id="h-dd">—</strong></div></div>
   <button class="labbtn" id="btBtn" onclick="runBt()">🔬 إعادة الفحص على آخر 6 أشهر</button></div>
  <p class="hint">المحاكاة تدخل عند افتتاح الشمعة التالية، وتحترم ترتيب الهدف والوقف، وتخصم الرسوم. أي نتيجة جيدة هنا لا تضمن نتيجة حية.</p>
  <div id="lab-list"></div>
 </div>

 <div id="tab-sys" class="tab">
  <div class="sec"><span>الأسواق الآن</span></div><div id="mk"></div>
  <div class="sec"><span>الإعدادات</span></div><div id="cfg"></div>
  <div class="sec"><span>النظام</span></div><div id="sysrows"></div>
  <button class="btn" style="width:100%;padding:12px" id="pauseBtn" onclick="pauseToggle()">—</button>
 </div>
</div>
<nav>
 <button class="nv act" onclick="tab('live',this)">💼<span>المحفظة</span></button>
 <button class="nv" onclick="tab('lab',this)">🧪<span>المختبر</span></button>
 <button class="nv" onclick="tab('sys',this)">📡<span>النظام</span></button>
</nav>
<script>
let D=null, flt='all';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sg=n=>(n>0?'+':'')+Number(n).toFixed(2);
const col=n=>n>=0?'var(--grn)':'var(--red)';
function tab(n,b){document.querySelectorAll('.tab,.nv').forEach(e=>e.classList.remove('act'));$('tab-'+n).classList.add('act');b.classList.add('act')}
function spark(v){
 if(!v||v.length<2)return '<div class="sub" style="text-align:center;padding:12px;color:rgba(255,255,255,.6)">المنحنى يظهر بعد أول صفقتين مغلقتين</div>';
 const mn=Math.min(...v,0),mx=Math.max(...v,.01),r=mx-mn||1;
 const p=v.map((y,i)=>(i/(v.length-1)*300).toFixed(1)+','+(56-(y-mn)/r*52).toFixed(1)).join(' ');
 return '<svg viewBox="0 0 300 60" preserveAspectRatio="none" style="width:100%;height:56px"><polyline points="'+p+'" fill="none" stroke="#4ade80" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>'}
function cards(ts,empty){
 if(!ts||!ts.length)return '<div class="empty">'+empty+'</div>';
 const S={OPEN:'جارية ⏳',WON:'رابحة ✅',LOST:'خاسرة 🛡️'};
 return ts.map(t=>{const c=t.symbol.endsWith('.SR')?' ر.س':'$',p=t.pnl_sar||0;
 return `<div class="t ${t.status}"><div class="tt"><div><span class="sym">${esc(t.symbol)}</span><span class="as">${esc(t.asset_type)} • ${esc(t.entry_time)}</span></div><span class="bd ${t.status}">${S[t.status]||t.status}</span></div>
 <div class="m"><div><span>الدخول (${t.invested_sar} ر.س)</span><strong>${t.entry_price}${c}</strong></div><div><span>الخروج</span><strong>${t.exit_price?t.exit_price+c:'—'}</strong></div><div><span>الصافي</span><strong style="color:${col(p)}">${sg(p)} ر.س</strong></div></div>
 <div class="note">💡 ${esc(t.reason)}</div><div class="les">📌 ${esc(t.lesson||'يراقب السعر...')}</div></div>`}).join('')}
function render(){
 if(!D)return; const L=D.live,s=L.stats,c=D.cfg,lab=D.lab;
 $('ai').innerText=c.ai_report;
 $('w').innerText=L.wallet.toFixed(2)+' ر.س';
 const tot=L.wallet-D.start;$('pnl').innerText=sg(tot)+' ر.س';$('pnl').style.color=tot>=0?'#4ade80':'#fda4af';
 $('curve').innerHTML=spark(s.curve);
 $('cash').innerText=L.cash.toFixed(1);$('inv').innerText=L.invested.toFixed(1);$('opn').innerText=L.open_count;
 $('k-wr').innerText=s.win_rate==null?'—':s.win_rate+'%';$('k-n').innerText=s.n+' صفقة مغلقة';
 $('k-pf').innerText=s.pf==null?'—':s.pf;
 $('k-ex').innerText=s.expectancy==null?'—':sg(s.expectancy)+' ر.س';$('k-ex').style.color=s.expectancy==null?'':col(s.expectancy);
 $('k-dd').innerText=s.max_dd.toFixed(2)+' ر.س';
 const g=Math.min(s.n,50);$('pg-t').innerText=s.n+' / 50';$('pg-b').style.width=(g/50*100)+'%';
 const F={all:'الكل',OPEN:'جارية',WON:'رابحة',LOST:'خاسرة'};
 $('chips').innerHTML=Object.keys(F).map(k=>`<button class="chip ${flt===k?'on':''}" onclick="flt='${k}';render()">${F[k]}</button>`).join('');
 $('live-list').innerHTML=cards(L.trades.filter(t=>flt==='all'||t.status===flt),'لا صفقات هنا بعد. الرادار يفحص 15 أصلاً كل دقيقتين، ويدخل فقط عند تحقق الشروط.');
 $('h-wr').innerText=lab.win_rate==null?'—':lab.win_rate+'%';$('h-pnl').innerText=sg(lab.pnl)+' ر.س';
 $('h-n').innerText=lab.n;$('h-pf').innerText=lab.pf==null?'—':lab.pf;$('h-dd').innerText=lab.max_dd.toFixed(2);
 $('lab-list').innerHTML=cards(lab.trades,'اضغط الزر بالأعلى لتشغيل المحاكاة.');
 const m=D.markets,row=(a,b,on)=>`<div class="sys"><span>${a}</span><span class="${on?'on':'offc'}">${b}</span></div>`;
 $('mk').innerHTML=row('₿ العملات الرقمية','مفتوح 24/7',1)+row('🇸🇦 تاسي (الأحد–الخميس 10ص–3م)',m.tasi?'مفتوح':'مغلق',m.tasi)+row('🇺🇸 الأمريكي (الإثنين–الجمعة)',m.us?'مفتوح':'مغلق',m.us);
 $('cfg').innerHTML=row('🎯 نطاق RSI',c.rsi_min+' – '+c.rsi_max,1)+row('⚖️ هدف / وقف',`+${c.tp_pct}% / ${c.sl_pct}%`,1)+row('💵 حجم الصفقة',c.trade_size+' ر.س',1)+row('🧾 رسوم تقديرية',(D.fee*2).toFixed(2)+'% للصفقة',1)+row('⏱️ أقصى مدة احتفاظ',c.max_hold_h+' ساعة',1)+row('🔒 حد الصفقات المفتوحة',c.max_open+' (مع '+c.max_per_class+' كحد أقصى لكل سوق)',1);
 $('sysrows').innerHTML=row('☁️ نسخ GitHub',D.cloud_ok?'مربوط 🟢':'غير مفعّل 🔴',D.cloud_ok)+row('🕒 آخر فحص',D.last_scan||'—',!!D.last_scan);
 $('pauseBtn').innerText=c.paused?'▶️ استئناف الدخول بصفقات جديدة':'⏸️ إيقاف الدخول بصفقات جديدة';
 let w='';if(!D.cloud_ok)w+='<div class="warn">⚠️ النسخ السحابي غير مفعّل: سجل الصفقات يضيع عند إعادة تشغيل السيرفر. أضف GITHUB_TOKEN.</div>';
 if(D.error)w+='<div class="warn">⚠️ خطأ في آخر فحص: '+esc(D.error)+'</div>';
 if(c.paused)w+='<div class="warn">⏸️ الدخول بصفقات جديدة متوقف. الصفقات المفتوحة ما زالت تُتابع.</div>';
 $('warns').innerHTML=w;$('dot').className='dot'+(c.paused?' off':'');
 $('sub').innerText='آخر فحص: '+(D.last_scan||'—');}
async function load(){try{D=await (await fetch('/api/data')).json();render()}catch(e){$('sub').innerText='تعذر الاتصال بالسيرفر'}}
async function act(path){
 const go=k=>fetch(path+(path.includes('?')?'&':'?')+'key='+encodeURIComponent(k));
 let k=localStorage.getItem('k')||'',r=await go(k);
 if(r.status===401){k=prompt('مفتاح الإدارة (ADMIN_KEY)');if(!k)return null;localStorage.setItem('k',k);r=await go(k);if(r.status===401){localStorage.removeItem('k');return null}}
 return r}
async function scanNow(){const b=$('scanBtn');b.disabled=true;b.innerText='⏳ جاري الفحص';await act('/api/scan');setTimeout(async()=>{await load();b.disabled=false;b.innerText='⚡ فحص الآن'},6000)}
async function runBt(){const b=$('btBtn');b.disabled=true;b.innerText='⏳ جاري التحليل (قد يأخذ دقيقة)';await act('/api/backtest');setTimeout(async()=>{await load();b.disabled=false;b.innerText='🔬 إعادة الفحص على آخر 6 أشهر'},45000)}
async function pauseToggle(){await act('/api/pause');await load()}
load();setInterval(load,30000);
</script></body></html>
'''
