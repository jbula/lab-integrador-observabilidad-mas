# Análisis de Overhead — OpenTelemetry SDK

| Métrica | Sin OTel | Con OTel | Overhead |
|---|---|---|---|
| Latencia promedio (ms) | 35.4 | 40.2 | +13.6% |
| Latencia p95 (ms) | 81.5 | 88.4 | +8.5% |
| Latencia p99 (ms) | 124.7 | 219.4 | +76.0% |
| Throughput (req/s) | 43.5 | 43.5 | +0.0% |
| CPU total 3 contenedores (%) | 60.5 | 73.4 | +21.3% |
| Memoria total 3 contenedores (MiB) | 309.4 | 319.3 | +3.2% |

> **Nota metodológica:** baseline e instrumentado usan la MISMA imagen; única diferencia `OTEL_ENABLED`. La latencia de DB simulada se desactiva (`SIMULATE_DB_LATENCY=false`) para aislar el overhead del SDK. El p99 es sensible a la cola y ruidoso en una VM de 4 CPU compartida con el Collector; los indicadores estables son latencia promedio, p95 y CPU. Medición en Colima 4 CPU / 6 GB.
