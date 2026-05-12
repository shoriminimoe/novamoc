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
  server: {
    proxy: Object.fromEntries(
      API_PROXY_PATHS.map((p) => [p, { target: API_PROXY_TARGET, changeOrigin: false }]),
    ),
  },
})
