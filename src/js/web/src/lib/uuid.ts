/**
 * Random UUIDv4 generator with a secure-context fallback.
 *
 * ``crypto.randomUUID`` is only defined in secure contexts (HTTPS or
 * loopback). The dev server is served over a LAN IP for mobile testing,
 * which is a non-secure context, so a Vivaldi-on-Android client throws
 * ``TypeError: crypto.randomUUID is not a function`` on the bare call.
 *
 * ``crypto.getRandomValues`` *does* work in non-secure contexts (it's
 * been available since 2015 across all browsers) and is enough to
 * synthesize a v4 UUID by hand. We prefer the native ``randomUUID``
 * when available (one C call, no allocation) and fall back to a
 * 16-byte ``getRandomValues`` + format on platforms that don't have it.
 */

export function randomUUID(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  // RFC 4122 §4.4 — set the version (4) and variant (10xx) bits.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
