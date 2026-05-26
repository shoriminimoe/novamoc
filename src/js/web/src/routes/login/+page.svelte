<script lang="ts">
	import { goto } from '$app/navigation'

	let username = $state('')
	let password = $state('')
	let submitting = $state(false)
	let errorTitle = $state<string | null>(null)
	let errorDetail = $state<string | null>(null)

	async function handleSubmit(event: SubmitEvent) {
		event.preventDefault()
		if (submitting) return
		submitting = true
		errorTitle = null
		errorDetail = null

		try {
			const response = await fetch('/auth/login', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ username, password }),
			})

			if (response.status === 204) {
				await goto('/')
				return
			}

			// 4xx / problem+json path. Fall back gracefully if the body
			// is not JSON or `title` / `detail` are not strings.
			let body: unknown = null
			try {
				body = await response.json()
			} catch {
				body = null
			}

			const record = (body && typeof body === 'object' ? (body as Record<string, unknown>) : null)
			const title = record && typeof record.title === 'string' ? record.title : null
			const detail = record && typeof record.detail === 'string' ? record.detail : null

			errorTitle = title ?? `HTTP ${response.status}`
			errorDetail = detail ?? response.statusText
		} catch {
			errorTitle = 'Network error'
			errorDetail = 'Could not reach the server. Please try again.'
		} finally {
			submitting = false
		}
	}
</script>

<div class="flex h-screen items-center justify-center px-4">
	<form
		class="flex w-full max-w-sm flex-col gap-4 rounded border border-gray-200 p-6"
		onsubmit={handleSubmit}
	>
		<h1 class="text-lg font-semibold">Sign in</h1>

		<label class="flex flex-col gap-1 text-sm">
			<span>Username</span>
			<input
				type="text"
				name="username"
				autocomplete="username"
				required
				bind:value={username}
				class="rounded border border-gray-300 px-3 py-2 focus:border-gray-500 focus:outline-none"
			/>
		</label>

		<label class="flex flex-col gap-1 text-sm">
			<span>Password</span>
			<input
				type="password"
				name="password"
				autocomplete="current-password"
				required
				bind:value={password}
				class="rounded border border-gray-300 px-3 py-2 focus:border-gray-500 focus:outline-none"
			/>
		</label>

		{#if errorTitle !== null}
			<div role="alert" class="text-sm text-red-700">
				<p class="font-semibold">{errorTitle}</p>
				{#if errorDetail !== null}
					<p>{errorDetail}</p>
				{/if}
			</div>
		{/if}

		<button
			type="submit"
			disabled={submitting}
			class="rounded border border-gray-300 px-3 py-2 text-sm font-medium disabled:opacity-60"
		>
			{submitting ? 'Signing in…' : 'Sign in'}
		</button>
	</form>
</div>
