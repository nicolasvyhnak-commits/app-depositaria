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

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Cartera PPI</title><body style="font-family:system-ui;margin:16px;max-width:560px">
<h1>Cartera PPI</h1><p id=s>Cargando…</p><pre id=o style="white-space:pre-wrap;font-size:12px"></pre>
<script>fetch('/api/posiciones').then(r=>r.json()).then(d=>{s.textContent='Datos reales de PPI (vista inicial)';o.textContent=JSON.stringify(d,null,1)}).catch(e=>s.textContent='Error: '+e)</script>"""

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def home(): return PAGE
