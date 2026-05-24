/// <reference types="vitest" />
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'

// In dev, forward the API surface to the Python server. The SPA always
// uses relative paths so production deployments can serve client and API
// from the same origin without rewriting URLs.
const API_PROXY_TARGET = process.env.NOVAMOC_API_URL ?? 'http://127.0.0.1:8000'
const API_PROXY_PATHS = ['/schema', '/events', '/problems', '/openapi']

// Serve dev over HTTPS with a self-signed cert. Mobile testing puts the
// dev server on a LAN IP, which is a non-secure context — and Web Crypto
// (``crypto.randomUUID``, ``crypto.subtle``) and other powerful APIs are
// gated on a secure context. HTTPS lifts that gate without polyfilling
// around it. Cert is auto-generated and cached by the plugin; first
// visit prompts the user to accept the self-signed warning.
export default defineConfig({
  plugins: [basicSsl(), svelte(), tailwindcss()],
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
      exclude: ['src/**/*.d.ts', 'tests/**', 'tests/e2e/**'],
      // No `thresholds:` block — the ratchet does the gating. Setting a
      // threshold here would either duplicate the ratchet's role or fight it.
      all: true,
    },
  },
})
