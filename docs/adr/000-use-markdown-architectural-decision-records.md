---
status: accepted
date: 2026-05-03
category: meta
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-000: Use Markdown Architectural Decision Records

## Context and Problem Statement

novaMOC's architecture is shaped by a number of consequential decisions, each of which constrains or enables the others. Without a written record of those decisions and the reasoning behind them, future contributors lose the ability to distinguish deliberate choices from accidental drift, or to revisit a decision knowing what depended on it. We need a lightweight, version-controlled, text-based format that lives alongside the code, diffs and reviews like any other change, and captures the *why* of each decision rather than just the outcome.

## Considered Options

* MADR (Markdown Any Decision Records)
* Nygard's original ADR template
* Y-Statements
* No formal decision records

## Decision Outcome

Chosen option: **MADR**, because it is the most active and well-documented of the lightweight markdown ADR formats, gives explicit structure for problem / drivers / options / outcome / consequences (the pieces that make a decision revisitable), and is broadly familiar to industry readers without inventing project-specific terminology. It is heavier than Nygard's three-section format and Y-Statements, but the extra structure is exactly what makes ADRs serve as durable records rather than terse footnotes.

ADRs live in `docs/adr/`, following the conventions in `docs/adr/_template.md` — that template carries the canonical section structure, required-vs-optional rules, status lifecycle, and writing guidance. To create a new ADR, copy the template, rename it `NNN-short-slug.md` (3-digit, lowercase-with-dashes), and fill it in.

### Consequences

* Good, because architectural decisions become reviewable in pull requests like any other change, with reasoning preserved alongside the decision rather than reconstructed from code later.
* Good, because MADR's section structure forces authors to surface alternatives and consequences, not just outcomes.
* Bad, because the format requires discipline — decisions made in chat, meetings, or code reviews don't exist as ADRs unless someone writes them up.

## More Information

ADRs 001–015 predate this revision and use a looser four-section shape (Status / Context / Decision / Consequences). They remain valid records and are not rewritten.
