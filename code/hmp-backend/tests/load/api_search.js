/**
 * Search-endpoint load test.
 *
 * Issues GET /search?q=<russian-keyword> with one of four rotating queries
 * to exercise realistic full-text search behaviour.
 *
 * NFR target: p95 < 150ms. Test allows a little headroom at p95 < 250ms.
 * Error budget: < 1%.
 *
 * Run:
 *   k6 run tests/load/api_search.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  vus: 20,
  duration: '20s',
  thresholds: {
    'http_req_duration{endpoint:search}': ['p(95)<250'],
    'http_req_duration':                  ['p(95)<300'],
    'http_req_failed':                    ['rate<0.01'],
  },
};

const QUERIES = ['бюджет', 'протокол', 'встреча', 'план'];

export default function () {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const url = `${BASE_URL}${ENDPOINTS.search}?q=${encodeURIComponent(q)}&limit=20`;

  const res = http.get(url, {
    headers: HEADERS,
    tags: { endpoint: 'search', method: 'GET' },
  });

  check(res, {
    'search status 2xx':       (r) => r.status >= 200 && r.status < 300,
    'search body not empty':   (r) => r.body && r.body.length > 0,
  });
}