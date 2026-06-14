/**
 * Client side of the shared LWW-fold parity harness (ADR-007 / ADR-012).
 *
 * Loads every JSON scenario from the repo-root `tests/fold-parity/`
 * directory (the single source of truth, also driven by the pytest twin
 * `test_fold_parity.py`), runs the client fold (`fold.ts`) from an empty
 * projection, and asserts the result equals the scenario's
 * `expected_projection`. A fold that diverges from the server fails here or
 * in the pytest suite — that's the whole point of sharing the scenarios.
 *
 * The comparison is over the structural entity-row columns plus the full
 * field-value tables, matching the pytest runner: derived `name` /
 * `properties` JSON is reconstructed from field-value rows at read time
 * (ADR-015) and is not part of the fold's parity contract.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { emptyProjection, fold } from '../../src/lib/db/fold'
import { gateEvent } from '../../src/lib/sync/schema'
import type { EventEnvelope, Projection } from '../../src/lib/db/types'

/**
 * An event in a gating scenario: a fold envelope plus the schema version it
 * carries and its replication `seq` (release order). Mirrors the server
 * runner's `_GatedEvent`.
 */
interface GatedEvent extends EventEnvelope {
  seq: number
  schema_version: number
}

interface GatingPhase {
  active_schema_version: number
  events: GatedEvent[]
}

interface Gating {
  phases: GatingPhase[]
}

interface Scenario {
  name: string
  events?: EventEnvelope[]
  gating?: Gating
  expected_projection: ExpectedProjection
}

interface ExpectedEntityRow {
  id: string
  type_id: string
  asset_id?: string
  deleted: boolean
  row_state_hlc: string
}

interface ExpectedFieldRow {
  entity_id: string
  field_id: string
  value_json: unknown
  hlc: string
}

interface ExpectedProjection {
  assets: ExpectedEntityRow[]
  asset_field_values: ExpectedFieldRow[]
  maintenance_records: ExpectedEntityRow[]
  maintenance_record_field_values: ExpectedFieldRow[]
}

// E1.3 (HLC) ships its own self-contained parity runner; skip its scenario
// here so the two harnesses stay independent.
const NOT_OURS = new Set(['hlc_basic.json'])

// Vitest runs with cwd at the package root (`src/js/web`); the shared
// scenario directory is at the repo root, three levels up. Resolving from
// cwd dodges the Vite transform that rewrites `import.meta.url`.
const SCENARIO_DIR = join(process.cwd(), '../../../tests/fold-parity')

function loadScenarios(): { file: string; scenario: Scenario }[] {
  return readdirSync(SCENARIO_DIR)
    .filter((f) => f.endsWith('.json') && !NOT_OURS.has(f))
    .sort()
    .map((file) => ({
      file,
      scenario: JSON.parse(
        readFileSync(join(SCENARIO_DIR, file), 'utf-8'),
      ) as Scenario,
    }))
}

/**
 * Replay a gating scenario through the ADR-009 gate and return the events in
 * the order they become applicable. Within a phase: the active version rises
 * (monotonic), arriving events that gate to `'apply'` fold immediately while
 * `'buffer'` ones are parked, then every parked event the new version
 * unblocks is released in `seq` order. Symmetric with the pytest runner so
 * the same JSON folds identically in both languages.
 */
function gatedEventOrder(gating: Gating): EventEnvelope[] {
  const applied: EventEnvelope[] = []
  const buffer: GatedEvent[] = []
  let active = 0
  for (const phase of gating.phases) {
    active = Math.max(active, phase.active_schema_version)
    for (const event of phase.events) {
      if (gateEvent(event, active) === 'apply') {
        applied.push(event)
      } else {
        buffer.push(event)
      }
    }
    const released = buffer
      .filter((e) => gateEvent(e, active) === 'apply')
      .sort((a, b) => a.seq - b.seq)
    for (const event of released) {
      applied.push(event)
      buffer.splice(buffer.indexOf(event), 1)
    }
  }
  return applied
}

function scenarioEvents(scenario: Scenario): EventEnvelope[] {
  if (scenario.gating) {
    return gatedEventOrder(scenario.gating)
  }
  return scenario.events ?? []
}

function entityRows(
  entities: Projection['assets'],
  withParent: boolean,
): ExpectedEntityRow[] {
  return [...entities.values()]
    .map((row) => {
      const entry: ExpectedEntityRow = {
        id: row.id,
        type_id: row.type_id,
        deleted: row.deleted,
        row_state_hlc: row.row_state_hlc,
      }
      // Asserting `asset_id` only for maintenance records keeps the actual
      // shape aligned with the JSON, which omits it on assets.
      if (withParent) {
        entry.asset_id = row.asset_id
      }
      return entry
    })
    .sort((a, b) => a.id.localeCompare(b.id))
}

function fieldRows(values: Projection['asset_field_values']): ExpectedFieldRow[] {
  return [...values.values()]
    .map((row) => ({
      entity_id: row.entity_id,
      field_id: row.field_id,
      value_json: row.value_json,
      hlc: row.hlc,
    }))
    .sort((a, b) =>
      a.entity_id === b.entity_id
        ? a.field_id.localeCompare(b.field_id)
        : a.entity_id.localeCompare(b.entity_id),
    )
}

function actualProjection(projection: Projection): ExpectedProjection {
  return {
    assets: entityRows(projection.assets, false),
    asset_field_values: fieldRows(projection.asset_field_values),
    maintenance_records: entityRows(projection.maintenance_records, true),
    maintenance_record_field_values: fieldRows(
      projection.maintenance_record_field_values,
    ),
  }
}

function sortExpected(expected: ExpectedProjection): ExpectedProjection {
  const byId = (a: ExpectedEntityRow, b: ExpectedEntityRow) =>
    a.id.localeCompare(b.id)
  const byKey = (a: ExpectedFieldRow, b: ExpectedFieldRow) =>
    a.entity_id === b.entity_id
      ? a.field_id.localeCompare(b.field_id)
      : a.entity_id.localeCompare(b.entity_id)
  return {
    assets: [...expected.assets].sort(byId),
    asset_field_values: [...expected.asset_field_values].sort(byKey),
    maintenance_records: [...expected.maintenance_records].sort(byId),
    maintenance_record_field_values: [
      ...expected.maintenance_record_field_values,
    ].sort(byKey),
  }
}

describe('LWW fold parity (shared scenarios)', () => {
  const scenarios = loadScenarios()

  it('discovers at least the v1 scenario set', () => {
    expect(scenarios.length).toBeGreaterThanOrEqual(6)
  })

  for (const { file, scenario } of scenarios) {
    it(`matches expected projection: ${scenario.name} (${file})`, () => {
      const result = fold(emptyProjection(), scenarioEvents(scenario))
      expect(actualProjection(result)).toEqual(
        sortExpected(scenario.expected_projection),
      )
    })
  }
})
