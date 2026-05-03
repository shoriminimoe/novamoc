# ADR-005: Model User-Defined Schemas as Data with JSON Projections for Reads

## Status

Accepted

## Context

Users define the shape of assets and maintenance records at runtime. A user modeling a vehicle fleet defines fields such as VIN, year, and mileage; a user tracking aircraft defines tail number, airframe hours, and last annual inspection date. All assets of a given type share the same fields (homogeneous within a type), but the set of types and their fields is not known at build time.

There are two well-known approaches to storing records whose schema is user-defined:

**Entity-Attribute-Value (EAV).** Each field of each entity is stored as its own row in a `values` table with columns `entity_id`, `attribute_id`, `value`. Adding a field at runtime is free. Queries become self-joins: "vehicles made before 2015 with mileage over 100k" requires one join per field referenced. Type safety is lost (the `value` column is either text or dispatched across parallel typed columns). Composite indexes across fields are impossible. Row counts explode. Aggregates get ugly.

**JSON column with generated columns and indexes.** Each entity is one row. User-defined fields are stored in a single `properties` JSON column. SQLite's JSON1 functions allow querying into the JSON with `json_extract`. Generated columns over specific JSON paths give near-native indexed access to hot fields.

The JSON-column approach preserves one-row-per-entity, retains normal SQL for fixed columns, and allows indexed query access to any field the application declares important — while still permitting ad-hoc queries against less-common fields via `json_extract`.

This ADR governs the **read projection** for entities. The **event grain** used by the sync layer is different by design and is addressed in ADR-012. The two representations coexist deliberately: event grain for per-field LWW and replication, JSON projection for natural reads.

## Decision

We model user-defined schemas as data in a meta-schema, and we store the read projection of entities as one row per entity with a JSON `properties` column holding user-defined field values.

The meta-schema consists of fixed tables known at build time: `asset_types`, `asset_type_fields`, `maintenance_record_types`, `maintenance_record_type_fields`. Rows in these tables describe the user-defined schema: which types exist, which fields they have, each field's data type and validation rules. The meta-schema tables are server-authoritative current state and carry an `active` lifecycle column (ADR-008); the schema change log records mutation history but does not produce the projection. Mutations are applied to the meta-schema tables in the same transaction that appends the corresponding row to the change log.

Entity tables (`assets`, `maintenance_records`) have fixed columns (id, tenant_id, type_id, name, timestamps, etc.) plus a `properties` JSON column holding the values of user-defined fields. Applications read user-defined values via `json_extract(properties, '$.field_name')`.

Where query performance on a specific user-defined field matters, we create a generated column extracting that field from the JSON and index it. The set of indexed fields is a deployment concern, not part of the user-visible schema.

The `properties` JSON column is a projection maintained from the event log (ADR-002, ADR-011). ADR-012 specifies that every event at field grain also updates the corresponding entity's `properties` JSON in the same transaction, keeping the projection consistent with the event log.

## Consequences

Adding a user-defined field is data, not DDL. Users add fields at runtime without schema migrations on either client or server (see ADR-008 for how schema changes propagate).

Queries over user-defined fields read naturally. "Assets of type X with mileage over N" is a single SELECT with one `json_extract` in the WHERE clause, optionally backed by a generated-column index.

We avoid EAV's query complexity, type safety loss, and row-count explosion for read purposes. We retain one row per entity, which matches how humans think about the data and how reports need to aggregate it.

The cost is that validation of user-defined field values cannot be enforced with SQL column constraints; it happens at the application layer against the meta-schema definition. We accept this. The meta-schema is the source of truth for field types and validation, and both client and server enforce it at event generation and acceptance time.

This ADR deliberately separates read projection from event grain. The sync layer operates at per-field event grain (ADR-012) for per-field LWW resolution (ADR-007); reads operate at per-entity grain with JSON properties. The two are kept consistent by the write path (ADR-012).
