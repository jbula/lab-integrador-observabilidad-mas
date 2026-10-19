#!/usr/bin/env bash
# Genera trafico sintetico contra el stack local para alimentar los Golden
# Signals de seguridad: trafico Norte-Sur (borde -> service-a), Este-Oeste
# (service-a -> service-b -> data-service) y autenticaciones exito/fallo.
#
# Uso: scripts/generate-traffic.sh [duracion_segundos] [ratio_fallo_auth]
#   duracion_segundos  por defecto 120
#   ratio_fallo_auth   entero 1..10, cuantos de cada 10 intentos fallan (def. 3)
set -euo pipefail

DURACION="${1:-120}"
RATIO_FALLO="${2:-3}"

SERVICE_A="${SERVICE_A_URL:-http://localhost:8000}"
DATA_SERVICE="${DATA_SERVICE_URL:-http://localhost:8002}"

ORDENES=(ord-001 ord-002 ord-003 ord-004 ord-005)
PRODUCTOS=(LAPTOP-X1 MOUSE-PRO KEYBOARD-MK MONITOR-4K HEADSET-Z)
USUARIOS=(demo analyst auditor)

# Credenciales de laboratorio sembradas por scripts/init-db-analytics.sql.
# Se resuelven con case en lugar de un array asociativo porque macOS trae
# bash 3.2, que no los soporta.
clave_de() {
  case "$1" in
    demo)    echo "demo123" ;;
    analyst) echo "analyst123" ;;
    auditor) echo "auditor123" ;;
    *)       echo "sin-clave" ;;
  esac
}

post_login() {
  local usuario="$1" clave="$2"
  curl -s -o /dev/null -X POST "${DATA_SERVICE}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${usuario}\",\"password\":\"${clave}\"}" || true
}

fin=$(( $(date +%s) + DURACION ))
iter=0
ns=0; ew=0; ok=0; fallo=0

echo "Generando trafico durante ${DURACION}s (ratio de fallo auth ${RATIO_FALLO}/10)..."

while [ "$(date +%s)" -lt "$fin" ]; do
  iter=$(( iter + 1 ))

  # Norte-Sur: el borde entra por service-a, que encadena service-b y data-service
  orden="${ORDENES[$(( RANDOM % ${#ORDENES[@]} ))]}"
  curl -s -o /dev/null "${SERVICE_A}/order/${orden}" || true
  ns=$(( ns + 1 )); ew=$(( ew + 1 ))

  # Este-Oeste directo: consulta analitica sin pasar por el borde
  producto="${PRODUCTOS[$(( RANDOM % ${#PRODUCTOS[@]} ))]}"
  curl -s -o /dev/null "${DATA_SERVICE}/analytics/${producto}" || true
  ew=$(( ew + 1 ))

  # Autenticacion: mezcla exito/fallo segun el ratio indicado
  usuario="${USUARIOS[$(( RANDOM % ${#USUARIOS[@]} ))]}"
  if [ $(( RANDOM % 10 )) -lt "$RATIO_FALLO" ]; then
    post_login "$usuario" "clave-incorrecta-$RANDOM"
    fallo=$(( fallo + 1 ))
  else
    post_login "$usuario" "$(clave_de "$usuario")"
    ok=$(( ok + 1 ))
  fi

  sleep 1
done

echo "Iteraciones=${iter} peticiones_NS=${ns} peticiones_EW=${ew} auth_ok=${ok} auth_fallo=${fallo}"
