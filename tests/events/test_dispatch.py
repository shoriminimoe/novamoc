"""Tests for the events dispatch table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from novamoc.domain.events import _dispatch as dispatch_mod
from novamoc.domain.events import _payloads
from novamoc.domain.events._payloads import EntityFamily

if TYPE_CHECKING:
    import pytest


async def test_dispatch_routes_created_to_asset_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def _fake(*_args: Any, **_kwargs: Any) -> None:
        called.append("asset.created")

    monkeypatch.setitem(
        dispatch_mod._HANDLERS,
        (EntityFamily.ASSET, _payloads.Created),
        _fake,
    )

    event = _payloads.EventEnvelope(
        hlc="0000000000000001-00000-client-a",
        family=EntityFamily.ASSET,
        type_id=uuid4(),
        instance_id=uuid4(),
        body=_payloads.Created(values={}),
    )
    await dispatch_mod.dispatch(services=None, auth=None, event=event)  # ty: ignore[invalid-argument-type]
    assert called == ["asset.created"]
