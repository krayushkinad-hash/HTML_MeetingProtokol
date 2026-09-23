/**
 * Soak test — long-run (10 minutes) at modest 30 VU load.
 *
 * Goal: surface memory leaks, slow accumulation of connections, GC pauses,
 * or DB connection-pool exhaustion that only show up over time.
 *
 * Traffic: same mix as api_read.js (80% list, 20% calendar).
 *
 * NFR envelope (steady-state):
 *   p95 < 250ms, error_rate < 1%.
 *
 * Run:
 *   k6 run tests/load/soak.js
 *   k6 run -e DURATION=20m tests/load/soak.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  vus: 30,
  duration: __ENV.DURATION || '10m',
  thresholds: {
    'http_req_duration': ['p(95)<250'],
    'http_req_failed':   ['rate<0.01'],
  },
};

export default function () {
  if (Math.random() < 0.8) {
    const page = Math.floor(Math.random() * 5) + 1;
    const url = `${BASE_URL}${ENDPOINTS.protocols}?limit=20&offset=${(page - 1) * 20}`;
    const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'protocols', method: 'GET' } });
    check(res, { 'soak protocols 2xx': (r) => r.status >= 200 && r.status < 300 });
  } else {
    const url = `${BASE_URL}${ENDPOINTS.calendar}?year=2026&month=9`;
    const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'calendar', method: 'GET' } });
    check(res, { 'soak calendar 2xx': (r) => r.status >= 200 && r.status < 300 });
  }
}