import adapter from '@sveltejs/adapter-static'
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

// novaMOC is a local-first SPA (ADR-001, ADR-003 / ADR-021): we ship a static
// bundle and run entirely client-side. ``adapter-static`` with a ``fallback``
// emits a fallback HTML the host serves for any path the bundle owns; the
// root layout sets ``ssr=false`` + ``prerender=false`` so SvelteKit never
// tries to server-render or build-time-prerender our routes (they all need a
// browser — OPFS, ``fetch`` against a same-origin API, etc.).

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      fallback: '200.html',
    }),
  },
}

export default config
