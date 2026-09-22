/**
 * Spike test — sudden load burst to verify auto-scaling / circuit breakers.
 *
 * 0 → 200 VU in 5s, hold 10s, 200 → 0 in 5s (total 30s).
 *
 * NFR envelope under spike:
 *   p99 < 2s, error_rate < 10% (very lenient — spikes are about survival).
 *
 * Run:
 *   k6 run tests/load/spike.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  stages: [
    { duration: '5s',  target: 200 },   // ramp up to 200 VU
    { duration: '10s', target: 200 },   // hold
    { duration: '5s',  target: 0   },   // ramp down
    { duration: '10s', target: 0   },   // post-spike cool-down
  ],
  thresholds: {
    'http_req_duration': ['p(99)<2000'],
    'http_req_failed':   ['rate<0.10'],
  },
};

export default function () {
  const page = Math.floor(Math.random() * 5) + 1;
  const url = `${BASE_URL}${ENDPOINTS.protocols}?limit=20&offset=${(page - 1) * 20}`;

  const res = http.get(url, {
    headers: HEADERS,
    tags: { endpoint: 'protocols', method: 'GET' },
  });

  check(res, {
    'spike status is 2xx or 5xx-tolerated': (r) =>
      (r.status >= 200 && r.status < 300) || (r.status >= 500 && r.status < 600),
    'spike response time < 2s':            (r) => r.timings.duration < 2000,
  });
}