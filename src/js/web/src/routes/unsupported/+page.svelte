<script lang="ts">
	import { page } from '$app/state'
	import type { MissingFeature } from '$lib/db/probe'

	/**
	 * Blocking error page rendered when ``probeOpfs`` fails (ADR-003).
	 *
	 * The probe reason rides in as ``?missing=<feature>`` so the page
	 * survives a reload and a direct visit names the same precondition
	 * the user originally hit. Unknown / missing values default to the
	 * generic "OPFS" message — better than blanking out.
	 */

	type Reason = {
		title: string
		detail: string
	}

	const REASONS: Record<MissingFeature, Reason> = {
		opfs: {
			title: 'Origin Private File System (OPFS) is not available.',
			detail:
				'novaMOC stores your data locally in OPFS. Your browser does not expose ' +
				'``navigator.storage.getDirectory``, so the app cannot persist anything.',
		},
		sync_handle: {
			title: 'OPFS synchronous access handles are not available.',
			detail:
				'novaMOC needs ``FileSystemSyncAccessHandle`` to run SQLite-WASM over OPFS. ' +
				'Your browser exposes OPFS but not the synchronous variant required by the ' +
				'SQLite VFS.',
		},
		cross_origin_isolation: {
			title: 'This page is not cross-origin isolated.',
			detail:
				'novaMOC needs SharedArrayBuffer, which browsers gate on cross-origin isolation. ' +
				'The page must be served with ``Cross-Origin-Opener-Policy: same-origin`` and ' +
				'``Cross-Origin-Embedder-Policy: require-corp`` headers.',
		},
	}

	function isMissingFeature(value: string | null): value is MissingFeature {
		return value === 'opfs' || value === 'sync_handle' || value === 'cross_origin_isolation'
	}

	const param = page.url.searchParams.get('missing')
	const missing: MissingFeature = isMissingFeature(param) ? param : 'opfs'
	const reason = $derived(REASONS[missing])
</script>

<svelte:head>
	<title>Unsupported browser — novaMOC</title>
</svelte:head>

<main class="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6 py-12">
	<h1 class="text-2xl font-semibold">novaMOC cannot run in this browser.</h1>

	<section
		role="alert"
		class="flex flex-col gap-2 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900"
	>
		<p class="font-semibold" data-testid="missing-precondition">{reason.title}</p>
		<p>{reason.detail}</p>
	</section>

	<section class="flex flex-col gap-2 text-sm">
		<h2 class="text-base font-semibold">Supported browsers</h2>
		<ul class="ml-5 list-disc">
			<li>Chrome / Edge 109 or later (January 2023).</li>
			<li>Safari 17 or later (September 2023) on macOS and iOS.</li>
			<li>Firefox is best-effort; we retest on each SQLite-WASM release.</li>
		</ul>
		<p class="text-gray-700">
			Please reopen novaMOC in one of the supported browsers. Until then the app cannot load
			your data.
		</p>
	</section>
</main>
