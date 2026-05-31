/**
 * Playwright config for novaMOC SPA browser e2e tests.
 *
 * Boots a dedicated API + Vite pair on non-default ports so the test
 * run is isolated from any local dev servers and from the shared
 * ``novamoc.sqlite`` dev DB:
 *
 * - API at ``E2E_API_PORT`` (8765) backed by a throwaway *file* SQLite
 *   DB under the OS temp dir. The app's ADR-021 startup gate
 *   (``db/_startup.py``) refuses to serve a DB that isn't at Alembic
 *   HEAD, and an in-memory DB lives and dies with its owning process —
 *   so a separate ``alchemy upgrade head`` step would migrate a
 *   throwaway DB that vanishes before ``litestar run`` connects. The
 *   fix: point ``NOVAMOC_DB_URL`` at a file, run the migrate + seed
 *   chain (``just bootstrap-dev`` = ``db-init`` + ``bootstrap-admin``)
 *   against that file, then launch ``litestar run`` against the *same*
 *   file. The gate then passes and a ``Development`` tenant with an
 *   ``admin``/``admin`` user is seeded for happy-path login e2e.
 * - Vite at ``E2E_APP_PORT`` (5174) with ``NOVAMOC_API_URL`` pointing
 *   the dev proxy at the test API.
 *
 * ``cwd: '../../..'`` on the API webServer is the repo root from
 * ``src/js/web/``, where ``uv run`` finds ``pyproject.toml``.
 */

import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { defineConfig } from '@playwright/test'

const API_PORT = 8765
const APP_PORT = 5174
const API_URL = `http://127.0.0.1:${API_PORT}`
// Vite serves HTTPS via ``@vitejs/plugin-basic-ssl`` so the browser sees
// a secure context and ``crypto.randomUUID`` / ``crypto.subtle`` are
// defined. The cert is self-signed, hence ``ignoreHTTPSErrors`` below.
const APP_URL = `https://127.0.0.1:${APP_PORT}`

// Throwaway file DB under the OS temp dir — never inside the repo tree,
// so there's nothing to gitignore and a stale file from a crashed prior
// run is removed (``rm -f``) at the start of the boot chain. The same
// path threads through migrate, seed, and serve so all three reach one
// DB. ``aiosqlite`` wants four slashes for an absolute path
// (``sqlite+aiosqlite:////abs/path``).
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
    ignoreHTTPSErrors: true,
  },
  webServer: [
    {
      // (1) drop any stale DB file, (2) migrate + seed the file DB via
      // ``just bootstrap-dev`` (db-init = ``alchemy upgrade head`` then
      // ``bootstrap-admin`` for the Development tenant + admin/admin),
      // (3) serve ``litestar run`` against the same file so the ADR-021
      // startup gate sees a DB at HEAD. ``NOVAMOC_DB_URL`` in ``env``
      // (below) threads through all three. ``rm -f`` is portable across
      // the POSIX shells Playwright spawns ``command`` through.
      command:
        `rm -f '${E2E_DB_PATH}' '${E2E_DB_PATH}-wal' '${E2E_DB_PATH}-shm' && ` +
        `just bootstrap-dev && ` +
        `uv run litestar --app novamoc.asgi:create_app run --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../../..',
      env: {
        NOVAMOC_DB_URL: E2E_DB_URL,
        // Cookie set over plain-HTTP loopback to the API; the SPA talks
        // to it through the Vite dev proxy, so the browser only ever
        // sees the HTTPS origin. Relax Secure so the cookie survives the
        // proxied login (mirrors the dev opt-out documented in
        // ``AuthSettings.session_cookie_secure``).
        NOVAMOC_AUTH_SESSION_COOKIE_SECURE: 'false',
      },
      url: `${API_URL}/openapi`,
      reuseExistingServer: false,
      // Generous: the chain runs Alembic migrations and an argon2id
      // password hash (64 MiB, t=3) for the seeded admin before serving.
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --port ${APP_PORT} --strictPort`,
      env: {
        NOVAMOC_API_URL: API_URL,
      },
      url: APP_URL,
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
