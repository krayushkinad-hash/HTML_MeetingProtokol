/**
 * Shared k6 configuration & helpers for HTML_MeetingProtokol load tests.
 *
 * Usage in test scripts:
 *   import { BASE_URL, HEADERS, getJSON, postJSON, uploadFile } from './config.js';
 *
 * Override via environment:
 *   k6 run -e BASE_URL=https://staging.example.com tests/load/api_read.js
 *
 * Note on k6 syntax: k6's bundled babel parser does NOT support object-spread
 * (e.g. `{...a, ...b}`) in all positions. We therefore build objects with
 * Object.assign() — works on every supported k6 version (>= 0.49).
 */

import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';

// Counter for failures captured inside the helpers (visible in test output).
export const errorRate = new Rate('errors');

// ---- Base configuration ---------------------------------------------------

export const BASE_URL    = __ENV.BASE_URL || 'http://127.0.0.1:8000';
export const API_PREFIX  = '/api/v1/hmp';

// All /api/v1/hmp/* endpoints
export const ENDPOINTS = {
  health:        '/health',
  protocols:     `${API_PREFIX}/protocols`,
  protocolItem:  (id) => `${API_PREFIX}/protocols/${id}`,
  calendar:      `${API_PREFIX}/calendar`,
  search:        `${API_PREFIX}/search`,
  utterances:    (id) => `${API_PREFIX}/protocols/${id}/utterances`,
  transcribe:    `${API_PREFIX}/transcribe/status`,
};

// Default JSON headers — note: per-request correlation id is added inside
// `requestHeaders()` below because k6 only defines `__VU`/`__ITER` inside
// the default function, not at module scope.
export const HEADERS = {
  'Content-Type': 'application/json',
  'Accept':       'application/json',
};

/**
 * Build a fresh headers object with a per-request X-Correlation-Id.
 * Use this everywhere you'd otherwise reference the static HEADERS const.
 */
export function requestHeaders(extra) {
  if (extra === undefined) extra = {};
  return Object.assign({
    'Content-Type':    'application/json',
    'Accept':          'application/json',
    'X-Correlation-Id': correlationId(),
  }, extra);
}

// ---- Helpers --------------------------------------------------------------

/**
 * GET request that returns a parsed JSON body and asserts status 2xx.
 */
export function getJSON(path, params) {
  if (params === undefined) params = {};
  const opts = Object.assign({
    headers: requestHeaders(),
    tags:    { endpoint: path, method: 'GET' },
  }, params);

  const res = http.get(`${BASE_URL}${path}`, opts);

  const ok = res.status >= 200 && res.status < 300;
  const passed = check(res, {
    'GET status 2xx': (r) => r.status >= 200 && r.status < 300,
    'GET has body':   (r) => r.body && r.body.length > 0,
  });
  if (!passed) errorRate.add(!ok);

  let body = null;
  try { body = res.json(); } catch (_e) { /* tolerate non-JSON */ }
  return { res, body, ok };
}

/**
 * POST request with JSON body. Returns parsed body + ok flag.
 */
export function postJSON(path, jsonBody, params) {
  if (params === undefined) params = {};
  const opts = Object.assign({
    headers: requestHeaders({ 'Content-Type': 'application/json' }),
    tags:    { endpoint: path, method: 'POST' },
  }, params);

  const res = http.post(`${BASE_URL}${path}`, JSON.stringify(jsonBody), opts);

  const ok = res.status >= 200 && res.status < 300;
  const passed = check(res, {
    'POST status 2xx': (r) => r.status >= 200 && r.status < 300,
  });
  if (!passed) errorRate.add(!ok);

  let body = null;
  try { body = res.json(); } catch (_e) { /* tolerate non-JSON */ }
  return { res, body, ok };
}

/**
 * Multipart upload from a file path. Use for POST /protocols with media.
 */
export function uploadFile(path, filePath, fileName, formFields) {
  if (formFields === undefined) formFields = {};
  const fd = open(filePath, 'b');
  if (fd === null) {
    console.error(`uploadFile: cannot open ${filePath}`);
    errorRate.add(1);
    return { res: null, body: null, ok: false };
  }

  const data = Object.assign({
    file: http.file(fd, fileName, 'video/mp4'),
  }, formFields);

  const opts = {
    headers: requestHeaders({ 'Content-Type': 'multipart/form-data' }),
    tags:    { endpoint: path, method: 'UPLOAD' },
  };

  const res = http.post(`${BASE_URL}${path}`, data, opts);

  const ok = res.status >= 200 && res.status < 300;
  const passed = check(res, {
    'UPLOAD status 2xx': (r) => r.status >= 200 && r.status < 300,
  });
  if (!passed) errorRate.add(!ok);

  let body = null;
  try { body = res.json(); } catch (_e) { /* tolerate non-JSON */ }
  return { res, body, ok };
}

/**
 * Random uuid v4 (no external dep — k6 ships crypto.randomUUID only in v0.50+).
 * Uses Math.random as a fallback that is sufficient for fake-id polling tests.
 */
export function randomUUID() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  const hex = () => Math.floor(Math.random() * 0x100000000).toString(16).padStart(8, '0');
  return `${hex()}-${hex().slice(0, 4)}-4${hex().slice(0, 3)}-${(0x8 + Math.floor(Math.random() * 4)).toString(16)}${hex().slice(0, 3)}-${hex()}${hex().slice(0, 4)}`;
}

/**
 * Random item picker for weighted scenarios.
 */
export function pickWeighted(items) {
  // items: [{ weight: 0.8, value: fn1 }, { weight: 0.2, value: fn2 }]
  const r = Math.random();
  let acc = 0;
  for (let i = 0; i < items.length; i++) {
    acc += items[i].weight;
    if (r <= acc) return items[i].value;
  }
  return items[items.length - 1].value;
}

/**
 * Build a per-VU/per-iteration correlation id. Uses k6 globals (__VU, __ITER)
 * which are only available inside the default function, not at module scope.
 */
export function correlationId() {
  return `${__VU}-${__ITER}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

// ---- Standard threshold set (NFR §3.1) ------------------------------------
export const NFR_THRESHOLDS = {
  // Synchronous read endpoints
  'http_req_duration': ['p(95)<200'],
  'http_req_failed':   ['rate<0.01'],
};