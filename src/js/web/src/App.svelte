<script lang="ts">
  import SchemaBrowser from './lib/SchemaBrowser.svelte'
  import { getBearerToken, setBearerToken } from './lib/token'

  let token = $state(getBearerToken() ?? '')
  let reloadKey = $state(0)

  function applyToken(): void {
    setBearerToken(token === '' ? null : token)
    reloadKey += 1
  }
</script>

<main class="mx-auto max-w-5xl p-8">
  <header class="mb-6">
    <h1 class="text-3xl font-bold">novaMOC</h1>
    <p class="text-sm text-gray-600">Schema browser</p>
  </header>

  <section class="mb-8">
    <label for="bearer-token" class="mb-1 block text-sm font-medium">
      Bearer token
    </label>
    <div class="flex gap-2">
      <input
        id="bearer-token"
        type="text"
        class="flex-1 rounded border border-gray-300 px-3 py-2 font-mono text-sm"
        placeholder="(empty — falls back to VITE_DEFAULT_BEARER_TOKEN)"
        bind:value={token}
        onblur={applyToken}
      />
      <button
        type="button"
        class="rounded bg-blue-600 px-4 py-2 text-sm text-white"
        onclick={applyToken}
      >
        Apply
      </button>
    </div>
  </section>

  <SchemaBrowser {reloadKey} />
</main>
