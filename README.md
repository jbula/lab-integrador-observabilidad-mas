# Pipeline de Observabilidad End-to-End con OpenTelemetry

**Laboratorio 2 — Maestría en Arquitectura de Software · Observabilidad en Ambientes Productivos**

Pipeline completo que captura **métricas** (Prometheus), **logs estructurados** (Loki) y
**trazas distribuidas** (Jaeger) desde dos microservicios Python/FastAPI, procesadas por un
**OTel Collector** y correlacionadas cross-signal mediante el `trace_id`.

> **Modo de ejecución:** este laboratorio se ejecuta **100% en local** con Docker Compose.
> Los manifiestos Terraform (AWS provider `~> 5.0`) son un **entregable de IaC validado** (`init` +
> `validate` + `plan`), **no se despliega** a AWS para evitar costos.

---

## Arquitectura

```
cliente / k6
   │ GET /order/{id}
   ▼
service-a (FastAPI :8000) ──HTTP──► service-b (FastAPI :8001)
   │ OTLP :4317                         │ OTLP :4317
   ▼                                    ▼
       OTel Collector (sidecar) ─┬─► Jaeger  :16686   (trazas)
                                 ├─► Prometheus :9091 (métricas :8889)
                                 └─► debug/stdout
   postgres-a (orders)      postgres-b (inventory)      [DB por servicio]
   stdout JSON ──► Promtail ──► Loki :3100 ──► Grafana :3000 (pivote trace_id)
```

Flujo de una request: `service-a` consulta su DB de pedidos, llama a `service-b` (que consulta
su DB de inventario) propagando el contexto W3C; una **sola traza** cruza ambos servicios.

---

## Prerrequisitos

- **Docker** (Colima o Docker Desktop). Lo único imprescindible.
- **k6** (benchmark) · **pandoc + tectonic** (reporte PDF) · **terraform** (IaC) — opcionales según la fase.

### ⚠️ Red corporativa con inspección TLS (Netskope/Zscaler/etc.)

Si tu red intercepta TLS (p. ej. Netskope), la VM de Docker **no confía** en el CA corporativo y
`docker pull` falla con `x509: certificate signed by unknown authority`. Inyecta el CA en la VM:

```bash
# Exportar el CA corporativo del llavero de macOS
security find-certificate -a -p /Library/Keychains/System.keychain > /tmp/sys.pem
# (filtrar los certs de tu proxy, p. ej. goskope/netskope) y copiarlo a la VM:
colima ssh -- sudo cp "$HOME/corp-ca.crt" /usr/local/share/ca-certificates/corp.crt
colima ssh -- sudo update-ca-certificates
colima ssh -- sudo systemctl restart docker
```

---

## Uso rápido (modo local)

```bash
make local-up    # construye y levanta los 10 contenedores
make seed        # genera carga para poblar trazas/métricas/logs
make verify      # chequea servicios en Jaeger y targets en Prometheus
make down        # detiene (make clean para borrar volúmenes)
```

**Accesos:**

| Servicio | URL | Notas |
|---|---|---|
| service-a | http://localhost:8000/docs | API |
| Jaeger UI | http://localhost:16686 | trazas distribuidas |
| Grafana | http://localhost:3000 | admin/admin · 8 paneles |
| Prometheus | http://localhost:9091 | métricas |

### Correlación cross-signal
En Grafana → **Explore** → Loki: `{service="service-a"} | json` → expandir una línea →
campo `trace_id` enlaza a la traza en Jaeger. Y en una traza de Jaeger, *trace-to-logs*
salta a Loki por el mismo `trace_id`.

---

## Benchmark de overhead (Fase 4)

```bash
cd k6 && ./run_benchmark.sh    # baseline (OTEL_ENABLED=false) vs instrumentado
```
Compara la **misma imagen** con y sin SDK, muestrea `docker stats` y produce
`results/overhead_table.md`. Resultado de referencia: CPU +21%, latencia promedio +14%,
memoria +3%. Ver `docs/report/report.pdf` §7.

---

## Infraestructura como Código (entregable, sin apply)

```bash
cd terraform
terraform init
terraform validate
TF_VAR_db_password=x terraform plan     # Plan: 42 to add — NO ejecutar apply (local-only)
```
5 módulos (`network`, `ecr`, `iam`, `observability`, `app`), 42 recursos, patrón sidecar
(servicio + collector + postgres), ALB restringido por IP, Service Connect, Secrets Manager.

---

## Estructura

```
service-a/ service-b/     Microservicios FastAPI + OTel SDK
otel-collector/           Configs local/aws + Dockerfile
scripts/                  init-db por servicio (orders / inventory)
prometheus/ grafana/ loki/  Backends y provisioning
k6/                       k6 + análisis de overhead
terraform/                IaC AWS 5.0 (5 módulos)
docs/report/              Reporte técnico (report.md → report.pdf)
docs/evidence/            Capturas de Jaeger/Grafana
legacy/                   Artefactos fuera de alcance (GCP, Tempo, K6 dup)
```

## Documentación

- Reporte técnico: `docs/report/report.pdf` (7 páginas)
- Spec de diseño: `.kiro/specs/otel-observability-pipeline/` (design, requirements, tasks)
