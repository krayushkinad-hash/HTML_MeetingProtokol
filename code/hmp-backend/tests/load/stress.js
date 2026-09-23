/**
 * Stress test — 5-minute ramp to 500 VU.
 *
 * Distribution:
 *   60% — GET /protocols (list)
 *   20% — GET /protocols/{id} (item — requires known id from env)
 *   15% — GET /search?q=...
 *    5% — POST /protocols (upload)
 *
 * NFR envelope under stress is relaxed:
 *   p95 < 500ms, error_rate < 5%.
 *
 * Pre-requisite:
 *   Seeded data via `k6 run tests/load/setup.js`, OR the backend already has data.
 *
 * Run:
 *   k6 run tests/load/stress.js
 */

import http from 'k6/http';
import { check } from 'k6';
import {
  BASE_URL, ENDPOINTS, HEADERS, pickWeighted,
} from './config.js';

export const options = {
  stages: [
    { duration: '30s', target: 100 },
    { duration: '60s', target: 300 },
    { duration: '120s', target: 500 },
    { duration: '60s', target: 500 },
    { duration: '30s', target: 0   },
  ],
  thresholds: {
    'http_req_duration{op:list}':    ['p(95)<500'],
    'http_req_duration{op:get}':     ['p(95)<500'],
    'http_req_duration{op:search}':  ['p(95)<500'],
    'http_req_duration{op:upload}':  ['p(95)<1000'],
    'http_req_duration':             ['p(95)<500'],
    'http_req_failed':               ['rate<0.05'],
  },
};

// CSV / newline list of protocol IDs available via env.
//   k6 run -e PROTOCOL_IDS="uuid1,uuid2,..." tests/load/stress.js
const PROTOCOL_IDS = (__ENV.PROTOCOL_IDS || '').split(',').filter(Boolean);

function listProtocols() {
  const page = Math.floor(Math.random() * 5) + 1;
  const url = `${BASE_URL}${ENDPOINTS.protocols}?limit=20&offset=${(page - 1) * 20}`;
  const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'protocols', op: 'list', method: 'GET' } });
  check(res, { 'list 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

function getProtocol() {
  if (PROTOCOL_IDS.length === 0) {
    // graceful degradation: fall back to a random uuid (404 path is still measurable)
  }
  const id = PROTOCOL_IDS.length
    ? PROTOCOL_IDS[Math.floor(Math.random() * PROTOCOL_IDS.length)]
    : '00000000-0000-4000-8000-000000000000';
  const url = `${BASE_URL}${ENDPOINTS.protocolItem(id)}`;
  const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'protocols_item', op: 'get', method: 'GET' } });
  check(res, { 'get 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

function search() {
  const q = ['бюджет', 'протокол', 'встреча', 'план'][Math.floor(Math.random() * 4)];
  const url = `${BASE_URL}${ENDPOINTS.search}?q=${encodeURIComponent(q)}&limit=20`;
  const res = http.get(url, { headers: HEADERS, tags: { endpoint: 'search', op: 'search', method: 'GET' } });
  check(res, { 'search 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

function upload() {
  const fd = open('./fixtures/sample-meeting.mp4', 'b');
  if (fd === null) return null;
  const data = {
    file:  http.file(fd, 'sample-meeting.mp4', 'video/mp4'),
    title: `stress-${__VU}-${__ITER}`,
  };
  const res = http.post(`${BASE_URL}${ENDPOINTS.protocols}`, data, {
    headers: {
      'Content-Type':    'multipart/form-data',
      'Accept':          'application/json',
      'X-Correlation-Id': `${__VU}-${__ITER}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    },
    tags: { endpoint: 'protocols', op: 'upload', method: 'UPLOAD' },
  });
  check(res, { 'upload 2xx': (r) => r.status >= 200 && r.status < 300 });
  return res;
}

export default function () {
  pickWeighted([
    { weight: 0.60, value: listProtocols },
    { weight: 0.20, value: getProtocol    },
    { weight: 0.15, value: search         },
    { weight: 0.05, value: upload         },
  ])();
}