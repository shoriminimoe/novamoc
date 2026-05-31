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
import type { EventEnvelope, Projection } from '../../src/lib/db/types'

interface Scenario {
  name: string
  events: EventEnvelope[]
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
      const result = fold(emptyProjection(), scenario.events)
      expect(actualProjection(result)).toEqual(
        sortExpected(scenario.expected_projection),
      )
    })
  }
})
