from advanced_alchemy.base import BigIntPrimaryKey
from sqlalchemy.orm import Mapped, mapped_column

class Event(BigIntPrimaryKey):

    __tablename__ = "event_log"

    tenant_id = Mapped[str]
    hlc: Mapped[str] = mapped_column(index=True)
    node_id: Mapped[str]

# CREATE TABLE event_log (
#   seq           INTEGER PRIMARY KEY AUTOINCREMENT,
#   table_name    TEXT NOT NULL,  -- e.g. 'asset_field_values', 'assets'
#   entity_id     TEXT NOT NULL,
#   field_id      TEXT,           -- NULL for row-level operations
#   op            TEXT NOT NULL,  -- 'set' | 'delete'
#   value_json    TEXT,           -- NULL for deletes
#   received_at   TEXT NOT NULL,
#   UNIQUE (tenant_id, node_id, hlc)
# );
#
# CREATE INDEX idx_event_log_tenant_seq ON event_log(tenant_id, seq);
