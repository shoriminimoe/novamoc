"""Snapshot (M2.3) domain — bulk projection transfer (ADR-015).

``GET /snapshot`` returns the tenant's data-projection state as a
paginated bulk transfer plus the ``event_log.seq`` cursor the client
uses to start incremental sync. Historical (as-of) snapshots are out
of scope — only the current projection is served.
"""
