"""Cross-tenant isolation — every service method scopes correctly.

Issue #51 acceptance criterion: seeding equivalent rows under two
tenants and exercising every read/write method must show no leak.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from novamoc.db._errors import CrossTenantWriteError, UnscopedQueryError
from novamoc.db._tenant_context import use_tenant
from novamoc.domain.schema._commands import SchemaCommand
from tests.data.scenarios import ACTIVE_TRUCK

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from novamoc.domain.schema._bundle import ServiceBundle

# The truck JSON fixture has a fixed UUID. The composite PK (tenant_id, id)
# allows the same UUID under both tenants — they are distinct rows. The
# fixed value lets us assert that get_one_or_none(id=...) under tenant=X
# always returns X's row even when both tenants' rows share the same UUID.
_TRUCK_UUID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
async def two_tenant_ids(seed) -> dict[str, UUID]:
    """Seed ACTIVE_TRUCK under t-a and t-b, return their ids.

    Both entries in the returned dict hold the same UUID value (verified
    against ``_TRUCK_UUID``); the tenant_id in the contextvar is what
    scopes each lookup to its own row.
    """
    a = await seed(ACTIVE_TRUCK, tenant_id="t-a")
    b = await seed(ACTIVE_TRUCK, tenant_id="t-b")
    ids = {
        "t-a": a["asset_type"]["Truck"],
        "t-b": b["asset_type"]["Truck"],
    }
    # Guard: the same-UUID property is what makes the cross-tenant tests
    # below non-vacuous. Catch fixture rotations early.
    assert ids["t-a"] == _TRUCK_UUID
    assert ids["t-b"] == _TRUCK_UUID
    return ids


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_list_returns_only_own_rows(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    """list() under a tenant returns only that tenant's rows."""
    with use_tenant(tenant):
        rows = await services.asset_type.list()
    assert {r.tenant_id for r in rows} == {tenant}
    assert len(rows) == 1


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_get_one_or_none_does_not_leak_other_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    """get_one_or_none(id=<uuid>) under a tenant returns that tenant's row.

    Both tenants share the same UUID (the fixture is deterministic).
    Under tenant t-a, the lookup returns the t-a row; under t-b, the
    t-b row. The returned row's tenant_id must match the contextvar —
    confirming Layer 1 filters the composite PK correctly.
    """
    uuid = two_tenant_ids[tenant]
    with use_tenant(tenant):
        row = await services.asset_type.get_one_or_none(id=uuid)
    assert row is not None, f"expected a row for {tenant!r} but got None"
    assert row.tenant_id == tenant


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_count_is_per_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    """count() under a tenant sees only its own rows."""
    with use_tenant(tenant):
        n = await services.asset_type.count()
    assert n == 1


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_update_does_not_touch_other_tenant(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID], tenant: str
) -> None:
    """update() targeting tenant's composite PK leaves the other tenant unchanged."""
    ids = dict(two_tenant_ids)
    own_id = ids.pop(tenant)
    other, other_id = ids.popitem()

    with use_tenant(tenant):
        await services.asset_type.update(
            data={"name": "Lorry"},
            item_id=(tenant, own_id),
            auto_commit=False,
        )

    # Verify own row was updated.
    with use_tenant(tenant):
        my_row = await services.asset_type.get_one_or_none(id=own_id)
    assert my_row is not None
    assert my_row.name == "Lorry"

    # Verify other tenant's row is unchanged.
    with use_tenant(other):
        other_row = await services.asset_type.get_one_or_none(id=other_id)
    assert other_row is not None
    assert other_row.name == "Truck"


@pytest.mark.no_tenant
async def test_select_without_tenant_context_raises(
    services: ServiceBundle, two_tenant_ids: dict[str, UUID]
) -> None:
    """list() with no tenant context raises UnscopedQueryError.

    The two_tenant_ids fixture seeds data so the table is non-empty;
    @no_tenant opts out of the autouse contextvar so the read fires
    without a tenant scope.
    """
    with pytest.raises(UnscopedQueryError):
        await services.asset_type.list()


@pytest.mark.no_tenant
async def test_create_without_context_raises(services: ServiceBundle) -> None:
    """create() with no tenant context raises UnscopedQueryError."""
    with pytest.raises(UnscopedQueryError):
        await services.asset_type.create(
            data={
                "id": UUID("11111111-1111-1111-1111-111111111111"),
                "name": "Z",
                "active": True,
            },
            auto_commit=False,
        )


async def test_create_with_mismatched_tenant_id_raises(services: ServiceBundle) -> None:
    """create() with tenant_id ≠ contextvar raises CrossTenantWriteError."""
    with use_tenant("t-a"), pytest.raises(CrossTenantWriteError):
        await services.asset_type.create(
            data={
                "tenant_id": "t-b",
                "id": UUID("22222222-2222-2222-2222-222222222222"),
                "name": "Z",
                "active": True,
            },
            auto_commit=False,
        )


@pytest.mark.parametrize("tenant", ["t-a", "t-b"])
async def test_list_changes_after_returns_only_own_rows(
    services: ServiceBundle, session: AsyncSession, tenant: str
) -> None:
    """list_changes_after under a tenant must not leak sibling-tenant rows.

    Seeds schema_change_log under both t-a and t-b with overlapping seq
    ranges (each tenant sees its own dense 1, 2, 3, ...). The contextvar
    is what scopes the call to a single tenant's rows.
    """
    # Seed t-a with 3 rows, t-b with 2 rows. Per-tenant dense seq means
    # both tenants observe seq=1, seq=2, so a leak would surface as
    # tenant_id != expected on at least one returned row.
    for _ in range(3):
        with use_tenant("t-a"):
            await services.change_log.append(
                command=SchemaCommand.CREATE_ASSET_TYPE,
                entity_id=uuid4(),
                payload={"name": "x"},
            )
    for _ in range(2):
        with use_tenant("t-b"):
            await services.change_log.append(
                command=SchemaCommand.CREATE_ASSET_TYPE,
                entity_id=uuid4(),
                payload={"name": "y"},
            )
    await session.flush()

    with use_tenant(tenant):
        rows = await services.change_log.list_changes_after(since=0, limit=100)
    assert all(r.tenant_id == tenant for r in rows)
    expected_count = 3 if tenant == "t-a" else 2
    assert len(rows) == expected_count
