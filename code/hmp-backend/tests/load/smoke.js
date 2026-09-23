/**
 * Smoke test — basic reachability check.
 *
 * NFR target: p95 < 200ms synchronous. Smoke is generous: p95 < 500ms.
 *
 * Run:
 *   k6 run tests/load/smoke.js
 *   k6 run -e BASE_URL=https://staging.example.com tests/load/smoke.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS } from './config.js';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    'http_req_duration': ['p(95)<500'],
    'http_req_failed':   ['rate<0.01'],
  },
};

export default function () {
  const url = `${BASE_URL}${ENDPOINTS.health}`;
  const res = http.get(url, { tags: { endpoint: ENDPOINTS.health, method: 'GET' } });

  check(res, {
    'health status is 200':      (r) => r.status === 200,
    'health body not empty':     (r) => r.body && r.body.length > 0,
    'response time < 500ms':     (r) => r.timings.duration < 500,
  });
}