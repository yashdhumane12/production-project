/**
 * k6 load test for TaskMaster API
 * Run: k6 run scripts/load-test.js
 */
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "60s", target: 50 },
    { duration: "60s", target: 100 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed:   ["rate<0.05"],
  },
};

const BASE = __ENV.BASE_URL || "http://localhost:8080";
const HEADERS = { "Content-Type": "application/json" };

export default function () {
  // Create
  const create = http.post(`${BASE}/tasks`,
    JSON.stringify({ title: `Task-${Date.now()}`, priority: 1 }), { headers: HEADERS });
  check(create, { "create 201": (r) => r.status === 201 });

  // List (should be cached after first call)
  const list = http.get(`${BASE}/tasks`);
  check(list, { "list 200": (r) => r.status === 200 });

  sleep(0.5);
}
