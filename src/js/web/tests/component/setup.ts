/**
 * Vitest setup for novaMOC component tests.
 *
 * Loads the ``@testing-library/jest-dom`` matchers (``.toBeVisible``,
 * ``.toHaveTextContent``, etc.), unmounts every rendered component
 * after each test, and plugs a deterministic ``crypto.randomUUID``
 * into jsdom (which doesn't ship one) so create flows can run
 * without polyfilling the real Web Crypto API.
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/svelte'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom doesn't implement ``crypto.randomUUID`` (it landed in Node 19+
// but jsdom's globalThis.crypto is its own minimal shim). The schema
// commands path needs UUID-shaped strings; the actual value doesn't
// matter for assertions.
if (typeof globalThis.crypto === 'undefined') {
  Object.defineProperty(globalThis, 'crypto', { value: {} })
}
let uuidCounter = 0
;(globalThis.crypto as unknown as { randomUUID?: () => string }).randomUUID =
  (): string => {
    uuidCounter += 1
    return `00000000-0000-0000-0000-${uuidCounter.toString(16).padStart(12, '0')}`
  }
