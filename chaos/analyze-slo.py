#!/usr/bin/env python3
"""
chaos/analyze-slo.py — Analiza degradacion de SLO y consumo de error budget
para una ventana temporal de experimento.

Define dos SLI, ambos con SLO del 99 % sobre una ventana de 30 dias:

  Disponibilidad : fraccion de peticiones que NO devuelven 4xx/5xx.
  Latencia       : fraccion de peticiones servidas en 500 ms o menos. Se calcula
                   desde el bucket le="0.5" del histograma, que es la forma
                   correcta de expresar un SLI de latencia; el percentil 99 por
                   si solo no permite contabilizar error budget porque no dice
                   QUE FRACCION de peticiones incumplio el objetivo.

Error budget: con un SLO del 99 % sobre 30 dias, el presupuesto es del 1 %,
equivalente a 432 minutos. El consumo de una ventana degradada es
(duracion_ventana * fraccion_incumplida), expresado como porcentaje de 432 min.

Uso:
  chaos/analyze-slo.py --inicio <epoch> --fin <epoch> \
      --etiqueta d1_caos --salida chaos/results/slo_d1_caos.json
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PROM = "http://localhost:9091"
SLO_OBJETIVO = 0.99
SLO_LATENCIA_S = 0.5
VENTANA_SLO_DIAS = 30
BUDGET_MINUTOS = (1 - SLO_OBJETIVO) * VENTANA_SLO_DIAS * 24 * 60   # 432 min


def consultar(expr: str, instante: float):
    params = urllib.parse.urlencode({"query": expr, "time": instante})
    with urllib.request.urlopen(f"{PROM}/api/v1/query?{params}", timeout=15) as r:
        res = json.load(r)["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def incremento(metric: str, inicio: float, fin: float):
    """increase() sobre la ventana exacta del experimento."""
    dur = max(int(fin - inicio), 1)
    return consultar(f"sum(increase({metric}[{dur}s])) or vector(0)", fin)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", type=float, required=True)
    ap.add_argument("--fin", type=float, required=True)
    ap.add_argument("--etiqueta", required=True)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    dur_s = args.fin - args.inicio
    dur_min = dur_s / 60.0

    total = incremento('otelcol_http_requests_total{service_name="service-a"}',
                       args.inicio, args.fin) or 0.0
    errores = incremento(
        'otelcol_http_requests_total{service_name="service-a",status=~"4xx|5xx"}',
        args.inicio, args.fin) or 0.0

    bucket_total = incremento(
        'otelcol_http_request_duration_seconds_count{service_name="service-a"}',
        args.inicio, args.fin) or 0.0
    bucket_rapidas = incremento(
        'otelcol_http_request_duration_seconds_bucket{service_name="service-a",le="0.5"}',
        args.inicio, args.fin) or 0.0

    # --- SLI de disponibilidad ---
    if total > 0:
        sli_disp = 1 - (errores / total)
    else:
        sli_disp = None

    # --- SLI de latencia ---
    if bucket_total > 0:
        sli_lat = bucket_rapidas / bucket_total
    else:
        sli_lat = None

    def budget(sli):
        """Minutos de presupuesto consumidos y su porcentaje sobre 432 min."""
        if sli is None:
            return None
        incumplido = max(0.0, 1 - sli)
        minutos = dur_min * incumplido
        return {
            "fraccion_incumplida": round(incumplido, 6),
            "minutos_consumidos": round(minutos, 4),
            "pct_del_budget_mensual": round(100 * minutos / BUDGET_MINUTOS, 4),
        }

    p99 = consultar("edge:latency:p99_2m", args.fin)
    umbral_2sigma = consultar("edge:latency:p99_threshold_2sigma", args.fin)

    r = {
        "etiqueta": args.etiqueta,
        "ventana": {
            "inicio_utc": datetime.fromtimestamp(args.inicio, timezone.utc).isoformat(),
            "fin_utc": datetime.fromtimestamp(args.fin, timezone.utc).isoformat(),
            "duracion_segundos": round(dur_s, 1),
        },
        "trafico": {"peticiones": round(total, 1), "errores": round(errores, 1)},
        "slo": {
            "objetivo": SLO_OBJETIVO,
            "umbral_latencia_segundos": SLO_LATENCIA_S,
            "budget_mensual_minutos": BUDGET_MINUTOS,
        },
        "disponibilidad": {
            "sli": round(sli_disp, 6) if sli_disp is not None else None,
            "slo_cumplido": (sli_disp >= SLO_OBJETIVO) if sli_disp is not None else None,
            "error_budget": budget(sli_disp),
        },
        "latencia": {
            "sli_fraccion_bajo_500ms": round(sli_lat, 6) if sli_lat is not None else None,
            "slo_cumplido": (sli_lat >= SLO_OBJETIVO) if sli_lat is not None else None,
            "error_budget": budget(sli_lat),
            "p99_observado_segundos": round(p99, 4) if p99 is not None else None,
            "umbral_2sigma_segundos": round(umbral_2sigma, 4) if umbral_2sigma is not None else None,
        },
    }

    if args.salida:
        with open(args.salida, "w") as fh:
            json.dump(r, fh, indent=2, ensure_ascii=False)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
