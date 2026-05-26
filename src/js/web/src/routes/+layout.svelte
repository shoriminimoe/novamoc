<script lang="ts">
	import '../app.css'
	import { onMount, setContext, type Snippet } from 'svelte'
	import { goto } from '$app/navigation'
	import { page } from '$app/state'

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
