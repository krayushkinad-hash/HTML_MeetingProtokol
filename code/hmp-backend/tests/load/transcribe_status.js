/**
 * Long-polling style test for /transcribe/status/{uuid}.
 *
 * Simulates 30 VUs hammering 60s of status checks against random UUIDs.
 * The endpoint should respond quickly whether the job exists (200) or not (404).
 *
 * NFR target: p95 < 200ms — including 404 responses (cache-miss path).
 *
 * Run:
 *   k6 run tests/load/transcribe_status.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS, randomUUID } from './config.js';

export const options = {
  vus: 30,
  duration: '60s',
  thresholds: {
    'http_req_duration':                ['p(95)<200'],
    'http_req_failed':                  ['rate<0.05'],   // 404s aren't "failed" for status-poll — but we still cap total failure
    'http_reqs{expected_response:true}':['count>0'],     // verify at least some 200s measured (with seeded data)
  },
};

export default function () {
  const uuid = randomUUID();
  const url = `${BASE_URL}${ENDPOINTS.transcribe}/${uuid}`;

  const res = http.get(url, {
    headers: HEADERS,
    tags: { endpoint: 'transcribe_status', method: 'GET' },
  });

  // Acceptable: 200 (job exists) or 404 (job not found / completed).
  check(res, {
    'transcribe status is 200 or 404': (r) =>
      r.status === 200 || r.status === 404,
    'transcribe response time < 200ms': (r) => r.timings.duration < 200,
  });
}