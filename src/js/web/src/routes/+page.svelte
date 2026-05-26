<script lang="ts">
	import SchemaBrowser from '$lib/SchemaBrowser.svelte'
</script>

<main class="flex h-screen flex-col">
	<header class="flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-3">
		<div>
			<h1 class="text-lg font-semibold">novaMOC</h1>
			<p class="text-xs text-gray-600">Schema management</p>
		</div>
	</header>
	<div class="flex-1 overflow-hidden">
		<SchemaBrowser />
	</div>
</main>
