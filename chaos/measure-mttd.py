#!/usr/bin/env python3
"""
chaos/measure-mttd.py — Mide el Mean Time To Detect de un experimento de caos.

Compara el instante de inyeccion del fallo (t0) con el instante en que cada
alerta pasa a estado 'firing', consultando la API de Prometheus.

El MTTD se calcula contra el campo 'activeAt' que reporta Prometheus, no contra
el momento en que este script observa la alerta. Son cosas distintas: activeAt
es cuando la condicion empezo a cumplirse, mientras que el momento de
observacion depende del intervalo de sondeo de este script. Usar activeAt evita
inflar el MTTD con el error de muestreo del propio medidor.

Uso:
  chaos/measure-mttd.py --t0 1792300000 \
      --alerts EdgeLatencyDegraded,EdgeLatencySLOBreach \
      --timeout 300 --salida chaos/results/mttd_d1.json
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

PROM = "http://localhost:9091"
OBJETIVO_MTTD_S = 120  # objetivo declarado: deteccion en menos de 2 minutos


def consultar_alertas():
    with urllib.request.urlopen(f"{PROM}/api/v1/alerts", timeout=10) as r:
        return json.load(r)["data"]["alerts"]


def epoch_de(active_at: str) -> float:
    """Convierte el activeAt de Prometheus (RFC3339, con o sin nanosegundos)."""
    s = active_at.replace("Z", "+00:00")
    # Python no acepta mas de 6 decimales en los segundos.
    if "." in s:
        cabeza, resto = s.split(".", 1)
        frac, _, zona = resto.partition("+")
        s = f"{cabeza}.{frac[:6]}+{zona}" if zona else f"{cabeza}.{frac[:6]}"
    return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t0", type=float, required=True,
                    help="epoch del instante de inyeccion")
    ap.add_argument("--alerts", required=True,
                    help="nombres de alerta separados por coma")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--intervalo", type=float, default=2.0)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    esperadas = [a.strip() for a in args.alerts.split(",") if a.strip()]
    detectadas: dict[str, dict] = {}

    print(f"Esperando alertas {esperadas} (timeout {args.timeout}s)...", flush=True)

    inicio = time.time()
    while time.time() - inicio < args.timeout and len(detectadas) < len(esperadas):
        try:
            alertas = consultar_alertas()
        except Exception as exc:                      # Prometheus reiniciando, etc.
            print(f"  aviso: no se pudo consultar la API ({exc})", flush=True)
            time.sleep(args.intervalo)
            continue

        for a in alertas:
            nombre = a["labels"].get("alertname")
            if nombre not in esperadas or nombre in detectadas:
                continue
            if a.get("state") != "firing":
                continue
            activo = epoch_de(a["activeAt"])
            # Descarta alertas que ya estaban activas antes de la inyeccion:
            # su MTTD no seria atribuible a este experimento.
            if activo < args.t0:
                continue
            mttd = round(activo - args.t0, 1)
            detectadas[nombre] = {
                "mttd_segundos": mttd,
                "objetivo_cumplido": mttd < OBJETIVO_MTTD_S,
                "detector": a["labels"].get("detector"),
                "severidad": a["labels"].get("severity"),
                "activo_desde": a["activeAt"],
            }
            marca = "OK" if mttd < OBJETIVO_MTTD_S else "FUERA DE OBJETIVO"
            print(f"  [{marca}] {nombre}: MTTD = {mttd}s "
                  f"(detector {a['labels'].get('detector')})", flush=True)

        if len(detectadas) < len(esperadas):
            time.sleep(args.intervalo)

    no_detectadas = [a for a in esperadas if a not in detectadas]
    for nombre in no_detectadas:
        print(f"  [NO DETECTADA] {nombre}: sin firing en {args.timeout}s", flush=True)

    resultado = {
        "t0_epoch": args.t0,
        "t0_utc": datetime.fromtimestamp(args.t0, timezone.utc).isoformat(),
        "objetivo_mttd_segundos": OBJETIVO_MTTD_S,
        "alertas_esperadas": esperadas,
        "detectadas": detectadas,
        "no_detectadas": no_detectadas,
    }
    if detectadas:
        mejor = min(v["mttd_segundos"] for v in detectadas.values())
        resultado["mttd_primera_deteccion_segundos"] = mejor
        resultado["objetivo_global_cumplido"] = mejor < OBJETIVO_MTTD_S

    if args.salida:
        with open(args.salida, "w") as fh:
            json.dump(resultado, fh, indent=2, ensure_ascii=False)
        print(f"Resultado escrito en {args.salida}")

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0 if detectadas else 1


if __name__ == "__main__":
    sys.exit(main())
