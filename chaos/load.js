/**
 * chaos/load.js — Carga sostenida a tasa constante para los experimentos del
 * Modulo D.
 *
 * A diferencia de k6/k6_benchmark.js (que usa constant-vus para medir
 * overhead), aqui se usa constant-arrival-rate: la tasa de peticiones se
 * mantiene fija aunque la latencia aumente. Esto es imprescindible en un
 * experimento de caos, porque con VUs fijos la inyeccion de latencia REDUCE
 * el throughput y contamina la comparacion entre fases.
 *
 * Uso:
 *   k6 run --env DURATION=480s --env RPS=12 chaos/load.js
 */
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DS_URL   = __ENV.DS_URL   || "http://localhost:8002";
const RPS      = parseInt(__ENV.RPS || "12", 10);
const DURATION = __ENV.DURATION || "480s";

// TARGET elige el punto de entrada de la carga:
//   edge      peticiones a service-a, que encadena service-b y data-service
//   analytics peticiones directas a data-service
//
// El modo analytics es necesario para el experimento D2. service-b mantiene una
// cache en memoria de inventario y, con solo cinco productos en catalogo, tras
// las primeras peticiones todas son acierto de cache: service-b responde sin
// llegar a invocar a data-service, de modo que el tercer salto deja de recibir
// trafico y un fallo inyectado alli seria indetectable por falta de muestras.
const TARGET = __ENV.TARGET || "edge";

const ORDER_IDS = ["ord-001", "ord-002", "ord-003", "ord-004", "ord-005"];
const PRODUCT_IDS = ["LAPTOP-X1", "MOUSE-PRO", "KEYBOARD-MK", "MONITOR-4K", "HEADSET-Z"];

export const options = {
  scenarios: {
    constante: {
      executor: "constant-arrival-rate",
      rate: RPS,
      timeUnit: "1s",
      duration: DURATION,
      // Holgura amplia de VUs: si la latencia sube 10x, k6 necesita mas VUs
      // para sostener la misma tasa de llegada.
      preAllocatedVUs: 20,
      maxVUs: 300,
    },
  },
  // Sin thresholds: en un experimento de caos se ESPERA degradacion, y un
  // threshold incumplido haria salir a k6 con codigo distinto de cero.
  thresholds: {},
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

export default function () {
  let res;
  if (TARGET === "analytics") {
    const pid = PRODUCT_IDS[Math.floor(Math.random() * PRODUCT_IDS.length)];
    res = http.get(`${DS_URL}/analytics/${pid}`, { timeout: "15s" });
  } else {
    const orderId = ORDER_IDS[Math.floor(Math.random() * ORDER_IDS.length)];
    res = http.get(`${BASE_URL}/order/${orderId}`, { timeout: "15s" });
  }
  // En un experimento de caos se ESPERAN respuestas 5xx; el check solo etiqueta.
  check(res, { "status 200": (r) => r.status === 200 });
}

export function handleSummary(data) {
  const d = data.metrics.http_req_duration?.values || {};
  const resumen = {
    peticiones: data.metrics.http_reqs?.values?.count || 0,
    rps_real: +(data.metrics.http_reqs?.values?.rate || 0).toFixed(2),
    fallidas_pct: +((data.metrics.http_req_failed?.values?.rate || 0) * 100).toFixed(3),
    latencia_ms: {
      avg: +(d.avg || 0).toFixed(1),
      med: +(d.med || 0).toFixed(1),
      p95: +(d["p(95)"] || 0).toFixed(1),
      p99: +(d["p(99)"] || 0).toFixed(1),
      max: +(d.max || 0).toFixed(1),
    },
  };
  const etiqueta = __ENV.FASE || "carga";
  return {
    stdout: JSON.stringify(resumen, null, 2) + "\n",
    [`chaos/results/k6_${etiqueta}.json`]: JSON.stringify(resumen, null, 2),
  };
}
