/**
 * Playwright config for the novaMOC SPA browser e2e tests.
 *
 * Boots an isolated API + Vite pair off the shared dev DB. The API runs
 * against a throwaway file SQLite DB because the startup gate (ADR-021)
 * refuses a DB that isn't at Alembic HEAD, and an in-memory DB wouldn't
 * survive the gap between a separate migrate step and `litestar run` —
 * so we migrate + seed a file, then serve that same file.
 */

import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { defineConfig } from '@playwright/test'

const API_PORT = 8765
const APP_PORT = 5174
const API_URL = `http://127.0.0.1:${API_PORT}`
// Plain HTTP on a loopback origin: it's a secure context even without
// TLS (so crypto + crossOriginIsolated still work), and it dodges the
// self-signed-cert probe and the IPv4/IPv6 localhost mismatch that make
// basic-ssl flaky on CI.
const APP_URL = `http://127.0.0.1:${APP_PORT}`

// Outside the repo tree so there's nothing to gitignore. aiosqlite
// needs four slashes for an absolute path (the leading `/` is the third).
const E2E_DB_PATH = join(tmpdir(), 'novamoc-e2e.sqlite')
const E2E_DB_URL = `sqlite+aiosqlite:///${E2E_DB_PATH}`

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
  },
  webServer: [
    {
      // Drop any stale file, migrate + seed, then serve the same DB.
      command:
        `rm -f '${E2E_DB_PATH}' '${E2E_DB_PATH}-wal' '${E2E_DB_PATH}-shm' && ` +
        `just bootstrap-dev && ` +
        `uv run litestar --app novamoc.asgi:create_app run --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../../..',
      env: {
        NOVAMOC_DB_URL: E2E_DB_URL,
        // Relax Secure so the session cookie is sent over the plain-HTTP
        // loopback (mirrors AuthSettings.session_cookie_secure's opt-out).
        NOVAMOC_AUTH_SESSION_COOKIE_SECURE: 'false',
      },
      url: `${API_URL}/openapi`,
      reuseExistingServer: false,
      // Generous: migrations + an argon2 hash run before the API serves.
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Bind to 127.0.0.1, not localhost, so the IPv4 readiness probe
      // matches the socket — on CI, localhost may resolve to ::1 first
      // and hang the probe. NOVAMOC_NO_HTTPS drops TLS (see APP_URL).
      command: `npm run dev -- --port ${APP_PORT} --strictPort --host 127.0.0.1`,
      env: {
        NOVAMOC_API_URL: API_URL,
        NOVAMOC_NO_HTTPS: '1',
      },
      url: APP_URL,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
