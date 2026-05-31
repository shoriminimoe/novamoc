import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import { sveltekit } from '@sveltejs/kit/vite'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'

// Vite's `server.headers` reach assets but not the SvelteKit-rendered HTML
// document, so `crossOriginIsolated` (and thus SharedArrayBuffer / the OPFS
// VFS, ADR-003) stays off. A dev-server middleware sets COOP/COEP on every
// response, document included. In prod the static host sets them (ADR-021).
const crossOriginIsolation: Plugin = {
  name: 'novamoc-cross-origin-isolation',
  configureServer(server) {
    server.middlewares.use((_req, res, next) => {
      res.setHeader('Cross-Origin-Opener-Policy', 'same-origin')
      res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp')
      next()
    })
  },
}

// In dev, forward the API surface to the Python server. The SPA always
// uses relative paths so production deployments can serve client and API
// from the same origin without rewriting URLs.
const API_PROXY_TARGET = process.env.NOVAMOC_API_URL ?? 'http://127.0.0.1:8000'
const API_PROXY_PATHS = ['/auth', '/schema', '/events', '/problems', '/openapi']

// Serve dev over HTTPS with a self-signed cert by default. Mobile
// testing puts the dev server on a LAN IP, which is a non-secure
// context — and Web Crypto (``crypto.randomUUID``, ``crypto.subtle``)
// and other powerful APIs are gated on a secure context. HTTPS lifts
// that gate without polyfilling around it. Cert is auto-generated and
// cached by the plugin; first visit prompts the user to accept the
// self-signed warning. Set ``NOVAMOC_NO_HTTPS=1`` to opt out for tooling
// that can't bypass self-signed certs (e.g. headless verification).
//
// COOP/COEP are required by ADR-003 (SQLite-WASM via OPFS uses
// ``SharedArrayBuffer``, which is gated on cross-origin isolation). They
// have to be set by whoever serves the bundle — in dev that's Vite, in
// prod that's whatever HTTP server hosts ``build/`` (see ADR-021).
export default defineConfig({
  plugins: [
    ...(process.env.NOVAMOC_NO_HTTPS ? [] : [basicSsl()]),
    crossOriginIsolation,
    tailwindcss(),
    sveltekit(),
  ],
  // Under Vitest, force Svelte's ``browser`` export condition so we get
  // the client build rather than the SSR build (which throws
  // ``lifecycle_function_unavailable`` on ``mount``). Set conditionally so
  // we don't override Vite's defaults outside test runs — passing an
  // empty array would replace the default ``['module', 'browser', …]``
  // and break ``vite dev``.
  ...(process.env.VITEST
    ? { resolve: { conditions: ['browser'] } }
    : {}),
  server: {
    proxy: Object.fromEntries(
      API_PROXY_PATHS.map((p) => [p, { target: API_PROXY_TARGET, changeOrigin: false }]),
    ),
  },
  test: {
    // Component tests run in jsdom; Playwright e2e is a separate suite under tests/e2e/.
    environment: 'jsdom',
    globals: true,
    include: ['tests/component/**/*.test.ts'],
    setupFiles: ['./tests/component/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: 'coverage',
      include: ['src/**/*.{ts,svelte}'],
      exclude: [
        'src/**/*.d.ts',
        'tests/**',
        'tests/e2e/**',
        // The worker body does real OPFS I/O in DedicatedWorker scope —
        // not reachable in jsdom; covered by the Playwright e2e instead.
        'src/lib/db/probe.worker.ts',
      ],
      // No `thresholds:` block — the ratchet does the gating. Setting a
      // threshold here would either duplicate the ratchet's role or fight it.
    },
  },
})
