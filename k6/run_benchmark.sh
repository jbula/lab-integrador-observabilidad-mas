#!/usr/bin/env bash
# Benchmark de overhead OTel: baseline (OTEL_ENABLED=false) vs instrumentado (true), misma imagen.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
RES="$(pwd)/results"
CONTAINERS="service-a service-b otel-collector"

sample_stats() {  # $1=outfile ; muestrea docker stats hasta recibir SIGTERM
  while true; do
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' $CONTAINERS 2>/dev/null >> "$1"
    sleep 3
  done
}

run_scenario() {  # $1=mode(baseline|otel) $2=OTEL_ENABLED $3=INSTRUMENTED
  local mode=$1 otel=$2 inst=$3
  echo "──> Escenario '$mode' (OTEL_ENABLED=$otel)"
  ( cd "$ROOT" && OTEL_ENABLED=$otel SIMULATE_DB_LATENCY=false docker compose up -d --no-deps service-a service-b >/dev/null )
  echo "    esperando health..."; sleep 18
  for i in $(seq 1 10); do curl -s -m 5 http://localhost:8000/order/ord-001 >/dev/null || true; done
  : > "$RES/stats_$mode.csv"
  sample_stats "$RES/stats_$mode.csv" & local sp=$!
  ( cd "$RES" && k6 run --quiet --env INSTRUMENTED=$inst "../k6_benchmark.js" ) || true
  kill "$sp" 2>/dev/null || true; wait "$sp" 2>/dev/null || true
  echo "    $mode listo."
}

( cd "$ROOT" && docker compose build service-a service-b >/dev/null 2>&1 ) && echo "build único OK"

run_scenario baseline false false
run_scenario otel     true  true
# dejar los servicios instrumentados al terminar
echo "──> merge de recursos + análisis"
python3 merge_resources.py
python3 analyze_overhead.py
