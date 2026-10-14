# ════════════════════════════════════════════════════════════════════
# Laboratorio OTel — orquestación local (Colima/Docker Compose)
# ════════════════════════════════════════════════════════════════════
.PHONY: help local-up down ps logs seed verify bench report tf-init tf-plan tf-validate clean

help:
	@echo "local-up    Levanta el stack completo (build + up -d)"
	@echo "down        Detiene y elimina contenedores (conserva volúmenes)"
	@echo "clean       down + elimina volúmenes (-v)"
	@echo "ps          Estado de los contenedores"
	@echo "logs        Logs en vivo (S=service para uno solo)"
	@echo "seed        Genera carga para poblar trazas/métricas"
	@echo "verify      Verifica los 3 pilares (trazas, métricas, logs)"
	@echo "bench       Benchmark de overhead (requiere k6)"
	@echo "report      Genera el reporte PDF (requiere pandoc)"
	@echo "tf-init/tf-validate/tf-plan   Terraform (entregable, sin apply)"

local-up:
	docker compose up -d --build

down:
	docker compose down

clean:
	docker compose down -v

ps:
	docker compose ps

logs:
	docker compose logs -f $(S)

seed:
	@echo "Generando carga..."
	@for i in $$(seq 1 30); do for id in ord-001 ord-002 ord-003 ord-004 ord-005; do \
		curl -s -m 5 http://localhost:8000/order/$$id >/dev/null; done; done
	@echo "Carga enviada. Jaeger: http://localhost:16686  Grafana: http://localhost:3000"

verify:
	@echo "Servicios en Jaeger:"; curl -s http://localhost:16686/api/services | python3 -m json.tool
	@echo "Targets Prometheus:"; curl -s "http://localhost:9091/api/v1/targets?state=active" | python3 -c "import json,sys;[print(' ',t['labels'].get('job'),t['health']) for t in json.load(sys.stdin)['data']['activeTargets']]"

bench:
	cd k6 && ./run_benchmark.sh

report:
	cd docs/report && pandoc report.md -o report.pdf

tf-init:
	cd terraform && terraform init

tf-validate:
	cd terraform && terraform validate

tf-plan:
	cd terraform && terraform plan -var-file=terraform.tfvars
