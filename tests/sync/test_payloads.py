"""Regression guards for the sync wire-format structs."""

from __future__ import annotations

import msgspec
import pytest

from novamoc.domain.sync._payloads import (
    AssetFieldValuesBatchBody,
    AssetsBatchBody,
    MaintenanceRecordFieldValuesBatchBody,
    MaintenanceRecordsBatchBody,
)


@pytest.mark.parametrize(
    ("body_type", "tag"),
    [
        (AssetsBatchBody, "assets"),
        (AssetFieldValuesBatchBody, "asset_field_values"),
        (MaintenanceRecordsBatchBody, "maintenance_records"),
        (MaintenanceRecordFieldValuesBatchBody, "maintenance_record_field_values"),
    ],
)
def test_batch_body_rejects_unknown_fields(body_type: type, tag: str) -> None:
    """``forbid_unknown_fields`` set on ``_SyncBody`` propagates to
    every ``*BatchBody`` subclass via msgspec inheritance.

    A regression guard for `the PR-104 review
    <https://github.com/shoriminimoe/novamoc/pull/104>`_ — if anyone
    re-declares one of the subclasses without keeping the config
    inheritance intact, this test fails loudly.
    """
    raw = f'{{"table":"{tag}","items":[],"extra":42}}'.encode()
    with pytest.raises(msgspec.ValidationError, match="unknown field"):
        msgspec.json.decode(raw, type=body_type)
