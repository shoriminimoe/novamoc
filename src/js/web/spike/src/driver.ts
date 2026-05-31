/**
 * Minimal stand-in for the @sqlite.org/sqlite-wasm OO API `db` object.
 *
 * This is the COMMON BASELINE every candidate sits on. Bundle-size deltas
 * we report exclude this driver (it's identical across all four) and isolate
 * only the abstraction layer (Kysely / Drizzle / hand-rolled / raw). We do not
 * pull the real WASM into the spike because (a) the WASM blob is fixed weight
 * for all four and (b) it dwarfs the JS deltas we're trying to resolve.
 */

export interface SqlExecOptions {
  sql: string
  bind?: unknown[]
  rowMode?: 'object' | 'array'
  returnValue?: 'resultRows'
}

export interface WasmDB {
  exec(opts: SqlExecOptions): Record<string, unknown>[]
}

/** A trivial in-memory fake so the spike code type-checks and "runs". */
export function makeDb(): WasmDB {
  const store: Record<string, unknown>[] = []
  return {
    exec(opts) {
      // Not a real SQL engine — just enough to exercise the code paths.
      void store
      return opts.returnValue === 'resultRows' ? [] : []
    },
  }
}
