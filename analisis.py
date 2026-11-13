"""Análisis técnico y fundamental de una acción de EE.UU. (el subyacente de un CEDEAR).
Solo lectura de datos públicos (Yahoo Finance). No opera ni da órdenes."""
import json, math, os, time, threading, urllib.request, urllib.error, urllib.parse, http.cookiejar

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TTL = 45 * 60
_cache = {}
_lock = threading.Lock()
_sess = {"opener": None, "crumb": None, "t": 0}


# ---------- descarga ----------
def _opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Accept", "application/json,text/plain,*/*"), ("Accept-Language", "en-US,en;q=0.9")]
    return op

def _get(op, url, timeout=10):
    with op.open(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _session(force=False):
    with _lock:
        if force or not _sess["crumb"] or time.time() - _sess["t"] > 6 * 3600:
            op = _opener()
            try:
                _get(op, "https://fc.yahoo.com")
            except urllib.error.HTTPError:
                pass  # devuelve 404 pero deja la cookie
            crumb = _get(op, "https://query1.finance.yahoo.com/v1/test/getcrumb").strip()
            if not crumb or "<" in crumb or len(crumb) > 40:
                raise RuntimeError("Yahoo no entregó el permiso de consulta")
            _sess.update(opener=op, crumb=crumb, t=time.time())
        return _sess["opener"], _sess["crumb"]

def _yahoo_history(t):
    last = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?range=2y&interval=1d&includePrePost=false"
        try:
            res = json.loads(_get(_opener(), url))["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            rows = [(ts, c, v) for ts, c, v in zip(res["timestamp"], q["close"], q.get("volume") or [None] * len(q["close"])) if c is not None]
            meta = res.get("meta", {})
            return {"ts": [r[0] for r in rows], "close": [r[1] for r in rows], "vol": [r[2] or 0 for r in rows],
                    "name": meta.get("longName") or meta.get("shortName") or t, "price": meta.get("regularMarketPrice"),
                    "ccy": meta.get("currency", "USD"), "src": "yahoo"}
        except Exception as e:
            last = e
    raise last

def _stooq_history(t):
    sym = t.lower().replace(".", "-") + ".us"
    raw = _get(_opener(), f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d")
    lines = [l for l in raw.strip().splitlines() if l]
    if not lines or not lines[0].lower().startswith("date,open"):
        raise RuntimeError("Stooq no devolvió datos")
    ts, c, v = [], [], []
    for l in lines[1:]:
        p = l.split(",")
        if len(p) < 6 or p[4] in ("", "null"): continue
        ts.append(int(time.mktime(time.strptime(p[0], "%Y-%m-%d")))); c.append(float(p[4])); v.append(float(p[5] or 0))
    ts, c, v = ts[-520:], c[-520:], v[-520:]
    return {"ts": ts, "close": c, "vol": v, "name": t, "price": c[-1], "ccy": "USD", "src": "stooq"}


# ---------- Financial Modeling Prep (con clave gratuita en FMP_API_KEY) ----------
def _fmp_key():
    return os.environ.get("FMP_API_KEY", "").strip()

def _fmp(path, **params):
    q = dict(params); q["apikey"] = _fmp_key()
    raw = _get(_opener(), "https://financialmodelingprep.com/stable/" + path + "?" + urllib.parse.urlencode(q), timeout=12)
    d = json.loads(raw)
    if isinstance(d, dict) and (d.get("Error Message") or d.get("error")):
        raise RuntimeError(str(d.get("Error Message") or d.get("error"))[:100])
    return d

def _pick(d, *names):
    for n in names:
        v = d.get(n)
        if isinstance(v, (int, float)) and math.isfinite(v): return v
    return None

def _fmp_history(t):
    if not _fmp_key(): raise RuntimeError("Falta FMP_API_KEY")
    desde = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 800 * 86400))
    rows = _fmp("historical-price-eod/full", symbol=t, **{"from": desde})
    if not isinstance(rows, list) or len(rows) < 60: raise RuntimeError("FMP sin datos")
    rows = sorted(rows, key=lambda r: r["date"])
    ts = [int(time.mktime(time.strptime(r["date"], "%Y-%m-%d"))) for r in rows]
    c = [float(r["close"]) for r in rows]; v = [float(r.get("volume") or 0) for r in rows]
    name = t
    try:
        pr = _fmp("profile", symbol=t)
        if pr: name = pr[0].get("companyName") or t
    except Exception:
        pass
    return {"ts": ts, "close": c, "vol": v, "name": name, "price": c[-1], "ccy": "USD", "src": "fmp"}

def _fmp_fundamentals(t):
    if not _fmp_key(): raise RuntimeError("Falta FMP_API_KEY")
    out = {k: None for k in ("pe", "fpe", "rev_g", "earn_g", "margin", "gross", "roe", "d2e", "cash", "debt", "rec", "target", "n_an", "mcap", "earn_ts")}
    ok = 0
    try:
        r = _fmp("ratios-ttm", symbol=t)[0]; ok += 1
        out["pe"] = _pick(r, "priceToEarningsRatioTTM", "peRatioTTM")
        out["margin"] = _pick(r, "netProfitMarginTTM")
        out["gross"] = _pick(r, "grossProfitMarginTTM")
        d = _pick(r, "debtToEquityRatioTTM", "debtEquityRatioTTM")
        out["d2e"] = d * 100 if d is not None else None
    except Exception:
        pass
    try:
        inc = _fmp("income-statement", symbol=t, limit=2); ok += 1
        if len(inc) >= 2:
            if inc[1].get("revenue"): out["rev_g"] = inc[0]["revenue"] / inc[1]["revenue"] - 1
            a, b = inc[0].get("netIncome"), inc[1].get("netIncome")
            if a is not None and b and b > 0: out["earn_g"] = a / b - 1
    except Exception:
        pass
    try:
        bs = _fmp("balance-sheet-statement", symbol=t, limit=1)[0]; ok += 1
        out["cash"] = _pick(bs, "cashAndShortTermInvestments", "cashAndCashEquivalents"); out["debt"] = _pick(bs, "totalDebt")
    except Exception:
        pass
    try:
        pt = _fmp("price-target-consensus", symbol=t)[0]; ok += 1
        out["target"] = _pick(pt, "targetConsensus", "targetMedian")
    except Exception:
        pass
    if not ok: raise RuntimeError("FMP no devolvió fundamentales")
    return out

def fetch_history(t):
    errs = []
    for fn in ((_fmp_history,) if _fmp_key() else ()) + (_yahoo_history, _stooq_history):
        try:
            return fn(t)
        except Exception as e:
            errs.append(f"{getattr(fn, '__name__', '?').strip('_').split('_')[0]}: {type(e).__name__} {e}"[:120])
    raise RuntimeError(" | ".join(errs))

def fetch_fundamentals(t):
    if _fmp_key():
        try:
            return _fmp_fundamentals(t)
        except Exception:
            pass
    return _yahoo_fundamentals(t)

def _yahoo_fundamentals(t):
    mods = "financialData,defaultKeyStatistics,summaryDetail,calendarEvents"
    for intento in (0, 1):
        op, crumb = _session(force=bool(intento))
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(t)}?modules={mods}&crumb={urllib.parse.quote(crumb)}"
        try:
            raw = _get(op, url)
            break
        except urllib.error.HTTPError as e:
            if intento == 0 and e.code in (401, 403, 404):
                continue
            raise
    r = json.loads(raw)["quoteSummary"]["result"][0]
    def g(mod, key):
        v = (r.get(mod) or {}).get(key)
        if isinstance(v, dict): v = v.get("raw")
        return v if isinstance(v, (int, float)) and math.isfinite(v) else None
    ed = None
    try:
        dates = r["calendarEvents"]["earnings"]["earningsDate"]
        ed = dates[0]["raw"] if dates else None
    except Exception:
        pass
    return {
        "pe": g("summaryDetail", "trailingPE"), "fpe": g("summaryDetail", "forwardPE") or g("defaultKeyStatistics", "forwardPE"),
        "rev_g": g("financialData", "revenueGrowth"), "earn_g": g("financialData", "earningsGrowth"),
        "margin": g("financialData", "profitMargins"), "gross": g("financialData", "grossMargins"),
        "roe": g("financialData", "returnOnEquity"), "d2e": g("financialData", "debtToEquity"),
        "cash": g("financialData", "totalCash"), "debt": g("financialData", "totalDebt"),
        "rec": g("financialData", "recommendationMean"), "target": g("financialData", "targetMeanPrice"),
        "n_an": g("financialData", "numberOfAnalystOpinions"), "mcap": g("summaryDetail", "marketCap"),
        "earn_ts": ed,
    }


# ---------- indicadores ----------
def sma(x, n):
    return [None if i + 1 < n else sum(x[i + 1 - n:i + 1]) / n for i in range(len(x))]

def ema(x, n):
    k = 2 / (n + 1); out = []; e = None
    for v in x:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out

def rsi(x, n=14):
    if len(x) <= n: return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = x[i] - x[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(x)):
        d = x[i] - x[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)

def macd(x):
    if len(x) < 40: return None
    m = [a - b for a, b in zip(ema(x, 12), ema(x, 26))]
    s = ema(m, 9)
    return {"macd": m[-1], "signal": s[-1], "hist": m[-1] - s[-1], "hist_prev": m[-2] - s[-2]}

def ret(x, d):
    return x[-1] / x[-1 - d] - 1 if len(x) > d else None

def technicals(h):
    c, v = h["close"], h["vol"]
    if len(c) < 60: raise ValueError("Pocos datos históricos")
    s50, s200 = sma(c, 50), sma(c, 200)
    last = c[-1]
    yr = c[-252:]
    hi, lo = max(yr), min(yr)
    r60 = c[-60:]
    rets = [c[i] / c[i - 1] - 1 for i in range(len(c) - 30, len(c))]
    mu = sum(rets) / len(rets)
    vol30 = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252)
    v5 = sum(v[-5:]) / 5; v20 = sum(v[-20:]) / 20
    return {
        "price": last, "sma50": s50[-1], "sma200": s200[-1], "rsi": rsi(c), "macd": macd(c),
        "hi52": hi, "lo52": lo, "from_hi": last / hi - 1, "from_lo": last / lo - 1,
        "sup": min(r60), "res": max(r60),
        "r1m": ret(c, 21), "r3m": ret(c, 63), "r6m": ret(c, 126), "r1y": ret(c, 252),
        "vol30": vol30, "vol_ratio": (v5 / v20) if v20 else None,
        "series": _series(h, s50, s200),
    }

def _series(h, s50, s200):
    n = 252
    c = h["close"][-n:]
    r = lambda a: [None if v is None else round(v, 2) for v in a[-n:]]
    return {"close": [round(v, 2) for v in c], "sma50": r(s50), "sma200": r(s200), "ts": h["ts"][-n:]}


# ---------- semáforos (solo describen; no son órdenes) ----------
def _p(x, d=1):
    return "—" if x is None else f"{x * 100:+.{d}f}%".replace(".", ",")

def _n(x, d=1):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")

def _usd(x):
    if x is None: return "—"
    a = abs(x)
    if a >= 1e12: return f"US${x / 1e12:.2f} bill.".replace(".", ",")
    if a >= 1e9: return f"US${x / 1e9:.1f} mil M".replace(".", ",")
    return f"US${x / 1e6:.0f} M"

def light(label, value, tone, text):
    return {"label": label, "value": value, "tone": tone, "text": text}

def tech_lights(t):
    out = []
    p = t["price"]
    if t["sma200"]:
        up = p > t["sma200"]
        out.append(light("Tendencia larga", "Arriba de la media de 200 ruedas" if up else "Debajo de la media de 200 ruedas",
            "g" if up else "r", f"La media de 200 ruedas es US${_n(t['sma200'], 2)}. El precio está {_p(p / t['sma200'] - 1)} respecto de ella. Sirve para ver si la tendencia de fondo viene para arriba o para abajo."))
    if t["sma50"]:
        up = p > t["sma50"]
        out.append(light("Tendencia corta", "Arriba de la media de 50" if up else "Debajo de la media de 50",
            "g" if up else "r", f"La media de 50 ruedas es US${_n(t['sma50'], 2)}. El precio está {_p(p / t['sma50'] - 1)} respecto de ella."))
    if t["rsi"] is not None:
        r = t["rsi"]
        if r >= 70: tone, v, x = "y", "Sobrecomprada", "Subió mucho y rápido. Suele pasar antes de una pausa, aunque puede seguir."
        elif r <= 30: tone, v, x = "y", "Sobrevendida", "Cayó mucho y rápido. A veces rebota, pero también puede seguir cayendo."
        else: tone, v, x = "n", "Neutral", "Ni demasiado comprada ni demasiado vendida."
        out.append(light("Fuerza (RSI)", f"{_n(r, 0)} · {v}", tone, f"El RSI mide el ritmo de las subas y bajas recientes, de 0 a 100. {x}"))
    m = t["macd"]
    if m:
        pos = m["hist"] > 0; mejora = m["hist"] > m["hist_prev"]
        out.append(light("Impulso (MACD)", ("Positivo" if pos else "Negativo") + (" y mejorando" if mejora else " y flojeando"),
            "g" if pos else "r", "Compara dos promedios del precio. Positivo: el impulso reciente es de suba. Negativo: es de baja. 'Mejorando' significa que se está fortaleciendo."))
    out.append(light("Vs. máximo del año", _p(t["from_hi"]), "g" if t["from_hi"] > -0.1 else ("y" if t["from_hi"] > -0.25 else "r"),
        f"Máximo de 12 meses: US${_n(t['hi52'], 2)}; mínimo: US${_n(t['lo52'], 2)}. Hoy está {_p(t['from_lo'])} arriba del mínimo."))
    if t["vol_ratio"]:
        vr = t["vol_ratio"]
        out.append(light("Volumen", f"{_n(vr, 2)}× lo normal", "y" if vr > 1.5 else "n",
            "Compara lo operado en los últimos 5 días con el promedio de 20. Mucho volumen en un movimiento le da más peso a ese movimiento."))
    out.append(light("Volatilidad", f"{_n(t['vol30'] * 100, 0)}% anual", "r" if t["vol30"] > 0.55 else ("y" if t["vol30"] > 0.35 else "g"),
        "Qué tanto se mueve el precio día a día. Más volatilidad = más posible ganancia y también más posible pérdida."))
    return out

def fund_lights(f, price):
    out = []
    rg = f.get("rev_g")
    if rg is not None:
        out.append(light("Crecimiento de ventas", _p(rg), "g" if rg > 0.15 else ("y" if rg > 0.03 else "r"), "Cuánto crecieron las ventas respecto del período anterior (último año fiscal o trimestre contra el mismo del año pasado, según la fuente)."))
    eg = f.get("earn_g")
    if eg is not None:
        out.append(light("Crecimiento de ganancias", _p(eg), "g" if eg > 0.15 else ("y" if eg > 0 else "r"), "Cuánto crecieron las ganancias respecto del período anterior (último año fiscal o trimestre contra el mismo del año pasado, según la fuente)."))
    mg = f.get("margin")
    if mg is not None:
        out.append(light("Margen de ganancia", _p(mg).replace("+", ""), "g" if mg > 0.20 else ("y" if mg > 0.08 else "r"), "De cada 100 dólares que vende, cuántos quedan como ganancia."))
    fp, pe = f.get("fpe"), f.get("pe")
    if fp is not None or pe is not None:
        v = fp if fp is not None else pe
        out.append(light("Precio / ganancias (P/E)", f"{_n(v, 1)}" + (" (esperado)" if fp is not None else ""),
            "g" if v <= 20 else ("y" if v <= 35 else "r"),
            f"Cuántas veces las ganancias anuales se pagan en el precio. Más alto = el mercado espera mucho crecimiento. Como referencia, el promedio histórico del mercado ronda 16–20." + (f" Con las ganancias de hoy: {_n(pe, 1)}." if fp is not None and pe is not None else "")))
    d = f.get("d2e")
    if d is not None:
        out.append(light("Deuda / capital", f"{_n(d, 0)}%", "g" if d < 50 else ("y" if d < 150 else "r"), "Cuánta deuda tiene en relación con su capital propio. Menos es más tranquilo."))
    if f.get("cash") is not None and f.get("debt") is not None:
        net = f["cash"] - f["debt"]
        out.append(light("Caja vs. deuda", _usd(net), "g" if net > 0 else "y", f"Caja {_usd(f['cash'])} y deuda {_usd(f['debt'])}. Positivo: tiene más plata que deudas."))
    rec = f.get("rec")
    if rec is not None:
        up = (f["target"] / price - 1) if f.get("target") and price else None
        lab = "Muy positivos" if rec <= 1.8 else ("Positivos" if rec <= 2.5 else ("Mixtos" if rec <= 3.3 else "Negativos"))
        out.append(light("Opinión de analistas", f"{lab} ({_n(rec, 1)} de 5)", "g" if rec <= 2.2 else ("y" if rec <= 3 else "r"),
            "Promedio de recomendaciones de analistas de bancos (1 = muy comprador, 5 = muy vendedor)." + (f" Precio objetivo promedio: US${_n(f['target'], 0)} ({_p(up, 0)} vs. hoy)." if up is not None else "") +
            " Ojo: los analistas suelen ir detrás del precio, no delante."))
    return out

def summary(t, f, tl, fl):
    a = []
    if t["sma200"]:
        a.append(f"El precio está {'arriba' if t['price'] > t['sma200'] else 'debajo'} de su promedio de 200 ruedas")
    if t["rsi"] is not None and (t["rsi"] >= 70 or t["rsi"] <= 30):
        a.append("viene " + ("sobrecomprada" if t["rsi"] >= 70 else "sobrevendida"))
    a.append(f"cotiza {_p(t['from_hi'], 0)} contra su máximo del año")
    s = ", ".join(a) + "."
    if fl:
        gg = sum(1 for x in fl if x["tone"] == "g"); rr = sum(1 for x in fl if x["tone"] == "r")
        s += f" En fundamentos, {gg} de {len(fl)} indicadores salen bien y {rr} salen flojos."
    if f and f.get("earn_ts") and f["earn_ts"] > time.time() - 86400:
        d = time.strftime("%d/%m/%Y", time.gmtime(f["earn_ts"]))
        s += f" Próximos resultados: {d}."
    return s


# ---------- entrada principal ----------
def analizar(ticker):
    ticker = ticker.upper()
    with _lock:
        hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    out = {"ticker": ticker, "asof": int(time.time()), "errors": []}
    h = fetch_history(ticker)
    t = technicals(h)
    out.update(name=h["name"], ccy=h["ccy"], price=h["price"] or t["price"], tech=t, tech_lights=tech_lights(t))
    f = None
    try:
        f = fetch_fundamentals(ticker)
        out["fund"] = f
        out["fund_lights"] = fund_lights(f, out["price"])
    except Exception as e:
        out["fund_lights"] = []
        out["errors"].append("Fundamentales no disponibles ahora: " + f"{type(e).__name__}")
    out["summary"] = summary(t, f, out["tech_lights"], out["fund_lights"])
    with _lock:
        _cache[ticker] = (time.time(), out)
    return out
