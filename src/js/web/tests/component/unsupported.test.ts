/**
 * Unit tests for the ``/unsupported`` blocking error page (issue
 * #140 / ADR-003). The page receives the failed precondition as
 * ``?missing=<feature>`` and must name BOTH the precondition AND
 * the supported browsers; missing or unknown values fall back to the
 * generic OPFS message rather than blanking out.
 *
 * Mocks ``$app/state`` so we can drive the ``page.url.searchParams``
 * the component reads without booting a real router.
 */
import { render, screen } from '@testing-library/svelte'
import { describe, expect, it, vi } from 'vitest'

// Mocked first so the import order matches the component's module graph.
vi.mock('$app/state', () => {
  let _url = new URL('https://example.com/unsupported')
  return {
    page: {
      get url() {
        return _url
      },
    },
    __setUrl(href: string) {
      _url = new URL(href)
    },
  }
})

// Re-import the mock module so we can drive the URL from the test body.
const appState = (await import('$app/state')) as unknown as {
  __setUrl: (href: string) => void
}

import UnsupportedPage from '../../src/routes/unsupported/+page.svelte'

describe('unsupported page', () => {
  it('names the OPFS precondition when missing=opfs', async () => {
    appState.__setUrl('https://example.com/unsupported?missing=opfs')
    render(UnsupportedPage)

    expect(screen.getByTestId('missing-precondition')).toHaveTextContent(
      /Origin Private File System/,
    )
    expect(screen.getByText('Chrome / Edge 109 or later (January 2023).')).toBeInTheDocument()
    expect(screen.getByText(/Safari 17 or later/)).toBeInTheDocument()
    expect(screen.getByText(/Firefox is best-effort/)).toBeInTheDocument()
  })

  it('names the sync-handle precondition when missing=sync_handle', async () => {
    appState.__setUrl('https://example.com/unsupported?missing=sync_handle')
    render(UnsupportedPage)

    expect(screen.getByTestId('missing-precondition')).toHaveTextContent(
      /synchronous access handles/,
    )
  })

  it('names the cross-origin isolation precondition when missing=cross_origin_isolation', async () => {
    appState.__setUrl(
      'https://example.com/unsupported?missing=cross_origin_isolation',
    )
    render(UnsupportedPage)

    expect(screen.getByTestId('missing-precondition')).toHaveTextContent(
      /cross-origin isolated/,
    )
  })

  it('falls back to the generic OPFS message when missing is absent', async () => {
    appState.__setUrl('https://example.com/unsupported')
    render(UnsupportedPage)

    expect(screen.getByTestId('missing-precondition')).toHaveTextContent(
      /Origin Private File System/,
    )
  })

  it('falls back to the generic OPFS message when missing is unknown', async () => {
    appState.__setUrl('https://example.com/unsupported?missing=bogus')
    render(UnsupportedPage)

    expect(screen.getByTestId('missing-precondition')).toHaveTextContent(
      /Origin Private File System/,
    )
  })

  it('always lists supported browsers', async () => {
    appState.__setUrl('https://example.com/unsupported?missing=cross_origin_isolation')
    render(UnsupportedPage)

    expect(screen.getByText(/Chrome \/ Edge 109/)).toBeInTheDocument()
    expect(screen.getByText(/Safari 17/)).toBeInTheDocument()
    expect(screen.getByText(/Firefox/)).toBeInTheDocument()
  })
})
