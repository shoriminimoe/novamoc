"""Tenant-scoping enforcement listeners (issue #51).

Three layers, registered at import time on SQLAlchemy's global event
system. Importing this module is the entire wiring step — see
asgi.create_app and tests/conftest.py.

Layer 1: do_orm_execute injects a tenant_id WHERE predicate on every
ORM SELECT against a class with a tenant_id column.
Layer 2: before_flush stamps tenant_id on new ORM instances of
tenant-scoped models, and rejects cross-tenant writes.
Layer 3: before_execute is the backstop for Core-level INSERT /
UPDATE / DELETE that bypasses Layers 1-2.
"""

# Each `raise UnscopedQueryError(...)` / `raise CrossTenantWriteError(...)`
# carries diagnostic context (mapped class name, table name, contextvar
# value) that a future engineer needs at the failure site. A class-level
# default message would lose that context, and the ratchet here is one
# greppable file rather than six per-line `# noqa: TRY003` suppressions.
# ruff: noqa: TRY003

from __future__ import annotations

from typing import Any

from sqlalchemy import Delete, Engine, Insert, Select, Update, event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql.elements import BinaryExpression

from novamoc.db._errors import CrossTenantWriteError, UnscopedQueryError
from novamoc.db._tenant_context import SKIP_TENANT_FILTER, current_tenant_id


# Columns named ``tenant_id`` that are FKs to the ``tenants`` registry
# (e.g. ``user_tenant_memberships.tenant_id``) carry
# ``info={"registry_fk": True}`` to opt out of scope enforcement. The
# heuristic still keys off column presence; the marker is the documented
# escape hatch when "this column points at the tenant registry" rather
# than "this row belongs to one tenant" is the right reading.
def _is_tenant_scoped(table) -> bool:
    col = table.columns.get("tenant_id")
    return col is not None and not col.info.get("registry_fk", False)


def _instance_is_tenant_scoped(obj: object) -> bool:
    table = getattr(obj, "__table__", None)
    return table is not None and _is_tenant_scoped(table)


@event.listens_for(Session, "before_flush")
def _stamp_or_reject_tenant(session, flush_context, instances) -> None:
    tid = current_tenant_id.get()
    for obj in session.new:
        if not _instance_is_tenant_scoped(obj):
            continue
        if obj.tenant_id is None:
            if tid is None:
                raise UnscopedQueryError(
                    f"Tenant-scoped INSERT attempted without tenant context: "
                    f"{type(obj).__name__}"
                )
            obj.tenant_id = tid
        elif tid is not None and obj.tenant_id != tid:
            raise CrossTenantWriteError(
                f"INSERT into {type(obj).__name__} for tenant {obj.tenant_id} "
                f"under context {tid}"
            )


# ---------------------------------------------------------------------------
# Layer 1: do_orm_execute — inject tenant_id predicate on every ORM SELECT
# ---------------------------------------------------------------------------


@event.listens_for(Session, "do_orm_execute")
def _inject_tenant_filter(state) -> None:
    if not state.is_select:
        return
    if state.execution_options.get(SKIP_TENANT_FILTER):
        return

    # Collect the set of concrete mapped classes that have a tenant_id column
    # and are involved in this statement.  One with_loader_criteria option is
    # added per such class using a pre-built column expression (not a lambda),
    # which avoids SQLAlchemy's lambda-caching system so the tenant_id value
    # is always fresh from the contextvar.
    tenant_scoped: list[Any] = [
        mapper.class_
        for mapper in state.all_mappers
        if hasattr(mapper.class_, "__table__")
        and _is_tenant_scoped(mapper.class_.__table__)
    ]

    if tenant_scoped:
        tid = current_tenant_id.get()
        if tid is None:
            # Use the first matching class name in the error message.
            cls_name = tenant_scoped[0].__name__
            raise UnscopedQueryError(
                f"Tenant-scoped SELECT against {cls_name} "
                "attempted without tenant context"
            )

        options = [
            with_loader_criteria(
                cls,
                cls.tenant_id == tid,
                include_aliases=True,
            )
            for cls in tenant_scoped
        ]
        state.statement = state.statement.options(*options)
        return

    # When all_mappers is empty the ORM mapper wasn't able to resolve mapped
    # classes — this happens for aggregate transforms (e.g. count()) that
    # advanced-alchemy emits via ``with_only_columns(func.count(1),
    # maintain_column_froms=True)``.  The FROM clause still references the
    # underlying tenant-scoped table, so we inject a WHERE predicate directly
    # on the statement for each tenant-scoped table in the FROM list.
    if not isinstance(state.statement, Select):
        return

    scoped_tables = [
        t for t in state.statement.get_final_froms() if _is_tenant_scoped(t)
    ]
    if not scoped_tables:
        return

    tid = current_tenant_id.get()
    if tid is None:
        raise UnscopedQueryError(
            f"Tenant-scoped SELECT against {scoped_tables[0].name} "
            "attempted without tenant context"
        )

    stmt = state.statement
    for table in scoped_tables:
        stmt = stmt.where(table.c.tenant_id == tid)
    state.statement = stmt


# ---------------------------------------------------------------------------
# Layer 3: before_execute — backstop for Core-level INSERT / UPDATE / DELETE
# ---------------------------------------------------------------------------
#
# Layer 1 covers ORM SELECTs and Layer 2 covers ORM flushes of mapped
# instances. Layer 3 fires on every statement reaching the engine and
# rejects DML against tenant-scoped tables that would either INSERT
# without a tenant_id or UPDATE / DELETE without filtering on one. The
# helpers reach into a few SQLAlchemy 2.x internals (``Insert._values``,
# ``Insert._multi_values``) — these are stable enough for our pinned
# version but are guarded with ``getattr`` fallbacks. The execution
# option ``SKIP_TENANT_FILTER`` bypasses the layer for deliberate
# cross-tenant administrative DML.


def _is_tenant_key(key: Any) -> bool:
    """Return True if a dict key (string column name or Column) names ``tenant_id``.

    SQLAlchemy 2.x normalises ``.values(tenant_id=...)`` into a dict keyed
    by the column name string; older shapes use the Column object directly.
    We accept both.
    """
    if isinstance(key, str):
        return key == "tenant_id"
    return getattr(key, "name", None) == "tenant_id"


def _values_carries_tenant(insert_stmt: Insert, multiparams: Any, params: Any) -> bool:
    """Return True if the INSERT names tenant_id in its values or params.

    Covers the four shapes SQLAlchemy emits in practice:
      * ``insert(t).values(tenant_id=...)``  -> ``_values`` dict whose keys
        are column names (strings) under SQLAlchemy 2.x.
      * ``insert(t).values([{...}, {...}])`` -> ``_multi_values`` tuple of
        list of column->value dicts.
      * ``session.execute(insert(t), {...})`` -> single dict in ``params``.
      * ``session.execute(insert(t), [{...}, {...}])`` -> list of dicts in
        ``multiparams``. ORM-emitted INSERTs land here too (the params
        dict carries ``tenant_id`` directly).
    """
    explicit = getattr(insert_stmt, "_values", None)
    if explicit and any(_is_tenant_key(key) for key in explicit):
        return True

    multi_values = getattr(insert_stmt, "_multi_values", ()) or ()
    for row in multi_values:
        for entry in row:
            if isinstance(entry, dict) and any(
                getattr(col, "name", col) == "tenant_id" for col in entry
            ):
                return True

    if isinstance(params, dict) and "tenant_id" in params:
        return True
    # multiparams is the executemany path: SQLAlchemy 2.x always passes a
    # list/tuple here (single-row executes use `params` instead), but the
    # check is cheap and would survive a future API change.
    if isinstance(multiparams, (list, tuple)):
        for entry in multiparams:
            if isinstance(entry, dict) and "tenant_id" in entry:
                return True

    return False


def _walk_for_tenant(elem: Any) -> bool:
    """Walk a WHERE expression tree looking for a column named tenant_id
    on a tenant-scoped table or alias.
    """
    if isinstance(elem, BinaryExpression):
        for side in (elem.left, elem.right):
            name = getattr(side, "name", None)
            table = getattr(side, "table", None)
            if name == "tenant_id" and table is not None and _is_tenant_scoped(table):
                return True
    children = getattr(elem, "get_children", None)
    if children is not None:
        for child in children():
            if _walk_for_tenant(child):
                return True
    return False


def _whereclause_filters_tenant(stmt: Any) -> bool:
    where = getattr(stmt, "whereclause", None)
    if where is None:
        return False
    return _walk_for_tenant(where)


@event.listens_for(Engine, "before_execute")
def _reject_unscoped_dml(
    conn: Any,
    clauseelement: Any,
    multiparams: Any,
    params: Any,
    execution_options: Any,
) -> None:
    if execution_options.get(SKIP_TENANT_FILTER):
        return

    if isinstance(clauseelement, Insert):
        table = getattr(clauseelement, "table", None)
        if table is None or not _is_tenant_scoped(table):
            return
        if not _values_carries_tenant(clauseelement, multiparams, params):
            # S608 false positive: this is an error message, not a SQL fragment.
            msg = f"INSERT into {table.name} has no tenant_id in VALUES or params"  # noqa: S608
            raise UnscopedQueryError(msg)
        return

    if isinstance(clauseelement, (Update, Delete)):
        table = getattr(clauseelement, "table", None)
        if table is None or not _is_tenant_scoped(table):
            return
        if not _whereclause_filters_tenant(clauseelement):
            raise UnscopedQueryError(
                f"{type(clauseelement).__name__} against {table.name} "
                f"has no tenant_id predicate"
            )
