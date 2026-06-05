/**
 * Real-browser integration for snapshot ingest (E1.7, ADR-013 / ADR-015).
 *
 * Seeds a non-trivial tenant through the *real* API (login for the session
 * cookie, then POST /schema + POST /events), runs the production
 * `ingestSnapshot` in the page against the OPFS-backed local DB, and asserts
 * the four local projection tables hold exactly the rows the server would
 * return via `GET /snapshot`. The server tenant is resolved from the session
 * cookie; the local DB is keyed by an arbitrary stable id (it only scopes the
 * local file and the local FKs), so the parity comparison is over the wire
 * row content, not `tenant_id`.
 *
 * This is the only place the full HTTP+OPFS path runs end to end: vitest mocks
 * the HTTP boundary and uses an in-memory DB, so neither the real session
 * cookie nor the worker-backed DB are exercised there.
 */

import { expect, test } from '@playwright/test'

const TRUCK = 'aaaaaaaa-0000-4000-8000-000000000001'
const VIN = 'aaaaaaaa-0000-4000-8000-000000000002'
const OIL = 'aaaaaaaa-0000-4000-8000-000000000003'
const NOTES = 'aaaaaaaa-0000-4000-8000-000000000004'
const ASSET_1 = 'aaaaaaaa-0000-4000-8000-000000000011'
const ASSET_2 = 'aaaaaaaa-0000-4000-8000-000000000012'
const MR_1 = 'aaaaaaaa-0000-4000-8000-000000000021'

// A unique local-DB key per run so a re-run doesn't collide with a prior OPFS
// file. The server tenant comes from the session, not from this value.
const LOCAL_TENANT = `e2e-snapshot-${Date.now()}`

test('snapshot ingest hydrates the local projection to match the server', async ({
  page,
}) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(await page.evaluate(() => globalThis.crossOriginIsolated)).toBe(true)

  const parity = await page.evaluate(
    async ({ ids, localTenant, modules }) => {
      const headers = { 'Content-Type': 'application/json' }
      const fetchJson = async (path: string) => {
        const r = await fetch(path, { credentials: 'include' })
        if (!r.ok) throw new Error(`GET ${path} -> ${r.status}: ${await r.text()}`)
        return r.json()
      }
      const post = async (path: string, body: unknown) => {
        const r = await fetch(path, {
          method: 'POST',
          credentials: 'include',
          headers,
          body: JSON.stringify(body),
        })
        if (!r.ok && r.status !== 201)
          throw new Error(`POST ${path} -> ${r.status}: ${await r.text()}`)
        return r.status === 204 ? null : r.json()
      }

      // -- Authenticate for the session cookie.
      const login = await fetch('/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers,
        body: JSON.stringify({ username: 'admin', password: 'admin' }),
      })
      if (login.status !== 204)
        throw new Error(`login -> ${login.status}: ${await login.text()}`)

      // -- Seed schema: two asset/MR types each with one field.
      await post('/schema', {
        type: 'create_asset_type',
        entity_id: ids.TRUCK,
        payload: { name: `Truck-${ids.TRUCK}` },
      })
      await post('/schema', {
        type: 'create_asset_type_field',
        entity_id: ids.VIN,
        payload: { parent_id: ids.TRUCK, name: 'vin', data_type: 'text' },
      })
      await post('/schema', {
        type: 'create_maintenance_record_type',
        entity_id: ids.OIL,
        payload: { name: `Oil-${ids.OIL}` },
      })
      await post('/schema', {
        type: 'create_maintenance_record_type_field',
        entity_id: ids.NOTES,
        payload: { parent_id: ids.OIL, name: 'notes', data_type: 'text' },
      })

      const schema = (await fetchJson('/schema')) as { schema_version: number }
      const schemaVersion = schema.schema_version

      // -- Seed data: two assets (one tombstoned) + one maintenance record.
      const events = [
        {
          hlc: '0000000000000001-00000-e2e',
          family: 'asset',
          type_id: ids.TRUCK,
          instance_id: ids.ASSET_1,
          body: {
            event: 'created',
            values: { 'col:name': 'Primary', [ids.VIN]: '1HGCM82633A004352' },
          },
        },
        {
          hlc: '0000000000000002-00000-e2e',
          family: 'asset',
          type_id: ids.TRUCK,
          instance_id: ids.ASSET_2,
          body: { event: 'created', values: { 'col:name': 'Spare' } },
        },
        {
          hlc: '0000000000000003-00000-e2e',
          family: 'asset',
          type_id: ids.TRUCK,
          instance_id: ids.ASSET_2,
          body: { event: 'deactivated' },
        },
        {
          hlc: '0000000000000004-00000-e2e',
          family: 'maintenance_record',
          type_id: ids.OIL,
          instance_id: ids.MR_1,
          body: {
            event: 'created',
            parent: { type_id: ids.TRUCK, instance_id: ids.ASSET_1 },
            values: { [ids.NOTES]: 'Changed oil' },
          },
        },
      ]
      const eventResp = (await post('/events', {
        schema_version: schemaVersion,
        events,
      })) as { outcomes: { outcome: string }[] }
      for (const o of eventResp.outcomes) {
        if (o.outcome !== 'accepted')
          throw new Error(`event not accepted: ${o.outcome}`)
      }

      // -- Assemble the server truth: walk GET /snapshot to completion.
      type Batch = {
        page: string | null
        cursor: number | null
        body: { table: string; items: Record<string, unknown>[] }
      }
      const server: Record<string, Record<string, unknown>[]> = {
        assets: [],
        asset_field_values: [],
        maintenance_records: [],
        maintenance_record_field_values: [],
      }
      let pageToken: string | null = null
      let serverCursor = 0
      for (;;) {
        const path =
          pageToken === null
            ? '/snapshot'
            : `/snapshot?page=${encodeURIComponent(pageToken)}`
        const batch = (await fetchJson(path)) as Batch
        for (const item of batch.body.items) server[batch.body.table].push(item)
        if (batch.page === null) {
          serverCursor = batch.cursor ?? -1
          break
        }
        pageToken = batch.page
      }

      // -- Ingest into the real OPFS-backed local DB. Schema first (FKs), then
      //    the bulk snapshot — the production modules, no test doubles.
      // The modules load through Vite's dev server in the page context; the
      // specifiers are passed in as runtime strings (not import literals) so
      // tsc doesn't try to resolve them, and each cast pins the shape.
      type LocalDb = { exec: (sql: string) => Promise<unknown[][]> }
      type Client = unknown
      const { openLocalDb } = (await import(
        /* @vite-ignore */ modules.bootstrap
      )) as { openLocalDb: (tenantId: string) => Promise<LocalDb> }
      const { refreshSchema } = (await import(
        /* @vite-ignore */ modules.schema
      )) as {
        refreshSchema: (o: {
          store: LocalDb
          tenantId: string
          client: Client
        }) => Promise<unknown>
      }
      const { ingestSnapshot } = (await import(
        /* @vite-ignore */ modules.snapshot
      )) as {
        ingestSnapshot: (o: {
          store: LocalDb
          tenantId: string
          client: Client
        }) => Promise<{ cursor: number; schema_version: number }>
      }
      const { createApiClient } = (await import(
        /* @vite-ignore */ modules.api
      )) as { createApiClient: () => Client }

      const db = await openLocalDb(localTenant)
      const client = createApiClient()
      await refreshSchema({ store: db, tenantId: localTenant, client })
      const result = await ingestSnapshot({
        store: db,
        tenantId: localTenant,
        client,
      })

      // -- Read back the four local tables (without tenant_id; the wire omits
      //    it) and shape them like the server rows for comparison.
      const localAssets = (
        await db.exec(
          'SELECT id, type_id, deleted, row_state_hlc FROM assets ORDER BY id',
        )
      ).map((r) => ({
        id: r[0],
        type_id: r[1],
        deleted: r[2] === 1,
        row_state_hlc: r[3],
      }))
      const localAfv = (
        await db.exec(
          'SELECT asset_id, field_id, value_json, hlc FROM asset_field_values ORDER BY asset_id, field_id',
        )
      ).map((r) => ({
        asset_id: r[0],
        field_id: r[1],
        value_json: JSON.parse(r[2] as string),
        hlc: r[3],
      }))
      const localMr = (
        await db.exec(
          'SELECT id, type_id, asset_id, deleted, row_state_hlc FROM maintenance_records ORDER BY id',
        )
      ).map((r) => ({
        id: r[0],
        type_id: r[1],
        asset_id: r[2],
        deleted: r[3] === 1,
        row_state_hlc: r[4],
      }))
      const localMrfv = (
        await db.exec(
          'SELECT maintenance_record_id, field_id, value_json, hlc FROM maintenance_record_field_values ORDER BY maintenance_record_id, field_id',
        )
      ).map((r) => ({
        maintenance_record_id: r[0],
        field_id: r[1],
        value_json: JSON.parse(r[2] as string),
        hlc: r[3],
      }))

      const pick = (
        rows: Record<string, unknown>[],
        keys: string[],
      ): Record<string, unknown>[] =>
        rows.map((row) => Object.fromEntries(keys.map((k) => [k, row[k]])))

      return {
        cursor: result.cursor,
        serverCursor,
        schemaVersion: result.schema_version,
        local: { localAssets, localAfv, localMr, localMrfv },
        server: {
          assets: pick(server.assets, ['id', 'type_id', 'deleted', 'row_state_hlc']),
          afv: pick(server.asset_field_values, [
            'asset_id',
            'field_id',
            'value_json',
            'hlc',
          ]),
          mr: pick(server.maintenance_records, [
            'id',
            'type_id',
            'asset_id',
            'deleted',
            'row_state_hlc',
          ]),
          mrfv: pick(server.maintenance_record_field_values, [
            'maintenance_record_id',
            'field_id',
            'value_json',
            'hlc',
          ]),
        },
      }
    },
    {
      ids: { TRUCK, VIN, OIL, NOTES, ASSET_1, ASSET_2, MR_1 },
      localTenant: LOCAL_TENANT,
      modules: {
        bootstrap: '/src/lib/db/bootstrap.ts',
        schema: '/src/lib/sync/schema.ts',
        snapshot: '/src/lib/sync/snapshot.ts',
        api: '/src/lib/api.ts',
      },
    },
  )

  // The terminal cursor the ingest persisted equals the server's.
  expect(parity.cursor).toBe(parity.serverCursor)
  expect(parity.schemaVersion).toBeGreaterThanOrEqual(4)

  // The four local tables match the server's snapshot rows exactly.
  const sortById = <T extends { [k: string]: unknown }>(rows: T[], key: string) =>
    [...rows].sort((a, b) => String(a[key]).localeCompare(String(b[key])))

  expect(sortById(parity.local.localAssets, 'id')).toEqual(
    sortById(parity.server.assets, 'id'),
  )
  expect(parity.local.localAfv).toEqual(
    [...parity.server.afv].sort((a, b) =>
      `${a.asset_id}${a.field_id}`.localeCompare(`${b.asset_id}${b.field_id}`),
    ),
  )
  expect(sortById(parity.local.localMr, 'id')).toEqual(
    sortById(parity.server.mr, 'id'),
  )
  expect(parity.local.localMrfv).toEqual(
    [...parity.server.mrfv].sort((a, b) =>
      `${a.maintenance_record_id}${a.field_id}`.localeCompare(
        `${b.maintenance_record_id}${b.field_id}`,
      ),
    ),
  )

  // The non-trivial tenant actually populated all four tables.
  expect(parity.local.localAssets.length).toBe(2)
  expect(parity.local.localMr.length).toBe(1)
  expect(parity.local.localAfv.length).toBeGreaterThanOrEqual(2)
  expect(parity.local.localMrfv.length).toBe(1)
})
