import { defineConfig } from 'vite'

// Build one candidate at a time so each output dir contains ONLY that
// candidate's code + its deps. CANDIDATE=handrolled|kysely|drizzle|raw
//
// The driver shim (src/driver.ts) is inlined into every bundle but is
// identical (~15 lines) across all four, so the *delta* between candidates is
// purely the abstraction layer. The real @sqlite.org/sqlite-wasm WASM blob is
// likewise common to all four and is not part of this measurement.
const candidate = process.env.CANDIDATE ?? 'handrolled'

export default defineConfig({
  build: {
    outDir: `dist/${candidate}`,
    minify: 'esbuild',
    target: 'es2022',
    reportCompressedSize: true,
    lib: {
      entry: `src/entry_${candidate}.ts`,
      formats: ['es'],
      fileName: () => `bundle.js`,
    },
  },
})
