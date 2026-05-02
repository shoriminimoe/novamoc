# ADR-016: ADRs are decision records, not design documents

## Status

Accepted. Supersedes ADR-000.

## Context

ADR-000 established the practice of using MADR-formatted Architecture Decision Records in `docs/adr/`. In use, several ADRs (notably 008, 009, 011, 012, 013) grew into design documents — full pipelines, code samples, exhaustive consequence lists. That's friction at write time and noise at read time. The practice still holds; the format needs sharpening, and bundling that refinement with the original definition keeps the practice in one place.

## Decision

ADRs record decisions, not designs. Design content lives in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

Each ADR is a Markdown file in `docs/adr/`, numbered sequentially from 000. The body has four sections:

- **Status** — Proposed | Accepted | Deprecated | Superseded (cite the replacement when superseded).
- **Context** — brief problem statement; only the background needed to make the decision intelligible.
- **Decision** — one sentence stating the choice, plus a short rationale paragraph if needed.
- **Consequences** — two or three of the most important tradeoffs. Not exhaustive.

ADRs are not edited after acceptance except to change status or correct factual errors; new decisions get new ADRs. ADRs cite each other by number rather than recapping upstream facts.

## Consequences

ADRs become quicker to write and easier to scan, which lowers the barrier to recording a decision at the moment it's made. Existing ADRs (000–015) are not rewritten — they remain valid records under the looser convention; the new format applies to ADR-017 onward. Design content that previously bled into ADRs now belongs in specs and plans, where iteration is expected.
