<script lang="ts">
  import { createApiClient, ProblemDetailsError } from './lib/api'
  import { getBearerToken, setBearerToken } from './lib/token'

  type ProbeResult =
    | { kind: 'success'; body: unknown }
    | { kind: 'error'; status: number; code: string; body: unknown }

  let token = $state(getBearerToken() ?? '')
  let result = $state<ProbeResult | null>(null)
  let loading = $state(false)

  function syncToken(): void {
    setBearerToken(token === '' ? null : token)
  }

  async function runProbe(client: ReturnType<typeof createApiClient>): Promise<void> {
    loading = true
    result = null
    try {
      const body = await client.get('/schema')
      result = { kind: 'success', body }
    } catch (e) {
      if (e instanceof ProblemDetailsError) {
        result = { kind: 'error', status: e.status, code: e.code, body: e.body }
      } else {
        result = { kind: 'error', status: 0, code: 'network_error', body: String(e) }
      }
    } finally {
      loading = false
    }
  }

  function probeSuccess(): void {
    void runProbe(createApiClient())
  }

  function probeError(): void {
    void runProbe(createApiClient({ getToken: () => 'invalid-token' }))
  }
</script>

<main class="mx-auto max-w-3xl p-8">
  <header class="mb-6">
    <h1 class="text-3xl font-bold">novaMOC</h1>
    <p class="text-sm text-gray-600">M4.1 — bearer-token + API client smoke test</p>
  </header>

  <section class="mb-6">
    <label for="bearer-token" class="mb-1 block text-sm font-medium">Bearer token</label>
    <input
      id="bearer-token"
      type="text"
      class="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm"
      placeholder="(empty — falls back to VITE_DEFAULT_BEARER_TOKEN)"
      bind:value={token}
      onblur={syncToken}
    />
  </section>

  <section class="mb-6 flex gap-3">
    <button
      type="button"
      class="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
      disabled={loading}
      onclick={probeSuccess}
    >
      Probe success (GET /schema)
    </button>
    <button
      type="button"
      class="rounded bg-gray-700 px-4 py-2 text-white disabled:opacity-50"
      disabled={loading}
      onclick={probeError}
    >
      Probe error (bad token &rarr; 401)
    </button>
  </section>

  {#if result !== null}
    <section class="rounded border border-gray-200 p-4">
      {#if result.kind === 'success'}
        <h2 class="mb-2 text-lg font-semibold text-green-700">Success</h2>
        <pre class="overflow-x-auto rounded bg-gray-50 p-3 text-xs">{JSON.stringify(
            result.body,
            null,
            2,
          )}</pre>
      {:else}
        <h2 class="mb-2 text-lg font-semibold text-red-700">
          {result.status} &middot; {result.code}
        </h2>
        <pre class="overflow-x-auto rounded bg-gray-50 p-3 text-xs">{JSON.stringify(
            result.body,
            null,
            2,
          )}</pre>
      {/if}
    </section>
  {/if}
</main>
