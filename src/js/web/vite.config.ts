import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// In dev, forward the API surface to the Python server. The SPA always
// uses relative paths so production deployments can serve client and API
// from the same origin without rewriting URLs.
const API_PROXY_TARGET = process.env.NOVAMOC_API_URL ?? 'http://127.0.0.1:8000'
const API_PROXY_PATHS = ['/schema', '/events', '/problems', '/openapi']

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      API_PROXY_PATHS.map((p) => [p, { target: API_PROXY_TARGET, changeOrigin: false }]),
    ),
  },
})
