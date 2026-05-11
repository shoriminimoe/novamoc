/**
 * Typed fetch wrapper for the novaMOC HTTP API.
 *
 * Requests carry the bearer token from {@link getBearerToken} via the
 * `Authorization: Bearer <token>` header (ADR-017). Error responses with a
 * `Content-Type: application/problem+json` body (ADR-016) are parsed into a
 * {@link ProblemDetailsError} whose `.code` getter exposes the leaf segment
 * of `type` (with the `.html` suffix stripped) — the stable identifier
 * clients branch on.
 */

import { getBearerToken } from './token'

const ENV_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export interface ProblemBody {
  type: string
  title: string
  status: number
  detail: string
  instance: string
  // Per-RFC-9457 §3.2 extension members ride here as additional keys.
  [extension: string]: unknown
}

export class ProblemDetailsError extends Error {
  readonly body: ProblemBody
  readonly status: number

  constructor(body: ProblemBody) {
    super(body.detail || body.title)
    this.name = 'ProblemDetailsError'
    this.body = body
    this.status = body.status
  }

  /** The error code clients branch on — leaf of `type`, `.html` stripped. */
  get code(): string {
    const leaf = this.body.type.split('/').pop() ?? ''
    return leaf.replace(/\.html$/, '')
  }
}

export interface ApiClientOptions {
  baseUrl?: string
  getToken?: () => string | null
}

export interface ApiClient {
  get: <T>(path: string) => Promise<T>
  post: <T>(path: string, body: unknown) => Promise<T>
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = options.baseUrl ?? ENV_BASE_URL
  const getToken = options.getToken ?? getBearerToken

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    const token = getToken()
    if (token !== null) headers.Authorization = `Bearer ${token}`
    if (body !== undefined) headers['Content-Type'] = 'application/json'

    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })

    if (!response.ok) {
      const contentType = response.headers.get('content-type') ?? ''
      if (contentType.startsWith('application/problem+json')) {
        const problem = (await response.json()) as ProblemBody
        throw new ProblemDetailsError(problem)
      }
      const text = await response.text()
      throw new Error(`HTTP ${response.status}: ${text || response.statusText}`)
    }

    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  return {
    get: <T>(path: string) => request<T>('GET', path),
    post: <T>(path: string, body: unknown) => request<T>('POST', path, body),
  }
}
