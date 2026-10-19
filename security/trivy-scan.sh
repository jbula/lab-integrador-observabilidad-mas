#!/usr/bin/env bash
# Escanea las imagenes del laboratorio con Trivy y publica el conteo de
# vulnerabilidades como metricas Prometheus (textfile collector).
# Golden Signal de seguridad: CVEs activos (Lab 4, Modulo C).
set -uo pipefail
cd "$(dirname "$0")"
OUT="metrics/cve.prom"
TMP="$(mktemp)"
IMAGES="${IMAGES:-otellabs-service-a otellabs-service-b otellabs-data-service otellabs-alert-enricher}"

{
  echo "# HELP image_vulnerabilities Vulnerabilidades detectadas por Trivy, por imagen y severidad"
  echo "# TYPE image_vulnerabilities gauge"
  echo "# HELP image_scan_timestamp_seconds Marca de tiempo del ultimo escaneo exitoso"
  echo "# TYPE image_scan_timestamp_seconds gauge"
} > "$TMP"

for img in $IMAGES; do
  echo "Escaneando $img ..." >&2
  # CORP_CA: en redes con inspeccion TLS (Netskope, Zscaler) Trivy no puede
  # descargar la base de vulnerabilidades sin el CA corporativo. Se monta y se
  # expone por SSL_CERT_FILE, que el runtime de Go respeta.
  CORP_CA="${CORP_CA:-$HOME/corp-ca.crt}"
  CA_ARGS=""
  if [ -f "$CORP_CA" ]; then
    CA_ARGS="-v $CORP_CA:/etc/ssl/certs/corp-ca.pem:ro -e SSL_CERT_FILE=/etc/ssl/certs/corp-ca.pem"
  fi

  json=$(docker run --rm \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$HOME/.cache/trivy:/root/.cache/trivy" \
      $CA_ARGS \
      aquasec/trivy:0.54.1 image --quiet --format json --scanners vuln "$img" 2>/dev/null)

  if [ -z "$json" ]; then
    echo "  aviso: escaneo sin resultado para $img (se conserva el valor anterior)" >&2
    continue
  fi

  echo "$json" | IMG="$img" python3 -c '
import json, os, sys
img = os.environ["IMG"]
data = json.load(sys.stdin)
counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
for res in data.get("Results") or []:
    for v in res.get("Vulnerabilities") or []:
        sev = (v.get("Severity") or "UNKNOWN").upper()
        counts[sev] = counts.get(sev, 0) + 1
for sev, n in counts.items():
    print(f"image_vulnerabilities{{image=\"{img}\",severity=\"{sev}\"}} {n}")
' >> "$TMP"
done

echo "image_scan_timestamp_seconds $(date +%s)" >> "$TMP"
mv "$TMP" "$OUT"
echo "Metricas escritas en $OUT" >&2
grep -c "^image_vulnerabilities" "$OUT" | xargs echo "Series publicadas:" >&2
