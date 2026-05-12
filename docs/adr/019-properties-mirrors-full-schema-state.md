---
status: accepted
date: 2026-05-12
category: storage
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-019: `properties` Mirrors the Full Schema State of an Entity

## Context and Problem Statement

ADR-012 specified the entity-table projection for user fields. Its
"Clears" clause read: *"A `set` event with `value_json = NULL`, or a
field-grain `delete`, removes the corresponding key from `properties`
for user fields…"* That choice — `json_remove` on clears — was
convenient for the projection write but conflates two distinct read-
side observations: *"this field has never been set"* and *"this field
was set and explicitly cleared."* Both surface as a missing JSON key.

We want `properties` to be a read-time mirror of the entity's full
schema state, so a UI iterating schema fields and reading `properties`
sees every defined field by name, with explicit JSON `null` for
unset / cleared cells. Distinguishing "unset" from "explicit null"
isn't a data we carry — the schema enumerates the entity's fields and
events are authoritative for values — but the projection should not
elide a key that the schema declares.

## Considered Options

* **`json_set(properties, '$.<field>', NULL)` on clears — chosen.**
* **`json_remove(properties, '$.<field>')` on clears (ADR-012's
  original choice).**

## Decision Outcome

Chosen option: **`json_set(..., NULL)` on clears.** A clear event
keeps the JSON key present with value `null`. ADR-012's clears clause
for user fields is superseded; the rest of ADR-012 stands.

`col:` columns are unchanged: a clear sets the typed column to SQL
`NULL`. Only the user-field branch of the projection write changes.

Schema validation (M1.4) already rejects events targeting a field not
present in the entity's schema, so `properties` keys are bounded by
the schema's declared fields. Combined with this ADR, a row's
`properties` after any sequence of accepted events contains exactly
the schema's user-field keys for every field that has been written —
with explicit `null` for cleared cells — and nothing else.

Initial population of all schema fields on entity creation (so a
never-touched field also appears with `null`) is a row-state concern
folded into M1.8 and out of scope for this ADR; today, fields appear
only after their first write.

## Consequences

* `json_extract(properties, '$.<field>')` continues to return SQL
  `NULL` for cleared cells.
* `json_type(properties, '$.<field>')` now returns the string
  `'null'` (key present, JSON null) instead of SQL `NULL` (key
  absent). Code that distinguishes these for cleared-vs-never-set
  must use other signals (e.g. `*_field_values` for whether an event
  has ever applied to that cell).
* `json_each(properties)` enumerates cleared keys alongside
  populated ones.
* Wire format is unchanged: the event log still records
  `value_json = NULL` to denote a clear; only the projection write
  differs.
