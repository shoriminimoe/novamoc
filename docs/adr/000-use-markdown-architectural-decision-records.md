# ADR-000: Use Markdown Architectural Decision Records

## Status

Accepted

## Context

novaMOC's architecture involves a number of consequential decisions — storage engine, sync protocol, schema modeling, conflict resolution, transport — each of which constrains or enables the others. Without a written record of those decisions and their reasoning, future contributors (including our future selves) lose the ability to distinguish deliberate choices from accidental drift, or to revisit a decision knowing what depended on it.

We need a lightweight, version-controlled, text-based format that lives alongside the code, diffs and reviews like any other change, and captures the *why* of each decision rather than just the outcome.

## Decision

We use Architecture Decision Records (ADRs) in [MADR](https://adr.github.io/madr/) format, stored as Markdown files in `docs/adr/` and numbered sequentially from 000.

ADRs record decisions, not designs. Design content — pipelines, code samples, evolving spec — belongs in the developer docs, not in ADRs. Any code, types, or examples that do appear in an ADR are illustrative pseudo-code, not an implementation contract.

Each ADR has four sections:

- **Status** — Proposed | Accepted | Deprecated | Superseded (cite the replacement when superseded).
- **Context** — brief problem statement; only the background needed to make the decision intelligible.
- **Decision** — one sentence stating the choice, followed by the rationale. The rationale is required and is one of the most important parts of the document — it is what makes a decision revisitable. Clarity beats brevity, though it shouldn't be verbose for its own sake.
- **Consequences** — two or three of the most important tradeoffs. Not exhaustive.

ADRs are not edited after acceptance except to change status or correct factual errors; new decisions get new ADRs. ADRs cite each other by number rather than recapping upstream facts.

The rationale: code shows the present shape but cannot answer "what would have to change for us to undo this?" without preserved reasoning, and an ADR is the artifact that makes that question answerable. MADR is the lightest format that still captures the pieces that matter — context, decision, rationale, consequences — and keeping ADRs in-tree means each one ships with the change it justifies, gets PR review, and can't drift from a separate wiki the way out-of-tree docs do. Constraining ADRs to *decisions, not designs* keeps them small enough that recording one at the moment of decision stays cheap; design content has its own iterative, sometimes-throwaway lifecycle that doesn't fit immutability-after-accept and belongs in the developer docs instead.

## Consequences

Architectural decisions become reviewable in pull requests like any other change, and the reasoning is preserved alongside the decision rather than reconstructed from code later. The tight format — brief context, one-line decision plus rationale, 2–3 key tradeoffs — keeps the cost of recording a decision low enough that the practice stays sustainable. The cost is discipline: decisions made in chat, meetings, or code reviews don't exist as ADRs unless someone writes them up afterward, and we accept that.
