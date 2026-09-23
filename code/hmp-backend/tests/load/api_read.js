/**
 * Read-heavy load test.
 *
 * Distribution:
 *   80% — GET /protocols (paged list, target p95 < 100ms)
 *   20% — GET /calendar?year=2026&month=9 (target p95 < 100ms)
 *
 * NFR threshold: p95 < 200ms for synchronous read traffic.
 * Error budget:  < 1%
 *
 * Stages: ramp-up 10→50→100 VU over 30s.
 *
 * Run:
 *   k6 run tests/load/api_read.js
 *   k6 run -e BASE_URL=https://staging.example.com tests/load/api_read.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  stages: [
    { duration: '5s',  target: 10  },   // ramp-up to 10 VU
    { duration: '10s', target: 50  },   // ramp to 50 VU
    { duration: '10s', target: 100 },   // ramp to 100 VU
    { duration: '5s',  target: 0   },   // ramp-down
  ],
  thresholds: {
    // Strict NFR endpoints:
    'http_req_duration{endpoint:protocols}':  ['p(95)<100'],
    'http_req_duration{endpoint:calendar}':   ['p(95)<100'],
    // Overall NFR envelope (synchronous reads):
    'http_req_duration':                      ['p(95)<200'],
    'http_req_failed':                        ['rate<0.01'],
  },
};

function listProtocols(page) {
  const limit = 20;
  const offset = (page - 1) * limit;
  const url = `${BASE_URL}${ENDPOINTS.protocols}?limit=${limit}&offset=${offset}`;
  const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'protocols', method: 'GET' } });
  check(res, { 'protocols status 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

function listCalendar() {
  const url = `${BASE_URL}${ENDPOINTS.calendar}?year=2026&month=9`;
  const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'calendar', method: 'GET' } });
  check(res, { 'calendar status 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

export default function () {
  const page = Math.floor(Math.random() * 5) + 1;   // pages 1..5
  if (Math.random() < 0.8) {
    listProtocols(page);
  } else {
    listCalendar();
  }
  // Tiny think-time so we don't fully pin a CPU on the runner.
  // (k6 default sleep is 1s; explicit here keeps it explicit in reports.)
}