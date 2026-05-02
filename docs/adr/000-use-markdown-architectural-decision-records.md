# ADR-000: Use Markdown Architectural Decision Records

## Status

Superseded by ADR-016 (format refinement; the practice itself carries over).

## Context

novaMOC is a local-first web application for asset maintenance tracking with user-defined schemas and offline support. The architecture involves a number of consequential decisions — storage engine, sync protocol, schema modeling, conflict resolution strategy, transport — each of which constrains or enables the others. Without a written record of these decisions and their reasoning, future contributors (including our future selves) will have no way to distinguish decisions that were made deliberately from decisions that accreted by accident, and no way to revisit a decision knowing which other decisions depended on it.

We want a lightweight, version-controlled, text-based format that lives alongside the code, is easy to diff and review, and captures the reasoning behind each decision rather than just the outcome.

## Decision

We will use Architecture Decision Records (ADRs) to document significant architectural decisions for novaMOC. We will use the MADR (Markdown Architectural Decision Records) format.

ADRs will be stored as Markdown files in `docs/adr/` within the repository and numbered sequentially starting from 000. ADR-000 (this document) establishes the practice itself. ADR-001 provides the overall architecture context; subsequent ADRs record specific decisions within that architecture.

Each ADR has a status of Proposed, Accepted, Deprecated, or Superseded. A superseded ADR names the ADR that replaces it; the replacement names the ADR it supersedes. ADRs are not edited after acceptance except to change status or to correct factual errors — new decisions get new ADRs.

## Consequences

Architectural decisions are reviewable in pull requests like any other change. The reasoning behind a decision is preserved alongside the decision itself, which makes revisiting a decision substantially easier than reconstructing intent from code. New contributors can read the ADRs in order to understand how the system arrived at its current shape.

The practice requires discipline: decisions made in chat, in meetings, or in code reviews have to be written up after the fact, or they don't exist as ADRs. We accept this cost.
