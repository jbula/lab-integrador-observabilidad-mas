"""
service-b: FastAPI — Servicio de inventario
Recibe llamadas de service-a, consulta inventario en PostgreSQL.
Continúa el trace distribuido iniciado por service-a mediante W3C TraceContext.
"""

import logging
import os
import time
import random
import httpx
import psycopg2

from fastapi import FastAPI, HTTPException
from pythonjsonlogger import jsonlogger
from contextlib import asynccontextmanager

# ── OTel SDK ─────────────────────────────────────────────────────────────────
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

# ── Config ────────────────────────────────────────────────────────────────────
OTEL_ENDPOINT   = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
DB_DSN          = os.getenv("DATABASE_URL", "postgresql://app:secret@postgres-b:5432/inventorydb")
ENV             = os.getenv("ENVIRONMENT", "production")
APP_VERSION     = os.getenv("APP_VERSION", "1.0.0")
OTEL_ENABLED    = os.getenv("OTEL_ENABLED", "true").lower() == "true"
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data-service:8002")
DB_HOST         = os.getenv("DB_HOST", "postgres-b")
DB_PORT         = int(os.getenv("DB_PORT", "5432"))
DB_NAME         = os.getenv("DB_NAME", "inventorydb")  # baseline del benchmark

# ── OTel Resource ─────────────────────────────────────────────────────────────
resource = Resource.create({
    SERVICE_NAME:    "service-b",
    SERVICE_VERSION: APP_VERSION,
    "deployment.environment": ENV,
    "cloud.provider": os.getenv("CLOUD_PROVIDER", "local"),
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

# ── TracerProvider ────────────────────────────────────────────────────────────
if OTEL_ENABLED:
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
    trace.set_tracer_provider(tracer_provider)
else:
    tracer_provider = None
tracer = trace.get_tracer("service-b", APP_VERSION)

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

# ── MeterProvider ─────────────────────────────────────────────────────────────
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
meter = metrics.get_meter("service-b", APP_VERSION)

# ── Instrumentos de métricas ──────────────────────────────────────────────────
inventory_requests = meter.create_counter(
    "inventory_requests_total",
    description="Total consultas de inventario procesadas",
    unit="1",
)
inventory_query_duration = meter.create_histogram(
    "inventory_query_duration_seconds",
    description="Latencia de consultas de inventario a PostgreSQL",
    unit="s",
)
data_service_calls_total = meter.create_counter(
    "data_service_calls_total",
    description="Llamadas HTTP a data-service",
    unit="1",
)
cache_hits = meter.create_counter(
    "inventory_cache_hits_total",
    description="Cache hits en consultas de inventario (en memoria)",
    unit="1",
)

# ── Logging estructurado con trace_id ─────────────────────────────────────────
class OtelJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            log_record["trace_id"] = format(ctx.trace_id, "032x")
            log_record["span_id"]  = format(ctx.span_id, "016x")
        log_record["service"]     = "service-b"
        log_record["environment"] = ENV

handler = logging.StreamHandler()
handler.setFormatter(OtelJsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("service-b")

# ── Auto-instrumentación ──────────────────────────────────────────────────────
# FastAPIInstrumentor: extrae automáticamente el header traceparent
# y continúa el trace iniciado por service-a — sin ninguna línea extra de código.
if OTEL_ENABLED:
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
    Psycopg2Instrumentor().instrument(tracer_provider=tracer_provider)

# ── Cache en memoria (simulación) ─────────────────────────────────────────────
_inventory_cache: dict[str, dict] = {}

def get_db_connection():
    return psycopg2.connect(DB_DSN)

# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Telemetry started: metrics via OTLP push to Collector", extra={"otlp_endpoint": OTEL_ENDPOINT})
    yield
    if OTEL_ENABLED:
        tracer_provider.shutdown()
        meter_provider.shutdown()

app = FastAPI(
    title="Service B",
    description="Microservicio de inventario — OTel end-to-end lab",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Instrumentar la app EXPLÍCITAMENTE tras crearla: extrae el traceparent de service-a.
if OTEL_ENABLED:
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "service-b"}


@app.get("/inventory/{product_id}")
async def get_inventory(product_id: str):
    """
    Retorna disponibilidad de inventario para un producto.
    El trace_id es el MISMO que el de service-a — propagado vía W3C TraceContext.
    El flame graph en Jaeger mostrará este span como hijo del span de service-a.
    """
    start = time.time()
    inventory_requests.add(1, {"product": product_id})

    # ── Verificar cache en memoria ────────────────────────────────────────────
    if product_id in _inventory_cache:
        with tracer.start_as_current_span(
            "inventory.cache.hit",
            attributes={"cache.type": "in-memory", "product.id": product_id}
        ):
            cache_hits.add(1, {"product": product_id})
            logger.info("Cache hit", extra={"product_id": product_id})
            return _inventory_cache[product_id]

    # ── Custom span: consulta DB de inventario ────────────────────────────────
    with tracer.start_as_current_span(
        "inventory.db.fetch",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "db.system":    "postgresql",
            "db.operation": "SELECT",
            "db.name":      DB_NAME,
            "db.sql.table": "inventory",
            "server.address": DB_HOST,
            "server.port":  DB_PORT,
            "product.id":   product_id,
        }
    ) as span:
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # Latencia de DB simulada; se desactiva en el benchmark para aislar overhead del SDK
            if os.getenv("SIMULATE_DB_LATENCY", "true").lower() == "true":
                time.sleep(random.uniform(0.01, 0.15))

            cur.execute(
                "SELECT product_id, available, warehouse, last_updated "
                "FROM inventory WHERE product_id = %s",
                (product_id,)
            )
            row = cur.fetchone()
            conn.close()

            duration = time.time() - start
            inventory_query_duration.record(duration, {"operation": "SELECT"})

            if not row:
                span.set_status(trace.StatusCode.ERROR, "Product not found")
                raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

            result = {
                "product_id":   row[0],
                "available":    row[1],
                "warehouse":    row[2],
                "last_updated": str(row[3]),
            }

            span.set_attribute("inventory.available", result["available"])
            span.set_attribute("inventory.warehouse", result["warehouse"])
            span.set_status(trace.StatusCode.OK)

            # ── Tercer salto: enriquecer con analitica de data-service ──────
            # Propaga el traceparent W3C automaticamente (HTTPXClientInstrumentor).
            with tracer.start_as_current_span(
                "call.data-service.analytics",
                kind=trace.SpanKind.CLIENT,
                attributes={"peer.service": "data-service", "product.id": product_id},
            ) as ds_span:
                data_service_calls_total.add(1, {"status": "attempt"})
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get(f"{DATA_SERVICE_URL}/analytics/{product_id}")
                        resp.raise_for_status()
                        result["analytics"] = resp.json()
                    data_service_calls_total.add(1, {"status": "success"})
                    ds_span.set_status(trace.StatusCode.OK)
                except httpx.HTTPStatusError as exc:
                    # data-service respondio con error (incluye el caos del Modulo D)
                    data_service_calls_total.add(1, {"status": "error"})
                    ds_span.record_exception(exc)
                    ds_span.set_status(trace.StatusCode.ERROR, str(exc))
                    result["analytics"] = {"error": "data-service error", "degraded": True}
                    logger.error("data-service respondio con error",
                                 extra={"product_id": product_id, "status_code": exc.response.status_code})
                except httpx.RequestError as exc:
                    # Indisponibilidad o timeout. Capturar RequestError (clase padre de
                    # ConnectError y TimeoutException) evita el fallo en cascada que el
                    # Game Day del Lab 3 revelo en service-a.
                    data_service_calls_total.add(1, {"status": "unavailable"})
                    ds_span.record_exception(exc)
                    ds_span.set_status(trace.StatusCode.ERROR, str(exc))
                    result["analytics"] = {"error": "data-service unavailable", "degraded": True}
                    logger.error("data-service inalcanzable",
                                 extra={"product_id": product_id, "error": type(exc).__name__})

            # Actualizar cache
            _inventory_cache[product_id] = result

            logger.info(
                "Inventory fetched from DB",
                extra={
                    "product_id": product_id,
                    "available":  result["available"],
                    "duration_s": round(duration, 4),
                }
            )
            return result

        except HTTPException:
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.error("Inventory DB query failed", extra={"error": str(e), "product_id": product_id})
            raise HTTPException(status_code=500, detail="Inventory service error")


@app.post("/inventory/{product_id}/reserve")
async def reserve_inventory(product_id: str, quantity: int = 1):
    """
    Custom span de lógica de negocio: reservar unidades de inventario.
    Demuestra spans anidados en el mismo servicio.
    """
    with tracer.start_as_current_span(
        "inventory.business.reserve",
        attributes={
            "product.id":        product_id,
            "reservation.units": quantity,
        }
    ) as span:
        logger.info("Reserving inventory", extra={"product_id": product_id, "quantity": quantity})

        # Simular validación de negocio
        with tracer.start_as_current_span("inventory.validate.stock") as val_span:
            time.sleep(random.uniform(0.005, 0.02))
            available = random.randint(0, 100)
            val_span.set_attribute("stock.available", available)

            if available < quantity:
                val_span.set_status(trace.StatusCode.ERROR, "Insufficient stock")
                span.set_status(trace.StatusCode.ERROR, "Reservation failed")
                raise HTTPException(status_code=409, detail="Insufficient stock")

        span.set_attribute("reservation.approved", True)
        span.set_status(trace.StatusCode.OK)

        # Invalidar cache
        _inventory_cache.pop(product_id, None)

        return {"reserved": quantity, "product_id": product_id, "status": "confirmed"}
