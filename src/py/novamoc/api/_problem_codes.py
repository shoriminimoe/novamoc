"""Canonical set of problem-details codes the API may emit.

Every value here corresponds to a markdown file under ``docs/problems/``
and to a leaf segment of the ``type`` URI in problem-details responses.
Adding a new failure mode means adding it here, raising it from a
converter in ``_problem_details.py``, and authoring the matching
markdown doc — the render script enforces that the three stay in sync.
"""

from __future__ import annotations

from novamoc.domain.schema._errors import ErrorCode

PROBLEM_CODES: frozenset[str] = frozenset(
    {c.value for c in ErrorCode} | {"tenant_not_resolved"}
)
