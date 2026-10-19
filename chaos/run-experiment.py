#!/usr/bin/env python3
"""
chaos/run-experiment.py — Orquestador de los experimentos de caos del Modulo D.

Sustituye a la orquestacion en bash, que resulto poco fiable: mezclar trabajos
en segundo plano, trap de rollback y docker run anidado producia bloqueos en los
que la fase de linea base se extendia mas de quince minutos y el rollback no
llegaba a ejecutarse, dejando la latencia inyectada activa.

Aqui el control de tiempos es explicito, la salida se vuelca sin buffer y el
rollback se ejecuta en un bloque finally que tambien cubre Ctrl-C.

Experimentos:
  d1  latencia de red de 200 ms en service-b mediante tc netem
  d2  tasa de error del 10 % en data-service mediante CHAOS_ERROR_RATE

Uso:
  chaos/run-experiment.py d1 --rps 3
  chaos/run-experiment.py d2 --rps 12
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROM = "http://localhost:9091"
RES = Path("chaos/results")
OBJETIVO_MTTD_S = 120

EXPERIMENTOS = {
    "d1": {
        "titulo": "latencia de red +200 ms en service-b",
        "alertas": ["EdgeLatencyDegraded", "EdgeLatencySLOBreach", "EdgeThroughputCollapse"],
    },
    "d2": {
        "titulo": "tasa de error 10 % en data-service",
        "alertas": ["DataServiceAnomalyCorrelated", "DataServiceErrorRateStatic"],
    },
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def correr(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── Inyeccion y rollback ────────────────────────────────────────────────────
def netem(accion, ms=200):
    base = ["docker", "run", "--rm", "--net", "container:service-b",
            "--cap-add", "NET_ADMIN", "nicolaka/netshoot", "tc", "qdisc"]
    if accion == "add":
        cmd = base + ["add", "dev", "eth0", "root", "netem", "delay", f"{ms}ms"]
    elif accion == "del":
        cmd = base + ["del", "dev", "eth0", "root"]
    else:
        cmd = base + ["show", "dev", "eth0"]
    return correr(cmd, timeout=90)


def recrear_data_service(error_rate, latency_ms):
    env = {"CHAOS_ERROR_RATE": str(error_rate), "CHAOS_LATENCY_MS": str(latency_ms)}
    import os
    entorno = {**os.environ, **env, "SIMULATE_DB_LATENCY": "false"}
    return subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", "--no-deps", "data-service"],
        capture_output=True, text=True, env=entorno, timeout=180)


# ── Consultas a Prometheus ──────────────────────────────────────────────────
def q(expr, instante=None):
    params = {"query": expr}
    if instante:
        params["time"] = instante
    url = f"{PROM}/api/v1/query?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as r:
        res = json.load(r)["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def alertas_activas():
    with urllib.request.urlopen(f"{PROM}/api/v1/alerts", timeout=15) as r:
        return json.load(r)["data"]["alerts"]


def epoch_de(s):
    s = s.replace("Z", "+00:00")
    if "." in s:
        cab, resto = s.split(".", 1)
        frac, _, zona = resto.partition("+")
        s = f"{cab}.{frac[:6]}+{zona}" if zona else f"{cab}.{frac[:6]}"
    return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()


def vigilar_mttd(t0, esperadas, duracion):
    """Sondea alertas durante la ventana de caos y devuelve el MTTD de cada una."""
    detectadas = {}
    fin = time.time() + duracion
    while time.time() < fin and len(detectadas) < len(esperadas):
        try:
            for a in alertas_activas():
                n = a["labels"].get("alertname")
                if n not in esperadas or n in detectadas or a.get("state") != "firing":
                    continue
                activo = epoch_de(a["activeAt"])
                if activo < t0:
                    continue          # ya estaba activa antes de inyectar
                mttd = round(activo - t0, 1)
                detectadas[n] = {
                    "mttd_segundos": mttd,
                    "objetivo_cumplido": mttd < OBJETIVO_MTTD_S,
                    "detector": a["labels"].get("detector"),
                    "severidad": a["labels"].get("severity"),
                }
                marca = "OK" if mttd < OBJETIVO_MTTD_S else "FUERA DE OBJETIVO"
                log(f"  ALERTA [{marca}] {n}: MTTD = {mttd}s")
        except Exception as exc:
            log(f"  aviso al consultar alertas: {exc}")
        time.sleep(2)
    return detectadas


def muestrear(etiqueta):
    """Instantanea de las senales clave del borde y de data-service."""
    return {
        "etiqueta": etiqueta,
        "p99_borde_s": q("edge:latency:p99_2m"),
        "media_borde_s": q("edge:latency:mean2m"),
        "umbral_2sigma_s": q("edge:latency:p99_threshold_2sigma"),
        "throughput_rps": q("edge:throughput:rps2m"),
        "throughput_base_rps": q("edge:throughput:baseline10m"),
        "error_rate_borde": q("edge:error_rate:ratio2m"),
        "error_rate_data_service": q("job:error_rate:ratio2m"),
        "p99_data_service_s": q("job:latency:p99_2m"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experimento", choices=sorted(EXPERIMENTOS))
    ap.add_argument("--rps", type=int, default=12)
    ap.add_argument("--base", type=int, default=150)
    ap.add_argument("--caos", type=int, default=180)
    ap.add_argument("--recup", type=int, default=120)
    ap.add_argument("--sufijo", default="")
    args = ap.parse_args()

    exp = args.experimento
    meta = EXPERIMENTOS[exp]
    nombre = f"{exp}{args.sufijo}"
    RES.mkdir(parents=True, exist_ok=True)

    total = args.base + args.caos + args.recup
    log(f"═══ {exp.upper()} — {meta['titulo']}")
    log(f"    carga {args.rps} req/s | base {args.base}s | caos {args.caos}s | recuperacion {args.recup}s")

    # Carga sostenida durante todo el experimento.
    k6_log = RES / f"k6_{nombre}.log"
    with open(k6_log, "w") as fh:
        # D2 inyecta el fallo en data-service, que bajo carga por la cadena no
        # recibe trafico: la cache de service-b absorbe las peticiones. Por eso
        # D2 dirige la carga directamente al servicio bajo prueba.
        target = "analytics" if exp == "d2" else "edge"
        k6 = subprocess.Popen(
            ["k6", "run", "--quiet", "--env", f"DURATION={total + 30}s",
             "--env", f"RPS={args.rps}", "--env", f"TARGET={target}",
             "chaos/load.js"],
            stdout=fh, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "FASE": nombre})
    log(f"    k6 arrancado (pid {k6.pid}) target={target}")

    inyectado = False
    try:
        # ── Fase 1: linea base ──────────────────────────────────────────────
        t_base_ini = time.time()
        log(f"[1/3] linea base {args.base}s...")
        time.sleep(args.base)
        t_base_fin = time.time()
        m_base = muestrear("base")
        log(f"      p99={m_base['p99_borde_s']} umbral={m_base['umbral_2sigma_s']} "
            f"rps={m_base['throughput_rps']}")

        # ── Fase 2: inyeccion ───────────────────────────────────────────────
        log(f"[2/3] inyectando: {meta['titulo']}")
        if exp == "d1":
            r = netem("add")
            if r.returncode != 0:
                log(f"      ERROR al inyectar: {r.stderr.strip()[:200]}")
                return 1
        else:
            r = recrear_data_service(0.10, 600)
            if r.returncode != 0:
                log(f"      ERROR al recrear: {r.stderr.strip()[:200]}")
                return 1
            time.sleep(8)
        inyectado = True
        t0 = time.time()
        log(f"      inyeccion activa en t0={int(t0)}")

        detectadas = vigilar_mttd(t0, meta["alertas"], args.caos)
        t_caos_fin = time.time()
        m_caos = muestrear("caos")
        log(f"      p99={m_caos['p99_borde_s']} umbral={m_caos['umbral_2sigma_s']} "
            f"rps={m_caos['throughput_rps']} err={m_caos['error_rate_borde']}")

        # ── Fase 3: rollback y recuperacion ─────────────────────────────────
        log(f"[3/3] rollback y recuperacion {args.recup}s...")
        if exp == "d1":
            netem("del")
        else:
            recrear_data_service(0, 0)
            time.sleep(8)
        inyectado = False
        t_recup_ini = time.time()
        time.sleep(args.recup)
        t_recup_fin = time.time()
        m_recup = muestrear("recuperacion")
        log(f"      p99={m_recup['p99_borde_s']} rps={m_recup['throughput_rps']}")

    finally:
        if inyectado:
            log("ROLLBACK de emergencia...")
            if exp == "d1":
                netem("del")
            else:
                recrear_data_service(0, 0)
        if k6.poll() is None:
            k6.terminate()
            try:
                k6.wait(timeout=60)
            except subprocess.TimeoutExpired:
                k6.kill()

    # ── Analisis de SLO por fase ────────────────────────────────────────────
    log("calculando SLO y error budget por fase...")
    fases = {"base": (t_base_ini, t_base_fin),
             "caos": (t0, t_caos_fin),
             "recuperacion": (t_recup_ini, t_recup_fin)}
    slo = {}
    for fase, (ini, fin) in fases.items():
        out = correr(["chaos/analyze-slo.py", "--inicio", str(ini), "--fin", str(fin),
                      "--etiqueta", f"{nombre}_{fase}"], timeout=120)
        try:
            slo[fase] = json.loads(out.stdout)
        except json.JSONDecodeError:
            slo[fase] = {"error": out.stdout[-300:] or out.stderr[-300:]}

    mejor = min((v["mttd_segundos"] for v in detectadas.values()), default=None)
    informe = {
        "experimento": exp.upper(),
        "fallo_inyectado": meta["titulo"],
        "rps_objetivo": args.rps,
        "fases_segundos": {"base": args.base, "caos": args.caos, "recuperacion": args.recup},
        "t0_epoch": t0,
        "t0_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
        "mttd": {
            "objetivo_segundos": OBJETIVO_MTTD_S,
            "primera_deteccion_segundos": mejor,
            "objetivo_cumplido": (mejor < OBJETIVO_MTTD_S) if mejor is not None else False,
            "por_alerta": detectadas,
            "no_detectadas": [a for a in meta["alertas"] if a not in detectadas],
        },
        "muestras": {"base": m_base, "caos": m_caos, "recuperacion": m_recup},
        "slo": slo,
        "ventanas_epoch": {k: {"inicio": v[0], "fin": v[1]} for k, v in fases.items()},
    }
    destino = RES / f"informe_{nombre}.json"
    destino.write_text(json.dumps(informe, indent=2, ensure_ascii=False))
    log(f"listo -> {destino}")

    print("\n" + "=" * 62)
    print(f" {exp.upper()} — MTTD primera deteccion: "
          f"{mejor if mejor is not None else 'NO DETECTADO'} s "
          f"(objetivo < {OBJETIVO_MTTD_S}s)")
    for n, v in detectadas.items():
        print(f"   {n:30s} {v['mttd_segundos']:6.1f}s  [{v['detector']}]")
    for n in informe["mttd"]["no_detectadas"]:
        print(f"   {n:30s}    ---   NO DISPARO")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
