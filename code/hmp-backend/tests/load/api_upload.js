/**
 * Upload test — POST /protocols with a multipart ~100KB video fixture.
 *
 * Note: real backend upload latency is dominated by parsing + storage write,
 * which is why the NFR threshold here is relaxed (p95 < 500ms).
 * Error budget: < 5% (uploads are flaky in test envs — network, IO, MIME).
 *
 * Run:
 *   k6 run tests/load/api_upload.js
 *
 * Override fixture:
 *   k6 run -e FIXTURE_PATH=/abs/path/to/file.mp4 tests/load/api_upload.js
 */

import http from 'k6/http';
import { check, fail } from 'k6';
import { BASE_URL, ENDPOINTS, HEADERS } from './config.js';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    'http_req_duration{upload:protocol}': ['p(95)<500'],
    'http_req_duration':                 ['p(95)<500'],
    'http_req_failed':                   ['rate<0.05'],
  },
};

const FIXTURE_PATH = __ENV.FIXTURE_PATH || './fixtures/sample-meeting.mp4';
const FILE_NAME    = 'sample-meeting.mp4';

export default function () {
  const fd = open(FIXTURE_PATH, 'b');
  if (fd === null) {
    fail(`Cannot open fixture file: ${FIXTURE_PATH}`);
    return;
  }

  const data = {
    file:       http.file(fd, FILE_NAME, 'video/mp4'),
    title:      `load-test-${__VU}-${__ITER}`,
    started_at: new Date().toISOString(),
  };

  const res = http.post(`${BASE_URL}${ENDPOINTS.protocols}`, data, {
    headers: {
      'Content-Type':    'multipart/form-data',
      'Accept':          'application/json',
      'X-Correlation-Id': `${__VU}-${__ITER}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    },
    tags: { endpoint: 'protocols', method: 'UPLOAD', upload: 'protocol' },
  });

  check(res, {
    'upload status 2xx':     (r) => r.status >= 200 && r.status < 300,
    'upload returns id':     (r) => {
      try { return !!r.json().id; } catch (_e) { return false; }
    },
  });
}