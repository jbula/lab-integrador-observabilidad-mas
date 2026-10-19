"""
alert-enricher — Enriquecimiento de alertas con trace_id (Lab 4, Modulo B)

Problema que resuelve: Prometheus y Alertmanager no transportan identificadores
de traza. Una alerta que solo dice "la tasa de error subio" no es accionable,
porque no indica que peticion fallo.

Este servicio recibe el webhook de Alertmanager, consulta Loki por la ultima
linea de log con error del servicio afectado, extrae su trace_id y emite la
alerta enriquecida con un enlace directo a la traza en Jaeger.
"""

import json
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from pythonjsonlogger import jsonlogger

LOKI_URL     = os.getenv("LOKI_URL", "http://loki:3100")
JAEGER_UI    = os.getenv("JAEGER_UI_URL", "http://localhost:16686")
LOOKBACK_S   = int(os.getenv("LOOKBACK_SECONDS", "300"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9099"))

handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("alert-enricher")

app = FastAPI(title="Alert Enricher", version="1.0.0")

# Contadores expuestos en formato Prometheus para el dashboard de AIOps.
_counters = {"enriched_with_trace": 0, "enriched_without_trace": 0, "alerts_received": 0}


async def find_trace_id(service: str) -> Optional[str]:
    """Busca en Loki el trace_id del ultimo log de error del servicio."""
    end = int(time.time() * 1_000_000_000)
    start = end - (LOOKBACK_S * 1_000_000_000)
    # Se filtra por nivel de error y se exige que el trace_id no este vacio.
    query = '{service="%s"} | json | trace_id != ""' % service
    params = {"query": query, "start": str(start), "end": str(end), "limit": "20", "direction": "backward"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params)
            resp.raise_for_status()
            streams = resp.json().get("data", {}).get("result", [])
    except Exception as exc:
        logger.error("Consulta a Loki fallida", extra={"error": str(exc)})
        return None

    # Se prioriza una linea que represente un error real.
    fallback = None
    for stream in streams:
        for _ts, line in stream.get("values", []):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = rec.get("trace_id")
            if not tid or tid == "0" * 32:
                continue
            level = str(rec.get("levelname", "")).upper()
            if level in ("ERROR", "CRITICAL"):
                return tid
            fallback = fallback or tid
    return fallback


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    alerts = payload.get("alerts", [])
    _counters["alerts_received"] += len(alerts)
    enriched = []

    for alert in alerts:
        labels = alert.get("labels", {})
        service = labels.get("service_name", "data-service")
        trace_id = await find_trace_id(service)

        annotations = dict(alert.get("annotations", {}))
        if trace_id:
            annotations["trace_id"] = trace_id
            annotations["trace_url"] = f"{JAEGER_UI}/trace/{trace_id}"
            _counters["enriched_with_trace"] += 1
        else:
            annotations["trace_id"] = "no_encontrado"
            annotations["enrichment_note"] = "Sin traza correlacionada en la ventana consultada"
            _counters["enriched_without_trace"] += 1

        record = {
            "alertname": labels.get("alertname"),
            "detector": labels.get("detector"),
            "severity": labels.get("severity"),
            "service": service,
            "status": alert.get("status"),
            "startsAt": alert.get("startsAt"),
            "annotations": annotations,
        }
        enriched.append(record)
        # La alerta enriquecida se emite como log estructurado: queda en Loki y
        # es consultable y correlacionable igual que el resto de la telemetria.
        logger.warning("Alerta enriquecida", extra=record)

    return {"received": len(alerts), "enriched": enriched}


@app.get("/metrics")
async def metrics():
    """Metricas en formato de exposicion Prometheus."""
    lines = [
        "# HELP alerts_received_total Alertas recibidas desde Alertmanager",
        "# TYPE alerts_received_total counter",
        f'alerts_received_total {_counters["alerts_received"]}',
        "# HELP alerts_enriched_total Alertas enriquecidas, por disponibilidad de trace_id",
        "# TYPE alerts_enriched_total counter",
        f'alerts_enriched_total{{has_trace_id="true"}} {_counters["enriched_with_trace"]}',
        f'alerts_enriched_total{{has_trace_id="false"}} {_counters["enriched_without_trace"]}',
    ]
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "alert-enricher"}
