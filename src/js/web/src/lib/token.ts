/**
 * Bearer-token storage for the SPA.
 *
 * The server identifies the active tenant from the bearer token (ADR-017).
 * v1 stores the token in `localStorage`; an empty / missing entry falls back
 * to `VITE_DEFAULT_BEARER_TOKEN` so a fresh checkout works without manual
 * setup. Replaced by a real auth flow when the tenant registry lands
 * (issue #19).
 */

const STORAGE_KEY = 'novamoc.bearer_token'

const ENV_DEFAULT =
  (import.meta.env.VITE_DEFAULT_BEARER_TOKEN as string | undefined) ?? ''

export function getBearerToken(): string | null {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  const value = stored ?? ENV_DEFAULT
  return value === '' ? null : value
}

export function setBearerToken(token: string | null): void {
  if (token === null || token === '') {
    window.localStorage.removeItem(STORAGE_KEY)
  } else {
    window.localStorage.setItem(STORAGE_KEY, token)
  }
}
