/**
 * Setup script — seeds 10 protocols for load tests that need existing data
 * (stress, soak). Uses the k6 init lifecycle so it runs ONCE per process
 * before VU iterations start.
 *
 * Run:
 *   k6 run tests/load/setup.js
 *
 * Or via the orchestrator:
 *   ./scripts/run-all.sh
 *
 * After running, list the created ids via the standard list endpoint and
 * feed them into stress.js via -e PROTOCOL_IDS="uuid1,uuid2,...".
 */

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  scenarios: {
    seed: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: 10,
      maxDuration: '2m',
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.01'],
  },
};

const SAMPLE_TITLES = [
  'Еженедельный синк',
  'Планирование бюджета Q4',
  'Ретроспектива спринта',
  'Обзор roadmap H2',
  'Встреча с заказчиком',
  '1-1 менеджер / разработчик',
  'Стендап',
  'Дизайн-ревью',
  'Аудит инфраструктуры',
  'Демо фичи',
];

export default function () {
  const idx = __ITER;
  const title = `${SAMPLE_TITLES[idx % SAMPLE_TITLES.length]} #${idx + 1}`;

  // Lightweight seed: POST JSON (not multipart) — adjust endpoint if backend
  // requires multipart-only creation. The id field is captured so a follow-up
  // caller (e.g. stress.js) can re-use it.
  const res = http.post(
    `${BASE_URL}${ENDPOINTS.protocols}`,
    JSON.stringify({
      title,
      started_at: new Date(Date.now() - idx * 86400000).toISOString(),
      duration_sec: 600 + idx * 60,
      participants: ['Alice', 'Bob', 'Carol'].slice(0, (idx % 3) + 1),
    }),
    { headers: {
        'Content-Type':    'application/json',
        'Accept':          'application/json',
        'X-Correlation-Id': `${__VU}-${__ITER}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      }, tags: { endpoint: 'protocols', method: 'POST' } },
  );

  const ok = check(res, {
    'seed status 2xx': (r) => r.status >= 200 && r.status < 300,
  });

  if (ok) {
    try {
      const body = res.json();
      if (body && body.id) {
        console.log(`seeded id=${body.id} title="${title}"`);
      }
    } catch (_e) { /* tolerate non-JSON */ }
  } else {
    console.error(`seed failed: status=${res.status} body=${res.body}`);
  }
}