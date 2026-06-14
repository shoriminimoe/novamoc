/**
 * Column (de)serialisation helpers shared by the repository mappers.
 *
 * SQLite has no boolean or JSON affinity: booleans land as INTEGER 0/1 and JSON
 * columns as TEXT. Each repo's row mapper is the single chokepoint (per the
 * spike) that converts between the on-disk representation and the JS-native row
 * type, so the conversions live here rather than being re-derived per table.
 */

import type { Json } from './_rows'

/** INTEGER 0/1 (or any SQLite truthy/falsy value) to `boolean`. */
export function toBool(value: unknown): boolean {
  return Boolean(value)
}

/** `boolean` to INTEGER 0/1 for a bind list. */
export function fromBool(value: boolean): number {
  return value ? 1 : 0
}

/**
 * A TEXT JSON column to its parsed value. A `null` column (NULL value, e.g. a
 * cleared field) parses to `null`; a missing string is treated as `null` too.
 */
export function parseJson(value: unknown): Json {
  if (value === null || value === undefined) {
    return null
  }
  return JSON.parse(value as string)
}

/** A JS value to a TEXT JSON column for a bind list. `null` stays SQL NULL. */
export function stringifyJson(value: Json): string | null {
  if (value === null || value === undefined) {
    return null
  }
  return JSON.stringify(value)
}
