"""Per-entity-kind command handlers.

Each submodule (``asset_type``, ``asset_type_field``, ...) exposes
module-level handler functions named after the verb (``create``,
``activate``, ``update``, ``deactivate``, ``clear``, ``delete``). The
dispatch table in :mod:`novamoc.domain.schema._dispatch` wires those
functions to their command structs.
"""
