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
