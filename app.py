"""Cartera PPI: servicio de SOLO LECTURA. Las credenciales vienen de variables de entorno."""
import os, secrets, time, threading, traceback, logging, hmac, hashlib
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from ppi_client.ppi import PPI

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
basic = HTTPBasic(auto_error=False)
COOKIE = "cartera_sesion"
_fails = []
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

def token():
    return hmac.new(need("APP_PASSWORD").encode(), b"cartera-ppi-sesion", hashlib.sha256).hexdigest()

def is_authed(request: Request, cred=None):
    c = request.cookies.get(COOKIE)
    if c and hmac.compare_digest(c.encode("utf-8", "ignore"), token().encode()):
        return True
    if cred is not None:
        return secrets.compare_digest(cred.password.encode(), need("APP_PASSWORD").encode())
    return False

def auth(request: Request, cred: Optional[HTTPBasicCredentials] = Depends(basic)):
    if not is_authed(request, cred):
        raise HTTPException(401, "Necesitás iniciar sesión")

@app.post("/login")
async def login(request: Request):
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < 60]
    if len(_fails) >= 8:
        raise HTTPException(429, "Demasiados intentos. Esperá un minuto.")
    try:
        body = await request.json()
        pw = str(body.get("password", ""))
    except Exception:
        pw = ""
    if not secrets.compare_digest(pw.encode(), need("APP_PASSWORD").encode()):
        _fails.append(now)
        raise HTTPException(401, "Contraseña incorrecta")
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, token(), max_age=60*60*24*365, httponly=True, secure=True, samesite="lax")
    return r

@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({"name": "Mi Cartera PPI", "short_name": "Cartera", "start_url": "/", "display": "standalone",
        "background_color": "#F2F4F7", "theme_color": "#1B4FD6",
        "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}]},
        media_type="application/manifest+json")

@app.get("/icon.png")
def icon():
    return FileResponse(os.path.join(HERE, "icon.png"), media_type="image/png")

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

import re
from datetime import datetime, timedelta

@app.get("/api/movimientos", dependencies=[Depends(auth)])
def movimientos():
    try:
        from ppi_client.models.account_movements import AccountMovements
        hoy = datetime.now()
        res = jsonable(client().account.get_movements(AccountMovements(need("PPI_ACCOUNT"), hoy - timedelta(days=365), hoy, None)))
        first = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else None)
        log.info("movimientos: tipo=%s n=%s claves=%s", type(res).__name__, len(res) if hasattr(res, "__len__") else "?", sorted(first.keys()) if isinstance(first, dict) else None)
        return res
    except HTTPException: raise
    except Exception as e:
        log.error("PPI movimientos error: %s", safe(e))
        raise HTTPException(502, "PPI respondió con error: " + safe(e))

@app.get("/api/precio/{ticker}", dependencies=[Depends(auth)])
def precio(ticker: str):
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,12}", ticker):
        raise HTTPException(400, "Código inválido")
    try:
        return jsonable(client().marketdata.current(ticker.upper(), "CEDEARS", "A-48HS"))
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(502, "PPI respondió con error: " + safe(e))

@app.get("/api/analisis/{ticker}", dependencies=[Depends(auth)])
def analisis(ticker: str):
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,10}", ticker):
        raise HTTPException(400, "Código inválido")
    try:
        import analisis as an
        return an.analizar(ticker)
    except Exception as e:
        log.error("analisis %s: %s", ticker, safe(e))
        raise HTTPException(502, "No pude traer datos de " + ticker.upper() + " ahora (" + type(e).__name__ + "). Probá de nuevo en un rato.")

LOGIN = """<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=apple-mobile-web-app-capable content=yes><meta name=mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-title content="Mi Cartera">
<link rel=manifest href=/manifest.webmanifest><link rel=apple-touch-icon href=/icon.png><meta name=theme-color content="#1B4FD6"><title>Mi Cartera PPI</title>
<style>:root{--bg:#F2F4F7;--ink:#101A24;--s:#fff;--line:#D7DDE5;--acc:#1B4FD6}@media(prefers-color-scheme:dark){:root{--bg:#0C1218;--ink:#E7EDF3;--s:#141C25;--line:#25303C;--acc:#7AA2FF}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px system-ui,-apple-system,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
form{width:100%;max-width:360px;background:var(--s);border:1px solid var(--line);border-radius:12px;padding:20px;display:flex;flex-direction:column;gap:12px}
h1{margin:0;font-size:22px}input,button{font:inherit;font-size:16px;padding:12px;border-radius:8px;border:1px solid var(--line);min-height:44px;background:var(--bg);color:var(--ink)}
button{background:var(--acc);color:#fff;border-color:var(--acc);font-weight:600}#e{color:#BF3126;min-height:20px;margin:0;font-size:14px}</style>
<form id=f><h1>Mi Cartera PPI</h1><input id=p type=password placeholder="Contraseña" autocomplete=current-password autofocus><p id=e></p><button>Entrar</button></form>
<script>f.onsubmit=function(ev){ev.preventDefault();e.textContent='';fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p.value})})
.then(function(r){if(r.ok)location.reload();else return r.json().then(function(d){e.textContent=d.detail||'Error'})}).catch(function(){e.textContent='No hay conexión'})}</script></html>"""

@app.get("/", response_class=HTMLResponse)
def home(request: Request, cred: Optional[HTTPBasicCredentials] = Depends(basic)):
    if not is_authed(request, cred):
        return LOGIN
    return open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
