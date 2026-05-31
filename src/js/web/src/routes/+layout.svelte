<script lang="ts">
	import '../app.css'
	import { onMount, setContext, type Snippet } from 'svelte'
	import { goto } from '$app/navigation'
	import { page } from '$app/state'
	import { probeOpfs } from '$lib/db/probe'

	type Principal = {
		user: { id: string; username: string }
		tenant: { id: string; display_name: string }
	}

	type Props = {
		children: Snippet
	}

	const { children }: Props = $props()

	let principal = $state<Principal | null>(null)
	let probeComplete = $state(false)

	setContext('novamoc:principal', {
		get current(): Principal | null {
			return principal
		},
	})

	onMount(() => {
		void (async () => {
			try {
				// OPFS feature probe (ADR-003) runs before anything else —
				// if the browser can't run SQLite-WASM-over-OPFS we route
				// to the blocking error page and never touch auth or data.
				// On the ``/unsupported`` route itself we skip both the
				// probe and the auth fetch — the user is already blocked
				// from doing anything, and re-running the probe would
				// either redirect-loop or hide the error page on a
				// transient pass.
				if (page.url.pathname === '/unsupported') {
					return
				}

				const probe = await probeOpfs()
				if (!probe.ok) {
					await goto(`/unsupported?missing=${probe.missing}`, { replaceState: true })
					return
				}

				const response = await fetch('/auth/me', { credentials: 'include' })
				if (response.status === 200) {
					principal = (await response.json()) as Principal
					if (page.url.pathname === '/login') {
						await goto('/')
					}
				} else if (response.status === 401) {
					if (page.url.pathname !== '/login') {
						await goto('/login')
					}
				}
			} catch {
				// Network error or non-JSON body — settle into "probe complete"
				// without redirecting. v1 keeps the page blank in that case.
			} finally {
				probeComplete = true
			}
		})()
	})
</script>

{#if probeComplete}
	{@render children()}
{/if}
