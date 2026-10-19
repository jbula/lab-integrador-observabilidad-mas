"""
data-service: FastAPI — Servicio de analitica (Lab 4, Modulo A)

Tercer salto de la cadena: service-a -> service-b -> data-service -> analyticsdb.
Instrumentado con OTel SDK (3 pilares) e incluye:
  - Database spans con OTel DB Semantic Conventions completas.
  - Histogramas con buckets explicitos acordes a la escala real del servicio
    (corrige la limitacion detectada en el Lab 3, donde los buckets por defecto
    en segundos hacian que p99 devolviera un valor constante).
  - Endpoint de autenticacion sintetica para los Golden Signals de seguridad (Modulo C).
  - Inyeccion de error controlada por variable de entorno para el caos (Modulo D).
"""

import hashlib
import logging
import os
import random
import time
from contextlib import asynccontextmanager

import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pythonjsonlogger import jsonlogger

# ── OTel SDK ─────────────────────────────────────────────────────────────────
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# ── Configuracion ────────────────────────────────────────────────────────────
OTEL_ENDPOINT    = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
DB_DSN           = os.getenv("DATABASE_URL", "postgresql://app:secret@postgres-d:5432/analyticsdb")
DB_HOST          = os.getenv("DB_HOST", "postgres-d")
DB_PORT          = int(os.getenv("DB_PORT", "5432"))
DB_NAME          = os.getenv("DB_NAME", "analyticsdb")
DB_USER          = os.getenv("DB_USER", "app")
ENV              = os.getenv("ENVIRONMENT", "development")
APP_VERSION      = os.getenv("APP_VERSION", "1.0.0")
OTEL_ENABLED     = os.getenv("OTEL_ENABLED", "true").lower() == "true"
CHAOS_ERROR_RATE = float(os.getenv("CHAOS_ERROR_RATE", "0"))   # Modulo D: 0.10 = 10 %
CHAOS_LATENCY_MS = float(os.getenv("CHAOS_LATENCY_MS", "0"))   # degrada tambien la latencia
PBKDF2_SALT      = os.getenv("AUTH_SALT", "otel-lab-salt").encode()
PBKDF2_ROUNDS    = 100_000

# ── Resource ─────────────────────────────────────────────────────────────────
resource = Resource.create({
    SERVICE_NAME:    "data-service",
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

# ── Trazas ───────────────────────────────────────────────────────────────────
if OTEL_ENABLED:
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)
else:
    tracer_provider = None
tracer = trace.get_tracer("data-service", APP_VERSION)

# ── Metricas con buckets EXPLICITOS (5 ms .. 2.5 s) ──────────────────────────
# El techo del histograma debe quedar POR ENCIMA del timeout del cliente. Con
# el techo anterior en 2.5 s, una degradacion que llevaba la latencia real por
# encima de ese valor dejaba a histogram_quantile sin margen de interpolacion y
# devolvia 2.5 s de forma constante. Peor aun: la linea base movil se envenenaba
# con ese mismo 2.5 s, de modo que la condicion p99 > base + 2*sigma pasaba a ser
# 2.5 > 2.5, siempre falsa, y el detector de anomalias se desactivaba solo justo
# cuando mas se necesitaba. Se extiende a 10 s, por encima del timeout de 5 s del
# cliente httpx interno.
LATENCY_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
if OTEL_ENABLED:
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True),
        export_interval_millis=15000,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[reader],
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
meter = metrics.get_meter("data-service", APP_VERSION)

analytics_requests_total = meter.create_counter(
    "analytics_requests_total",
    description="Total de consultas de analitica procesadas",
    unit="1",
)
analytics_query_duration = meter.create_histogram(
    "analytics_query_duration_seconds",
    description="Latencia de las consultas de analitica a PostgreSQL",
    unit="s",
)
auth_attempts_total = meter.create_counter(
    "auth_attempts_total",
    description="Intentos de autenticacion, exitosos y fallidos",
    unit="1",
)
chaos_injected_total = meter.create_counter(
    "chaos_injected_total",
    description="Fallos inyectados por experimentos de caos",
    unit="1",
)

# ── Logging JSON con trace_id/span_id ────────────────────────────────────────
class OtelJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        ctx = trace.get_current_span().get_span_context()
        if ctx and ctx.is_valid:
            log_record["trace_id"] = format(ctx.trace_id, "032x")
            log_record["span_id"] = format(ctx.span_id, "016x")
        log_record["service"] = "data-service"
        log_record["version"] = APP_VERSION
        log_record["environment"] = ENV

handler = logging.StreamHandler()
handler.setFormatter(OtelJsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("data-service")

if OTEL_ENABLED:
    Psycopg2Instrumentor().instrument(tracer_provider=tracer_provider)


def get_db_connection():
    return psycopg2.connect(DB_DSN)


def hash_password(plain: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", plain.encode(), PBKDF2_SALT, PBKDF2_ROUNDS).hex()


# ── DB Semantic Conventions ──────────────────────────────────────────────────
# Atributos conformes a las OTel DB Semantic Conventions. El SDK 1.25 usa la
# nomenclatura clasica; entre parentesis, el renombrado de versiones posteriores:
#   db.system    -> db.system.name
#   db.name      -> db.namespace
#   db.operation -> db.operation.name
#   db.sql.table -> db.collection.name
#   db.statement -> db.query.text
def db_span_attributes(operation: str, table: str, statement: str) -> dict:
    return {
        "db.system":      "postgresql",
        "db.name":        DB_NAME,
        "db.operation":   operation,
        "db.sql.table":   table,
        "db.statement":   statement,   # parametrizada: nunca valores reales (evita PII)
        "db.user":        DB_USER,
        "server.address": DB_HOST,
        "server.port":    DB_PORT,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "data-service iniciado",
        extra={"otlp_endpoint": OTEL_ENDPOINT, "chaos_error_rate": CHAOS_ERROR_RATE},
    )
    yield
    if OTEL_ENABLED:
        tracer_provider.shutdown()
        meter_provider.shutdown()


app = FastAPI(
    title="Data Service",
    description="Servicio de analitica — OTel DB semantic conventions",
    version=APP_VERSION,
    lifespan=lifespan,
)

if OTEL_ENABLED:
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "data-service"}


@app.get("/analytics/{product_id}")
async def analytics(product_id: str):
    """Agregados de ventas del producto. Continua la traza iniciada por service-a."""
    start = time.time()
    labels = {"endpoint": "/analytics", "product": product_id}

    # ── Modulo D: inyeccion de error controlada y reversible ──────────────────
    if CHAOS_ERROR_RATE > 0 and random.random() < CHAOS_ERROR_RATE:
        span = trace.get_current_span()
        span.set_attribute("chaos.injected", True)
        span.set_status(trace.StatusCode.ERROR, "chaos: fallo inyectado")
        chaos_injected_total.add(1, {"experiment": "error-rate"})
        analytics_requests_total.add(1, {**labels, "status": "5xx"})
        logger.error(
            "Fallo inyectado por experimento de caos",
            extra={"chaos": True, "product_id": product_id},
        )
        raise HTTPException(status_code=500, detail="chaos: internal error")

    # Degradacion de latencia del experimento: un incidente real suele degradar
    # errores Y latencia a la vez, que es lo que exige la regla de correlacion.
    if CHAOS_LATENCY_MS > 0:
        time.sleep(CHAOS_LATENCY_MS / 1000.0)

    statement = "SELECT product_id, SUM(units_sold), SUM(revenue) FROM sales_facts WHERE product_id = %s GROUP BY product_id"
    with tracer.start_as_current_span(
        "analytics.query.sales",
        kind=trace.SpanKind.CLIENT,
        attributes=db_span_attributes("SELECT", "sales_facts", statement),
    ) as span:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(statement, (product_id,))
            row = cur.fetchone()
            conn.close()

            duration = time.time() - start
            analytics_query_duration.record(duration, {"operation": "SELECT", "table": "sales_facts"})
            span.set_attribute("db.response.returned_rows", 1 if row else 0)

            if not row:
                span.set_status(trace.StatusCode.ERROR, "Producto sin datos de analitica")
                analytics_requests_total.add(1, {**labels, "status": "4xx"})
                raise HTTPException(status_code=404, detail=f"Sin analitica para {product_id}")

            result = {
                "product_id":   row[0],
                "units_sold":   int(row[1] or 0),
                "revenue":      float(row[2] or 0),
                "source":       "analyticsdb",
            }
            span.set_attribute("analytics.units_sold", result["units_sold"])
            span.set_status(trace.StatusCode.OK)
            analytics_requests_total.add(1, {**labels, "status": "2xx"})
            logger.info("Analitica consultada", extra={"product_id": product_id, **result})
            return result

        except HTTPException:
            raise
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            analytics_requests_total.add(1, {**labels, "status": "5xx"})
            logger.error("Consulta de analitica fallida", extra={"error": str(exc)})
            raise HTTPException(status_code=503, detail="Analytics database unavailable")


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def login(req: LoginRequest):
    """Autenticacion sintetica: alimenta el Golden Signal de autenticaciones fallidas."""
    statement = "SELECT username, password_hash FROM app_users WHERE username = %s"
    with tracer.start_as_current_span(
        "auth.verify.credentials",
        kind=trace.SpanKind.CLIENT,
        attributes=db_span_attributes("SELECT", "app_users", statement),
    ) as span:
        span.set_attribute("enduser.id", req.username)   # identificador, nunca la contrasena
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(statement, (req.username,))
            row = cur.fetchone()
            conn.close()
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise HTTPException(status_code=503, detail="Auth backend unavailable")

        ok = bool(row) and row[1] == hash_password(req.password)
        auth_attempts_total.add(1, {"result": "success" if ok else "failure", "username": req.username})
        span.set_attribute("auth.result", "success" if ok else "failure")

        if not ok:
            span.set_status(trace.StatusCode.ERROR, "Credenciales invalidas")
            logger.warning(
                "Intento de autenticacion fallido",
                extra={"username": req.username, "auth_result": "failure"},
            )
            raise HTTPException(status_code=401, detail="Credenciales invalidas")

        logger.info("Autenticacion exitosa", extra={"username": req.username, "auth_result": "success"})
        return {"status": "authenticated", "username": req.username}
