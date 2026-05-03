# Spec: ADR-000 redesign — adopt MADR full template

**Date:** 2026-05-03
**Branch:** `docs/adr-format-refinement` (PR [#12](https://github.com/shoriminimoe/novamoc/pull/12))
**Status:** approved (brainstorming complete; ready for implementation plan)

## Background

The current ADR-000 (and the briefly-extant ADR-016 it spawned) iterated through several
quick passes that left the result loose: section content was loosely defined, lifecycle
was implied rather than specified, and there was no template scaffold or naming/numbering
spec. This redesign replaces that with a deliberate, MADR-based setup.

Research informing this design: [adr.github.io ad-practices](https://adr.github.io/ad-practices/),
[MADR](https://adr.github.io/madr/), and the linked ozimmer.ch articles on Definition of
Ready (START), ADR Creation, ADR Review, and the MADR Template Primer.

## Goals

- ADR-000 is itself a decision record in the new format — a worked example of the shape
  every new ADR will take.
- The format used in novaMOC is standard MADR full template — readers familiar with MADR
  see no surprises, no project-specific terminology to learn.
- A copyable template at `docs/adr/_template.md` carries the canonical spec (section
  list, required-vs-optional rules, status lifecycle, supersession syntax, naming
  conventions, philosophy, style guidance). One file is the source of truth; ADR-000
  references it rather than restating its rules.
- ADRs 001–015 are grandfathered unchanged.

## Non-goals

- **No workflow gates.** No enforced START Definition of Ready; no required review
  checklist. ADR-000 prescribes format and lifecycle only. The current scale of the
  project doesn't justify process bureaucracy.
- **No renumbering of existing ADRs.** We stay 3-digit going forward.
- **No backfilling of MADR shape into ADRs 001–015.** They remain valid records in
  their original four-section form.

## Decisions made (during brainstorming)

1. **Format:** Standard MADR full template, adopted wholesale.
2. **Required sections:** MADR's defaults — Context and Problem Statement, Considered
   Options, Decision Outcome. All other sections (Decision Drivers, Consequences,
   Confirmation, Pros and Cons of the Options, More Information) are optional. The
   author may include or omit any optional section; reviewers may request inclusion of
   an omitted one.
3. **Frontmatter:** YAML frontmatter, per MADR, with `status`, `date`, `category`,
   `decision-makers`, `consulted`, `informed`. `category` is a novaMOC-specific
   free-form tag for indexing/search (e.g., `storage`, `sync`, `schema`, `transport`,
   `multi-tenancy`, `meta`).
4. **Workflow rigor:** ADR-000 prescribes format and lifecycle only.
5. **Numbering:** 3-digit, sequential, going forward (next is 016).
6. **Template file:** `docs/adr/_template.md` (leading underscore signals "not an ADR";
   sorts to the top).
7. **ADR-000 shape:** Follows the new MADR template format. Operational conventions
   live as inline guidance in `_template.md`, not duplicated in ADR-000.

## Artifacts

### A. ADR-000 (rewritten — replaces the entire current contents)

```markdown
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
```

### B. `docs/adr/_template.md` (new file)

```markdown
<!--
novaMOC ADR template (MADR full template, customized for this repo).

How to use:
1. Copy this file:  cp docs/adr/_template.md docs/adr/NNN-short-slug.md
2. NNN is the next available 3-digit number, sequential.
3. Slug is lowercase-with-dashes, representative of the decision.
4. Fill in or remove sections per the inline guidance below.
5. Delete this top comment block before committing the new ADR.

Required sections:  Context and Problem Statement, Considered Options, Decision Outcome.
Optional sections:  Decision Drivers, Consequences, Confirmation, Pros and Cons of the
                    Options, More Information. The author may include or omit any optional
                    section; reviewers may request inclusion of an omitted optional section.

ADRs are decision records, not comprehensive design documents. They may include design
discussion to the extent the decision or its rationale needs, but exhaustive design
content belongs elsewhere. Code, types, or examples that appear in an ADR should not
be considered an implementation contract.

Style: assertive, factual; avoid marketing language. Disclose uncertainty when it exists —
fair reviewers appreciate honesty about confidence. Cite related ADRs by number rather
than recapping their content.

Status lifecycle:
  proposed                  — opened for discussion; the decision is not yet in force
  accepted                  — approved; the decision is in force
  rejected                  — considered and not adopted (kept on file for the record)
  deprecated                — no longer current and not replaced
  superseded by ADR-NNN     — replaced; cite the replacement ADR by number

ADRs are not edited after acceptance except to change status or correct factual errors;
new decisions get new ADRs. When superseding, update the old ADR's frontmatter status to
"superseded by ADR-NNN" and let the new ADR cite the old one in its Context section.

Category is a free-form tag for indexing and search (e.g., storage, sync, schema, transport,
multi-tenancy, meta). Pick the primary area; if a decision spans two, pick the most central.
-->

---
status: "{proposed | accepted | rejected | deprecated | superseded by ADR-NNN}"
date: {YYYY-MM-DD when last updated}
category: {free-form tag, e.g. storage / sync / schema / transport / multi-tenancy / meta}
decision-makers: [{names}]
consulted: [{names of subject-matter experts; two-way communication}]
informed: [{names kept up to date; one-way communication}]
---

# ADR-NNN: {short title — representative of the problem and chosen solution}

## Context and Problem Statement

<!-- REQUIRED. Two to three sentences, or a short narrative, framing the situation and the
     question being decided. You may articulate the problem as a question. -->

{Describe the situation and the question being decided.}

<!-- OPTIONAL. Forces, constraints, or qualities that motivated the decision. Bullet list. -->
## Decision Drivers

* {driver 1, e.g. a desired quality, a constraint, a force}
* {driver 2}

## Considered Options

<!-- REQUIRED. Two or more alternatives, listed at the same level of abstraction (don't compare
     a technology to a product, or an architectural style to a protocol spec). List the chosen
     option first. -->

* {chosen option}
* {alternative 1}
* {alternative 2}

## Decision Outcome

<!-- REQUIRED. State the chosen option and the rationale. The rationale is one of the most
     important parts of the document — it is what makes the decision revisitable later.
     Clarity beats brevity, but it should not be verbose for its own sake. -->

Chosen option: **{chosen option}**, because {rationale}.

<!-- OPTIONAL. Two or three of the most important tradeoffs that follow from the decision.
     Not exhaustive. Use Good / Bad framing. -->
### Consequences

* Good, because {positive consequence}.
* Bad, because {negative consequence}.

<!-- OPTIONAL. How implementation alignment will be verified — a code review, test, lint
     rule, ArchUnit-style check, etc. -->
### Confirmation

{How the decision is enforced or checked.}

<!-- OPTIONAL. Per-option pros/cons when the rationale needs more depth than fits in
     Decision Outcome. Use Good / Bad / Neutral. -->
## Pros and Cons of the Options

### {chosen option}

* Good, because {argument}.
* Bad, because {argument}.

### {alternative 1}

* Good, because {argument}.
* Neutral, because {argument}.
* Bad, because {argument}.

<!-- OPTIONAL. Additional evidence, team agreement, confidence level, revisit triggers,
     links to other decisions or external resources. -->
## More Information

{Anything else worth noting.}
```

### C. `CLAUDE.md` ADR pointer line update

The current pointer line:

> - ADR-000 — the ADR practice and format (brief context, one-line decision + rationale, 2–3 key tradeoffs). ADRs record a decision and its reasoning; design discussion is allowed where it supports that, but exhaustive design lives in the developer docs.

becomes:

> - ADR-000 — the ADR practice. To start a new ADR, copy `docs/adr/_template.md`; that template carries the section structure, required-vs-optional rules, status lifecycle, and writing guidance. ADRs 001–015 use the older four-section shape and are grandfathered.

### D. PR #12 history

The branch currently has six commits iterating on the prior, looser approach. The
implementation plan should:

- Land the redesign as a single new commit on top of the existing six (no rewriting
  of pushed history).
- When the PR is ready to merge, squash via the GitHub merge UI so the resulting
  `main` commit is one tidy `docs(adr): ...` commit.

## Out of scope

- Redesign of any other ADR.
- Changes to `docs/superpowers/` layout.
- Tooling for ADR indexing/search (the `category` field exists for future tooling, but
  we are not building that tooling now).
- Any process automation (CI lint of ADR shape, status-transition checks, etc.).

## Open questions

None.
