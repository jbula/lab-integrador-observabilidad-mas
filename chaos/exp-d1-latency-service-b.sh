#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
# Experimento D1 — Inyeccion de 200 ms de latencia de red en service-b.
#
# Hipotesis: la degradacion de un servicio interno (service-b) propaga HACIA
# ARRIBA hasta el borde (service-a) y el detector 2-sigma de latencia del borde
# la senala en menos de 2 minutos.
#
# Mecanismo: tc netem desde un contenedor auxiliar que comparte el namespace de
# red de service-b. No requiere NET_ADMIN en el servicio ni reconstruir imagen.
#
# Fases: linea base 150 s -> caos 180 s -> recuperacion 120 s
# Rollback: automatico via trap, incluso si el script se interrumpe.
# ════════════════════════════════════════════════════════════════════════════
set -uo pipefail

OBJETIVO=service-b
LATENCIA_MS=200
BASE_S=150
CAOS_S=180
RECUP_S=120
RPS="${RPS:-12}"
RES=chaos/results

mkdir -p "$RES"

limpiar() {
  echo ""
  echo "[rollback] eliminando la disciplina de cola de ${OBJETIVO}..."
  docker run --rm --net "container:${OBJETIVO}" --cap-add NET_ADMIN \
    nicolaka/netshoot tc qdisc del dev eth0 root >/dev/null 2>&1 \
    && echo "[rollback] qdisc eliminada" \
    || echo "[rollback] no habia qdisc activa (nada que revertir)"
}
trap limpiar EXIT INT TERM

echo "════════════════════════════════════════════════════════════"
echo " D1 — latencia +${LATENCIA_MS} ms en ${OBJETIVO}"
echo " fases: base ${BASE_S}s | caos ${CAOS_S}s | recuperacion ${RECUP_S}s"
echo " carga: ${RPS} req/s a tasa constante"
echo "════════════════════════════════════════════════════════════"

TOTAL_S=$(( BASE_S + CAOS_S + RECUP_S ))

# La carga corre en segundo plano durante TODO el experimento, para que las tres
# fases sean comparables bajo la misma tasa de llegada.
echo "[carga] arrancando k6 por ${TOTAL_S}s..."
FASE="d1_completo" k6 run --quiet --env DURATION="${TOTAL_S}s" --env RPS="${RPS}" \
  chaos/load.js > "${RES}/k6_d1.log" 2>&1 &
K6_PID=$!

# ── Fase 1: linea base ──────────────────────────────────────────────────────
T_BASE_INI=$(date +%s)
echo "[fase 1] linea base, ${BASE_S}s..."
sleep "$BASE_S"
T_BASE_FIN=$(date +%s)

# ── Fase 2: inyeccion ───────────────────────────────────────────────────────
echo "[fase 2] inyectando ${LATENCIA_MS} ms..."
docker run --rm --net "container:${OBJETIVO}" --cap-add NET_ADMIN \
  nicolaka/netshoot tc qdisc add dev eth0 root netem delay "${LATENCIA_MS}ms"
T0=$(date +%s)
echo "[fase 2] inyeccion aplicada en t0=${T0}"

# Medir MTTD en paralelo mientras el caos sigue activo.
chaos/measure-mttd.py --t0 "$T0" \
  --alerts EdgeLatencyDegraded,EdgeLatencySLOBreach \
  --timeout "$CAOS_S" --salida "${RES}/mttd_d1.json" &
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

# ── Analisis de SLO por fase ────────────────────────────────────────────────
echo ""
echo "[analisis] calculando SLO y error budget por fase..."
chaos/analyze-slo.py --inicio "$T_BASE_INI" --fin "$T_BASE_FIN" \
  --etiqueta d1_base  --salida "${RES}/slo_d1_base.json"  > /dev/null
chaos/analyze-slo.py --inicio "$T0"         --fin "$T_CAOS_FIN" \
  --etiqueta d1_caos  --salida "${RES}/slo_d1_caos.json"  > /dev/null
chaos/analyze-slo.py --inicio "$T_RECUP_INI" --fin "$T_RECUP_FIN" \
  --etiqueta d1_recup --salida "${RES}/slo_d1_recup.json" > /dev/null

cat > "${RES}/ventanas_d1.json" <<JSON
{
  "experimento": "D1",
  "fallo": "latencia de red +${LATENCIA_MS} ms en ${OBJETIVO}",
  "rps_objetivo": ${RPS},
  "base":  {"inicio": ${T_BASE_INI},  "fin": ${T_BASE_FIN}},
  "caos":  {"inicio": ${T0},          "fin": ${T_CAOS_FIN}},
  "recup": {"inicio": ${T_RECUP_INI}, "fin": ${T_RECUP_FIN}}
}
JSON

echo "[listo] resultados en ${RES}/ (mttd_d1.json, slo_d1_*.json, ventanas_d1.json)"
