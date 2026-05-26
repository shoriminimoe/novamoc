// novaMOC is local-first (ADR-001 / ADR-003) and the SPA bundle is a
// CSR-only ``adapter-static`` build (ADR-021). Disabling SSR and prerender
// at the root layout opts every route out of server / build-time rendering
// — the only thing that runs is the client bundle in the browser.
export const ssr = false
export const prerender = false
