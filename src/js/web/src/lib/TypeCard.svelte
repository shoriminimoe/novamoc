<script lang="ts">
  import type { Snippet } from 'svelte'
  import type { FieldView, TypeView } from './schema'

  interface Props {
    type: TypeView
    showTombstoned: boolean
    /**
     * Optional per-field actions row, rendered under each field's
     * display row. Lets the asset-types column inject field lifecycle
     * controls without modifying the type-level display.
     */
    fieldActions?: Snippet<[FieldView]>
  }

  let { type, showTombstoned, fieldActions }: Props = $props()

  let visibleFields = $derived(
    showTombstoned ? type.fields : type.fields.filter((f) => f.active),
  )
</script>

<article
  class="rounded border border-gray-200 p-4"
  class:opacity-60={!type.active}
>
  <header class="mb-3 flex items-baseline justify-between gap-2">
    <h3 class="font-mono text-base font-semibold">{type.name}</h3>
    {#if !type.active}
      <span
        class="rounded bg-gray-200 px-2 py-0.5 text-xs uppercase tracking-wide text-gray-700"
      >
        tombstoned
      </span>
    {/if}
  </header>

  {#if visibleFields.length === 0}
    <p class="text-sm italic text-gray-500">
      {#if type.fields.length === 0}
        no fields
      {:else}
        no active fields
      {/if}
    </p>
  {:else}
    <ul class="divide-y divide-gray-100">
      {#each visibleFields as field (field.id)}
        <li class="py-1.5" class:opacity-60={!field.active}>
          <div class="flex items-center justify-between text-sm">
            <span class="font-mono">{field.name}</span>
            <span class="flex items-center gap-2">
              <span class="text-xs uppercase tracking-wide text-gray-500">
                {field.data_type}
              </span>
              {#if !field.active}
                <span
                  class="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gray-700"
                >
                  tombstoned
                </span>
              {/if}
            </span>
          </div>
          {#if fieldActions}
            {@render fieldActions(field)}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</article>
