#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
# Experimento D2 — Tasa de error del 10 % en data-service.
#
# Hipotesis: una tasa de error del 10 % en el servicio mas profundo de la
# cadena activa el detector correlacionado 2-sigma (error_rate por encima de
# base + 2 sigma Y p99 por encima del SLO) en menos de 2 minutos.
#
# Mecanismo: variable CHAOS_ERROR_RATE dentro del propio servicio. Es
# determinista, reversible y queda marcado en la traza con chaos.injected=true,
# lo que permite distinguir en Jaeger un fallo inyectado de uno real.
#
# Nota de diseno: se inyecta tambien CHAOS_LATENCY_MS. La regla correlacionada
# exige AMBAS condiciones, y un fallo que responde de inmediato con 500 no
# degrada la latencia: sin este componente la alerta correlacionada no podria
# dispararse nunca. Es una propiedad de la regla, no un artificio del montaje.
#
# Fases: linea base 150 s -> caos 180 s -> recuperacion 120 s
# Rollback: automatico via trap (CHAOS_ERROR_RATE de vuelta a 0).
# ════════════════════════════════════════════════════════════════════════════
set -uo pipefail

OBJETIVO=data-service
TASA_ERROR=0.10
LATENCIA_CAOS_MS=600
BASE_S=150
CAOS_S=180
RECUP_S=120
RPS="${RPS:-12}"
RES=chaos/results

mkdir -p "$RES"

recrear() {
  local tasa="$1" latencia="$2"
  CHAOS_ERROR_RATE="$tasa" CHAOS_LATENCY_MS="$latencia" \
    docker compose up -d --force-recreate --no-deps "$OBJETIVO" >/dev/null 2>&1
}

limpiar() {
  echo ""
  echo "[rollback] restableciendo CHAOS_ERROR_RATE=0 en ${OBJETIVO}..."
  recrear 0 0
  sleep 8
  echo "[rollback] ${OBJETIVO} restablecido"
}
trap limpiar EXIT INT TERM

echo "════════════════════════════════════════════════════════════"
echo " D2 — error rate ${TASA_ERROR} en ${OBJETIVO}"
echo " fases: base ${BASE_S}s | caos ${CAOS_S}s | recuperacion ${RECUP_S}s"
echo " carga: ${RPS} req/s a tasa constante"
echo "════════════════════════════════════════════════════════════"

TOTAL_S=$(( BASE_S + CAOS_S + RECUP_S ))

echo "[carga] arrancando k6 por ${TOTAL_S}s..."
FASE="d2_completo" k6 run --quiet --env DURATION="${TOTAL_S}s" --env RPS="${RPS}" \
  chaos/load.js > "${RES}/k6_d2.log" 2>&1 &
K6_PID=$!

# ── Fase 1: linea base ──────────────────────────────────────────────────────
T_BASE_INI=$(date +%s)
echo "[fase 1] linea base, ${BASE_S}s..."
sleep "$BASE_S"
T_BASE_FIN=$(date +%s)

# ── Fase 2: inyeccion ───────────────────────────────────────────────────────
echo "[fase 2] inyectando error rate ${TASA_ERROR} y ${LATENCIA_CAOS_MS} ms..."
recrear "$TASA_ERROR" "$LATENCIA_CAOS_MS"
sleep 8                      # espera a que el contenedor acepte trafico
T0=$(date +%s)
echo "[fase 2] inyeccion aplicada en t0=${T0}"

chaos/measure-mttd.py --t0 "$T0" \
  --alerts DataServiceAnomalyCorrelated,DataServiceErrorRateStatic \
  --timeout "$CAOS_S" --salida "${RES}/mttd_d2.json" &
MTTD_PID=$!

sleep "$CAOS_S"
T_CAOS_FIN=$(date +%s)
wait "$MTTD_PID" 2>/dev/null || true

# ── Fase 3: rollback y recuperacion ─────────────────────────────────────────
echo "[fase 3] revirtiendo y observando recuperacion ${RECUP_S}s..."
limpiar
trap - EXIT INT TERM
T_RECUP_INI=$(date +%s)
sleep "$RECUP_S"
T_RECUP_FIN=$(date +%s)

wait "$K6_PID" 2>/dev/null || true

echo ""
echo "[analisis] calculando SLO y error budget por fase..."
chaos/analyze-slo.py --inicio "$T_BASE_INI"  --fin "$T_BASE_FIN" \
  --etiqueta d2_base  --salida "${RES}/slo_d2_base.json"  > /dev/null
chaos/analyze-slo.py --inicio "$T0"          --fin "$T_CAOS_FIN" \
  --etiqueta d2_caos  --salida "${RES}/slo_d2_caos.json"  > /dev/null
chaos/analyze-slo.py --inicio "$T_RECUP_INI" --fin "$T_RECUP_FIN" \
  --etiqueta d2_recup --salida "${RES}/slo_d2_recup.json" > /dev/null

cat > "${RES}/ventanas_d2.json" <<JSON
{
  "experimento": "D2",
  "fallo": "error rate ${TASA_ERROR} en ${OBJETIVO}",
  "latencia_caos_ms": ${LATENCIA_CAOS_MS},
  "rps_objetivo": ${RPS},
  "base":  {"inicio": ${T_BASE_INI},  "fin": ${T_BASE_FIN}},
  "caos":  {"inicio": ${T0},          "fin": ${T_CAOS_FIN}},
  "recup": {"inicio": ${T_RECUP_INI}, "fin": ${T_RECUP_FIN}}
}
JSON

echo "[listo] resultados en ${RES}/ (mttd_d2.json, slo_d2_*.json, ventanas_d2.json)"
