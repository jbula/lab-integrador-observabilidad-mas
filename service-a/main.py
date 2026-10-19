"""
service-a: FastAPI — Orquestador principal
Recibe requests HTTP externos, hace llamadas a service-b y accede a PostgreSQL.
Instrumentado con OpenTelemetry (OTel) SDK: trazas, métricas y logs correlacionados.
"""

import logging
import os
import time
import json
import psycopg2
import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from pythonjsonlogger import jsonlogger

# ── OTel SDK: imports ────────────────────────────────────────────────────────
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.propagate import inject

# ── Configuración desde variables de entorno ─────────────────────────────────
OTEL_ENDPOINT   = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
SERVICE_B_URL   = os.getenv("SERVICE_B_URL", "http://service-b:8001")
DB_DSN          = os.getenv("DATABASE_URL", "postgresql://app:secret@postgres-a:5432/ordersdb")
ENV             = os.getenv("ENVIRONMENT", "production")
DB_HOST         = os.getenv("DB_HOST", "postgres-a")
DB_PORT         = int(os.getenv("DB_PORT", "5432"))
DB_NAME         = os.getenv("DB_NAME", "ordersdb")
APP_VERSION     = os.getenv("APP_VERSION", "1.0.0")
OTEL_ENABLED    = os.getenv("OTEL_ENABLED", "true").lower() == "true"  # baseline del benchmark

# ── 1. Resource: identidad del servicio en toda la telemetría ─────────────────
# El Resource viaja en cada señal (traza, métrica, log) para identificar el origen.
resource = Resource.create({
    SERVICE_NAME:    "service-a",
    SERVICE_VERSION: APP_VERSION,
    "deployment.environment": ENV,
    "cloud.provider": os.getenv("CLOUD_PROVIDER", "local"),
    "host.name":     os.getenv("HOSTNAME", "local"),
    # service.instance.id distingue cada PROCESO, no cada contenedor. Las
    # imagenes arrancan uvicorn con --workers 2, de modo que dentro de un mismo
    # contenedor hay dos procesos y cada uno crea su propio MeterProvider con un
    # contador acumulativo independiente. Como el resto de atributos de recurso
    # son identicos, ambos flujos colapsaban en la MISMA serie de Prometheus: el
    # exportador exponia alternadamente uno u otro, cada alternancia parecia un
    # reinicio de contador y rate() se inflaba de forma acumulativa (se midieron
    # 74 req/s sobre una carga real de 12). Al incluir el PID cada worker produce
    # su propia serie y las agregaciones con sum() vuelven a ser correctas.
    "service.instance.id": f"{os.getenv('HOSTNAME', 'local')}-{os.getpid()}",
})

# ── 2. TracerProvider + OTLP exporter (gRPC → OTel Collector) ────────────────
if OTEL_ENABLED:
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
    trace.set_tracer_provider(tracer_provider)
else:
    tracer_provider = None
tracer = trace.get_tracer("service-a", APP_VERSION)

# ── Buckets EXPLICITOS de latencia (5 ms .. 2.5 s) ───────────────────────────
# Sin esta View el SDK aplica sus fronteras por defecto, que estan expresadas en
# MILISEGUNDOS (0, 5, 10, ... 10000). Como los instrumentos registran SEGUNDOS,
# toda observacion caia en el primer bucket y histogram_quantile devolvia un
# valor fijo de ~4.95 s: el histograma quedaba sin resolucion y una inyeccion de
# 200 ms resultaba invisible. Estas fronteras coinciden con las de data-service
# para que los tres servicios sean comparables.
# El techo del histograma debe quedar POR ENCIMA del timeout del cliente. Con
# el techo anterior en 2.5 s, una degradacion que llevaba la latencia real por
# encima de ese valor dejaba a histogram_quantile sin margen de interpolacion y
# devolvia 2.5 s de forma constante. Peor aun: la linea base movil se envenenaba
# con ese mismo 2.5 s, de modo que la condicion p99 > base + 2*sigma pasaba a ser
# 2.5 > 2.5, siempre falsa, y el detector de anomalias se desactivaba solo justo
# cuando mas se necesitaba. Se extiende a 10 s, por encima del timeout de 5 s del
# cliente httpx interno.
LATENCY_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

# ── 3. MeterProvider + OTLP metric exporter (push al Collector cada 15s) ──────
# Las métricas se exponen en formato Prometheus desde el Collector (:8889), no por-servicio
if OTEL_ENABLED:
    otlp_metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True), export_interval_millis=15000)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[otlp_metric_reader],
        views=[
            View(
                instrument_name="*duration_seconds",
                aggregation=ExplicitBucketHistogramAggregation(boundaries=LATENCY_BUCKETS),
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)
else:
    meter_provider = None
meter = metrics.get_meter("service-a", APP_VERSION)

# ── 4. Instrumentos de métricas (SLIs) ───────────────────────────────────────
http_requests_total = meter.create_counter(
    "http_requests_total",
    description="Total HTTP requests recibidos por service-a",
    unit="1",
)
http_request_duration = meter.create_histogram(
    "http_request_duration_seconds",
    description="Distribución de latencia de requests HTTP (p50/p95/p99)",
    unit="s",
)
db_query_duration = meter.create_histogram(
    "db_query_duration_seconds",
    description="Latencia de queries a PostgreSQL",
    unit="s",
)
service_b_calls_total = meter.create_counter(
    "service_b_calls_total",
    description="Llamadas HTTP a service-b",
    unit="1",
)
active_requests = meter.create_up_down_counter(
    "http_active_requests",
    description="Requests activos en vuelo (saturación)",
    unit="1",
)

# ── 5. Logging estructurado JSON con trace_id/span_id ────────────────────────
# El trace_id en el log es el PUENTE que correlaciona log ↔ traza en Grafana.
class OtelJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            # Formato hexadecimal de 32 dígitos para trace_id (estándar W3C)
            log_record["trace_id"] = format(ctx.trace_id, "032x")
            log_record["span_id"]  = format(ctx.span_id, "016x")
        log_record["service"]     = "service-a"
        log_record["version"]     = APP_VERSION
        log_record["environment"] = ENV

handler = logging.StreamHandler()
handler.setFormatter(OtelJsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("service-a")

# ── 6. Auto-instrumentación de librerías ─────────────────────────────────────
# FastAPIInstrumentor crea spans automáticos para cada endpoint HTTP
# HTTPXClientInstrumentor propaga el W3C TraceContext hacia service-b
# Psycopg2Instrumentor crea spans para cada query SQL
if OTEL_ENABLED:
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
    Psycopg2Instrumentor().instrument(tracer_provider=tracer_provider)

# ── Conexión DB ───────────────────────────────────────────────────────────────
def get_db_connection():
    return psycopg2.connect(DB_DSN)

# ── FastAPI App ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Telemetry started: metrics via OTLP push to Collector", extra={"otlp_endpoint": OTEL_ENDPOINT})
    yield
    # Shutdown: flushar todos los spans pendientes
    if OTEL_ENABLED:
        tracer_provider.shutdown()
        meter_provider.shutdown()

app = FastAPI(
    title="Service A",
    description="Microservicio orquestador — OTel end-to-end lab",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Instrumentar la app EXPLÍCITAMENTE tras crearla (robusto vs .instrument() global).
# Crea el span servidor raíz y extrae/propaga el W3C traceparent.
if OTEL_ENABLED:
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — no genera trazas (excluido en el Collector)."""
    return {"status": "ok", "service": "service-a"}


@app.get("/order/{order_id}")
async def get_order(order_id: str, request: Request):
    """
    Flujo principal:
    1. Consulta la DB para obtener metadatos del pedido (custom span: fetch.order.db)
    2. Llama a service-b para enriquecer con datos de inventario (propagación W3C)
    3. Retorna la respuesta consolidada
    """
    start = time.time()
    labels = {"endpoint": "/order", "method": "GET"}
    # El contador y el histograma se emiten UNA sola vez, en el bloque finally,
    # para que toda peticion quede contabilizada con su etiqueta status. Antes
    # se incrementaba al entrar (sin status) y de nuevo al salir, de modo que
    # las respuestas 2xx se contaban doble y los 404 no aparecian con status.
    status = "5xx"
    active_requests.add(1, labels)

    try:
        # ── Custom span: lógica de negocio DB ────────────────────────────────
        with tracer.start_as_current_span(
            "fetch.order.db",
            kind=trace.SpanKind.CLIENT,
            attributes={
                "db.system":    "postgresql",
                "db.operation": "SELECT",
                "db.name":      DB_NAME,
                "db.sql.table": "orders",
                "server.address": DB_HOST,
                "server.port":  DB_PORT,
                "order.id":     order_id,
            }
        ) as db_span:
            db_start = time.time()
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, product, quantity, status FROM orders WHERE id = %s",
                    (order_id,)
                )
                row = cur.fetchone()
                conn.close()

                db_duration = time.time() - db_start
                db_query_duration.record(db_duration, {"operation": "SELECT", "table": "orders"})

                if not row:
                    db_span.set_status(trace.StatusCode.ERROR, "Order not found")
                    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

                order_data = {
                    "id":       row[0],
                    "product":  row[1],
                    "quantity": row[2],
                    "status":   row[3],
                }
                db_span.set_attribute("order.status", order_data["status"])
                logger.info("Order fetched from DB", extra={"order_id": order_id, "status": order_data["status"]})

            except HTTPException:
                raise
            except Exception as e:
                db_span.record_exception(e)
                db_span.set_status(trace.StatusCode.ERROR, str(e))
                logger.error("DB query failed", extra={"error": str(e), "order_id": order_id})
                raise HTTPException(status_code=500, detail="Database error")

        # ── Llamada a service-b (propagación automática de trace context) ────
        with tracer.start_as_current_span(
            "call.service-b.inventory",
            kind=trace.SpanKind.CLIENT,
            attributes={
                "http.method": "GET",
                "peer.service": "service-b",
                "order.product": order_data["product"],
            }
        ) as sb_span:
            service_b_calls_total.add(1, {"status": "attempt"})
            try:
                # HTTPXClientInstrumentor inyecta automáticamente el header
                # traceparent: 00-{trace_id}-{span_id}-01 (W3C TraceContext)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = {}
                    inject(headers)  # propagación explícita como fallback
                    resp = await client.get(
                        f"{SERVICE_B_URL}/inventory/{order_data['product']}",
                        headers=headers,
                    )
                    resp.raise_for_status()
                    inventory = resp.json()

                service_b_calls_total.add(1, {"status": "success"})
                sb_span.set_attribute("http.status_code", resp.status_code)
                sb_span.set_attribute("inventory.available", inventory.get("available", 0))
                logger.info("Inventory fetched from service-b",
                            extra={"product": order_data["product"], "available": inventory.get("available")})
                status = "2xx"
            except httpx.HTTPStatusError as e:
                service_b_calls_total.add(1, {"status": "error"})
                sb_span.record_exception(e)
                sb_span.set_status(trace.StatusCode.ERROR, str(e))
                status = f"{e.status_code // 100}xx"
                logger.error("service-b call failed", extra={"error": str(e)})
                inventory = {"available": -1, "error": "service-b unavailable"}

        return {
            "order":     order_data,
            "inventory": inventory,
            "trace_id":  format(trace.get_current_span().get_span_context().trace_id, "032x"),
        }

    except HTTPException as exc:
        # Captura 404 (pedido inexistente) y 500 (fallo de DB) para que queden
        # reflejados en el SLI de errores del borde, y re-lanza sin alterar la
        # respuesta al cliente.
        status = f"{exc.status_code // 100}xx"
        raise

    finally:
        active_requests.add(-1, labels)
        status_labels = {**labels, "status": status}
        http_requests_total.add(1, status_labels)
        http_request_duration.record(time.time() - start, status_labels)


@app.get("/metrics/health")
async def metrics_health():
    """Estado del pipeline de telemetría."""
    return {
        "otel_collector": OTEL_ENDPOINT,
        "service_b_url": SERVICE_B_URL,
    }
