/**
 * Playwright config for novaMOC SPA browser e2e tests.
 *
 * Boots a dedicated API + Vite pair on non-default ports so the test
 * run is isolated from any local dev servers and from the shared
 * ``novamoc.sqlite`` dev DB:
 *
 * - API at ``E2E_API_PORT`` (8765) with an in-memory aiosqlite +
 *   ``static_pool=true`` so all requests share the same engine.
 * - Vite at ``E2E_APP_PORT`` (5174) with ``NOVAMOC_API_URL`` pointing
 *   the dev proxy at the test API.
 *
 * ``cwd: '../../..'`` on the API webServer is the repo root from
 * ``src/js/web/``, where ``uv run`` finds ``pyproject.toml``.
 */

import { defineConfig } from '@playwright/test'

const API_PORT = 8765
const APP_PORT = 5174
const API_URL = `http://127.0.0.1:${API_PORT}`
// Vite serves HTTPS via ``@vitejs/plugin-basic-ssl`` so the browser sees
// a secure context and ``crypto.randomUUID`` / ``crypto.subtle`` are
// defined. The cert is self-signed, hence ``ignoreHTTPSErrors`` below.
const APP_URL = `https://127.0.0.1:${APP_PORT}`

// ``E2E_SKIP_API=1`` runs only the Vite dev server. Some e2e tests
// (e.g. the OPFS-probe blocking-UI test, issue #140) don't touch the
// Python API at all — the layout's probe redirects to ``/unsupported``
// before any backend call — and the existing in-memory API webServer
// doesn't bootstrap Alembic (ADR-021), so it currently crashes at
// startup. Until a proper test harness lands (see issue #81), opting
// out keeps the SPA-only e2e tests runnable.
const SKIP_API = process.env.E2E_SKIP_API === '1'

const apiWebServer = {
  command: `uv run litestar --app novamoc.asgi:create_app run --host 127.0.0.1 --port ${API_PORT}`,
  cwd: '../../..',
  env: {
    NOVAMOC_DB_URL: 'sqlite+aiosqlite:///:memory:',
    NOVAMOC_DB_STATIC_POOL: 'true',
  },
  url: `${API_URL}/openapi`,
  reuseExistingServer: false,
  timeout: 60_000,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
}

const appWebServer = {
  command: `npm run dev -- --port ${APP_PORT} --strictPort`,
  env: {
    NOVAMOC_API_URL: API_URL,
  },
  url: APP_URL,
  ignoreHTTPSErrors: true,
  reuseExistingServer: false,
  timeout: 30_000,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: APP_URL,
    trace: 'retain-on-failure',
    ignoreHTTPSErrors: true,
  },
  webServer: SKIP_API ? [appWebServer] : [apiWebServer, appWebServer],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
