"""Cartera PPI: servicio de SOLO LECTURA. Las credenciales vienen de variables de entorno."""
import os, secrets, time, threading, traceback, logging
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from ppi_client.ppi import PPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
basic = HTTPBasic()
lock = threading.Lock()
_ppi = {"c": None, "t": 0}

log = logging.getLogger("uvicorn.error")

def safe(e):
    t = f"{type(e).__name__}: {e}"
    for k in ("PPI_PUBLIC_KEY", "PPI_PRIVATE_KEY", "APP_PASSWORD"):
        v = os.environ.get(k)
        if v: t = t.replace(v, "***")
    return t[:300]

def need(name):
    v = os.environ.get(name)
    if not v:
        raise HTTPException(500, f"Falta la variable {name} en Render")
    return v

def auth(cred: HTTPBasicCredentials = Depends(basic)):
    ok = secrets.compare_digest(cred.password.encode(), need("APP_PASSWORD").encode())
    if not ok:
        raise HTTPException(401, "Contraseña incorrecta", headers={"WWW-Authenticate": "Basic"})

def client():
    with lock:
        if _ppi["c"] is None or time.time() - _ppi["t"] > 40 * 60:
            c = PPI(sandbox=False)
            c.account.login_api(need("PPI_PUBLIC_KEY"), need("PPI_PRIVATE_KEY"))
            _ppi["c"], _ppi["t"] = c, time.time()
        return _ppi["c"]

def jsonable(o):
    if isinstance(o, dict): return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [jsonable(v) for v in o]
    if hasattr(o, "__dict__"): return jsonable(vars(o))
    return o

@app.get("/health")
def health(): return {"ok": True}

@app.get("/api/posiciones", dependencies=[Depends(auth)])
def posiciones():
    try:
        return jsonable(client().account.get_balance_and_positions(need("PPI_ACCOUNT")))
    except HTTPException: raise
    except Exception as e:
        _ppi["c"] = None
        log.error("PPI error: %s\n%s", safe(e), "".join(traceback.format_exc().splitlines(True)[-6:]))
        raise HTTPException(502, "PPI respondió con error: " + safe(e))

@app.get("/api/saldos", dependencies=[Depends(auth)])
def saldos():
    try:
        return jsonable(client().account.get_available_balance(need("PPI_ACCOUNT")))
    except HTTPException: raise
    except Exception as e:
        _ppi["c"] = None
        log.error("PPI error: %s\n%s", safe(e), "".join(traceback.format_exc().splitlines(True)[-6:]))
        raise HTTPException(502, "PPI respondió con error: " + safe(e))

PAGE = """<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Cartera PPI</title>
<style>
:root{--bg:#F2F4F7;--s:#fff;--ink:#101A24;--mut:#586574;--line:#D7DDE5;--g:#0E7A55;--l:#BF3126}
@media(prefers-color-scheme:dark){:root{--bg:#0C1218;--s:#141C25;--ink:#E7EDF3;--mut:#93A1B1;--line:#25303C;--g:#3DD598;--l:#FF7A6E}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,sans-serif;padding:16px max(16px,env(safe-area-inset-right)) 40px max(16px,env(safe-area-inset-left))}
.w{max-width:560px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
h1,h2,p{margin:0}h1{font-size:22px}h2{font-size:18px}
.c{background:var(--s);border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:6px}
.big{font:600 28px ui-monospace,Menlo,monospace;overflow-wrap:anywhere}
.m{color:var(--mut);font-size:13px}.r{display:flex;justify-content:space-between;gap:12px}
.r b{font-family:ui-monospace,Menlo,monospace;font-weight:600;text-align:right}
.g{color:var(--g)}.l{color:var(--l)}.t{font-weight:600}
</style><body><div class=w><h1>Cartera PPI</h1><p class=m id=s>Cargando...</p><div id=o class=w style="gap:16px"></div>
<details class=m><summary>Datos tal cual los envia PPI</summary><pre id=raw style="white-space:pre-wrap;font-size:11px"></pre></details></div>
<script>
const f=(n,d=2)=>new Intl.NumberFormat('es-AR',{minimumFractionDigits:d,maximumFractionDigits:d}).format(n);
const sg=(n,suf='')=>(n>0?'+':n<0?'-':'')+f(Math.abs(n))+suf;
const cl=n=>n>0?'g':n<0?'l':'';
function esc(x){return String(x==null?'':x).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
fetch('/api/posiciones').then(r=>r.json()).then(d=>{
 if(d.detail){s.textContent='Error: '+d.detail;return}
 raw.textContent=JSON.stringify(d,null,1);
 let h='',tot=0;
 (d.groupedInstruments||[]).forEach(g=>{tot+=g.groupedValue||0});
 h+='<div class=c><p class=m>Valor de tus inversiones (en pesos)</p><p class=big>$'+f(tot,0)+'</p></div>';
 (d.groupedInstruments||[]).forEach(g=>{
  h+='<h2>'+esc(g.name)+'</h2>';
  (g.instruments||[]).forEach(i=>{
   const p=i.ppc||{},ret=p.cumulativeReturn,pc=p.cumulativeReturnPercentage;
   h+='<div class=c><div class=r><span class=t>'+esc(i.ticker)+'</span><b>'+esc((i.currency||'').includes('MEP')?'US$':'$')+f(i.amount)+'</b></div>'
   +'<p class=m>'+esc(i.description)+'</p>'
   +'<div class=r><span>Cantidad</span><b>'+f(i.quantity,0)+'</b></div>'
   +'<div class=r><span>Precio hoy</span><b>'+f(i.price)+'</b></div>'
   +'<div class=r><span>Precio promedio de compra</span><b>'+f(p.ppcValue)+'</b></div>'
   +(ret!=null?'<div class=r><span>Ganancia o perdida</span><b class='+cl(ret)+'>'+sg(ret)+' ('+sg(pc,'%')+')</b></div>':'')
   +'</div>'});
 });
 h+='<h2>Efectivo disponible</h2><div class=c>';
 (d.groupedAvailability||[]).forEach(g=>{
  const imm=(g.availability||[]).find(a=>a.settlement==='INMEDIATA');
  if(imm)h+='<div class=r><span>'+esc(g.currency)+'</span><b>'+(imm.symbol==='USD'?'US$':'$')+f(imm.amount)+'</b></div>'});
 h+='</div>';
 o.innerHTML=h;s.textContent='Datos reales de tu cuenta en PPI';
}).catch(e=>s.textContent='Error: '+e);
</script></html>"""

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def home(): return PAGE
