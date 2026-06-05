<script lang="ts">
	// Minimal snapshot-ingest progress surface (E1.7). The FULL /_debug/sync
	// surface is E1.12 — this page only proves the bulk-snapshot ingest and its
	// per-table progress modal. It opens the local DB for the active tenant,
	// runs ingestSnapshot, and renders a blocking modal that fills in per-table
	// row/batch counts as batches arrive.
	import { createSubscriber } from 'svelte/reactivity'

	import { openLocalDb } from '$lib/db/bootstrap'
	import { SNAPSHOT_TABLES, SnapshotProgressStore } from '$lib/sync/_progress'
	import { ingestSnapshot } from '$lib/sync/snapshot'

	let { tenantId = '' }: { tenantId?: string } = $props()

	const store = new SnapshotProgressStore()

	let running = $state(false)
	let result = $state<{ cursor: number; schema_version: number } | null>(null)
	let errorMessage = $state<string | null>(null)

	// Bridge the external store into Svelte reactivity: createSubscriber wires
	// the store's subscribe contract to the effect graph so reading `progress`
	// inside the template tracks it, re-deriving whenever a batch lands. No
	// state-assigning $effect, no manual teardown.
	const subscribe = createSubscriber((update) => store.subscribe(update))
	const progress = $derived.by(() => {
		subscribe()
		return store.snapshot()
	})

	// The modal blocks while a transfer is in flight or has just finished, so
	// the operator sees the terminal counts before dismissing.
	const modalOpen = $derived(running || result !== null || errorMessage !== null)

	async function start() {
		if (running || tenantId === '') return
		running = true
		result = null
		errorMessage = null
		store.reset('running')
		try {
			const db = await openLocalDb(tenantId)
			result = await ingestSnapshot({ store: db, tenantId, progress: store })
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error)
		} finally {
			running = false
		}
	}

	function dismiss() {
		if (running) return
		result = null
		errorMessage = null
	}

	const TABLE_LABELS: Record<(typeof SNAPSHOT_TABLES)[number], string> = {
		assets: 'Assets',
		asset_field_values: 'Asset field values',
		maintenance_records: 'Maintenance records',
		maintenance_record_field_values: 'Maintenance record field values',
	}
</script>

<section class="mx-auto max-w-xl p-6">
	<h1 class="text-lg font-semibold">Snapshot ingest</h1>
	<p class="mt-1 text-sm text-gray-600">
		Hydrate the local projection from <code>GET /snapshot</code>. Debug-only
		surface (E1.7); the full sync debug page is E1.12.
	</p>

	<label class="mt-4 flex flex-col gap-1 text-sm">
		<span>Tenant id</span>
		<input
			type="text"
			bind:value={tenantId}
			placeholder="00000000-0000-0000-0000-000000000000"
			class="rounded border border-gray-300 px-3 py-2 focus:border-gray-500 focus:outline-none"
		/>
	</label>

	<button
		type="button"
		onclick={start}
		disabled={running || tenantId === ''}
		class="mt-4 rounded border border-gray-300 px-3 py-2 text-sm font-medium disabled:opacity-60"
	>
		{running ? 'Ingesting…' : 'Start snapshot ingest'}
	</button>
</section>

{#if modalOpen}
	<div
		class="fixed inset-0 flex items-center justify-center bg-black/40 p-4"
		role="dialog"
		aria-modal="true"
		aria-label="Snapshot ingest progress"
	>
		<div class="w-full max-w-md rounded bg-white p-6 shadow-lg">
			<h2 class="text-base font-semibold">
				{#if errorMessage !== null}
					Snapshot ingest failed
				{:else if result !== null}
					Snapshot ingest complete
				{:else if progress.phase === 'restarted'}
					Snapshot restarted — server advanced
				{:else}
					Ingesting snapshot…
				{/if}
			</h2>

			<p class="mt-1 text-sm text-gray-600">
				{progress.totalRows} rows synced
			</p>

			<ul class="mt-4 flex flex-col gap-2 text-sm">
				{#each SNAPSHOT_TABLES as table (table)}
					{@const t = progress.tables[table]}
					<li class="flex items-center justify-between gap-4">
						<span>{TABLE_LABELS[table]}</span>
						<span class="tabular-nums text-gray-600">
							{t.rows} rows · {t.batches} batches
						</span>
					</li>
				{/each}
			</ul>

			{#if errorMessage !== null}
				<p role="alert" class="mt-4 text-sm text-red-700">{errorMessage}</p>
			{/if}

			{#if result !== null}
				<p class="mt-4 text-sm text-gray-600">
					Cursor {result.cursor} · schema v{result.schema_version}
				</p>
			{/if}

			{#if !running}
				<button
					type="button"
					onclick={dismiss}
					class="mt-4 rounded border border-gray-300 px-3 py-2 text-sm font-medium"
				>
					Dismiss
				</button>
			{/if}
		</div>
	</div>
{/if}
