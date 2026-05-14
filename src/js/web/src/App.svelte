<script lang="ts">
  import SchemaBrowser from './lib/SchemaBrowser.svelte'
  import { getBearerToken, setBearerToken } from './lib/token'

  let token = $state(getBearerToken() ?? '')
  let reloadKey = $state(0)
  let overflowOpen = $state(false)

  function applyToken(): void {
    setBearerToken(token === '' ? null : token)
    reloadKey += 1
    overflowOpen = false
  }

  // Close the header overflow when the user clicks anywhere outside it.
  function onWindowClick(e: MouseEvent): void {
    if (!overflowOpen) return
    if (!(e.target instanceof Element)) return
    if (e.target.closest('[data-menu-region]')) return
    overflowOpen = false
  }
</script>

<svelte:window onclick={onWindowClick} />

<main class="flex h-screen flex-col">
  <header class="flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-3">
    <div>
      <h1 class="text-lg font-semibold">novaMOC</h1>
      <p class="text-xs text-gray-600">Schema management</p>
    </div>
    <div class="relative">
      <button
        type="button"
        data-menu-region
        aria-haspopup="menu"
        aria-expanded={overflowOpen}
        aria-label="More"
        class="rounded border border-gray-300 px-2 py-1 text-sm hover:bg-gray-50"
        onclick={() => (overflowOpen = !overflowOpen)}
      >
        ⋯
      </button>
      {#if overflowOpen}
        <div role="menu" data-menu-region class="absolute right-0 top-9 z-10 w-72 rounded border border-gray-300 bg-white p-3 text-sm shadow-md">
          <label for="bearer-token" class="block text-xs font-medium text-gray-700">Bearer token</label>
          <p class="mt-0.5 text-[10px] text-gray-500">Empty = fall back to <code>VITE_DEFAULT_BEARER_TOKEN</code>.</p>
          <div class="mt-2 flex gap-2">
            <input
              id="bearer-token"
              type="text"
              class="flex-1 rounded border border-gray-300 px-2 py-1 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              bind:value={token}
            />
            <button
              type="button"
              class="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
              onclick={applyToken}
            >
              Apply
            </button>
          </div>
        </div>
      {/if}
    </div>
  </header>
  <div class="flex-1 overflow-hidden">
    <SchemaBrowser {reloadKey} />
  </div>
</main>
