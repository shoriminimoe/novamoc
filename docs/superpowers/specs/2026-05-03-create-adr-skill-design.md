# Spec: `create-adr` skill

**Date:** 2026-05-03
**Branch:** `feat/create-adr-skill`, based on `main` (PR [#12](https://github.com/shoriminimoe/novamoc/pull/12) — the ADR-000 redesign that introduced `docs/adr/_template.md` — has merged).
**Status:** approved (brainstorming complete; ready for implementation plan)

## Background

PR #12 introduced `docs/adr/_template.md` as the canonical MADR-based format spec for
novaMOC ADRs. With that format settled, the next step is a Claude skill that
mechanically produces a new ADR from a settled decision — picks the next number, gathers
content, fills the template, commits.

## Goals

- A project-local Claude skill at `.claude/skills/create-adr/SKILL.md` that ships with
  the repo.
- Mechanics-only. The skill assumes the decision is already made (chosen option +
  rationale in hand); it does not brainstorm.
- Reads `docs/adr/_template.md` at invocation time. The template is the format source of
  truth; the skill never duplicates the template's rules and stays in sync automatically
  when the template changes.
- Defers to existing skills for adjacent concerns: `superpowers:brainstorming` for
  unsettled decisions; manual edit (per the template's lifecycle guidance) for status
  updates that don't involve writing a new ADR (e.g., marking an Accepted ADR as
  Deprecated).
- **Supersession is in scope.** When the new ADR replaces one or more existing ADRs,
  the skill updates the superseded ADRs' status fields in the same commit.

## Non-goals

- **Not a generic ADR skill.** This is novaMOC-specific (paths, conventions, category
  examples). A generic version is a different artifact.
- **No status updates on existing ADRs without writing a new ADR.** Marking an
  Accepted ADR Deprecated, flipping a Proposed ADR to Accepted, etc., is a manual
  edit per the template's lifecycle guidance. (Supersession itself *is* in scope —
  see Goals.)
- **No CLAUDE.md updates.** The skill creates the ADR file and commits; whether the new
  ADR earns a pointer in CLAUDE.md's `## ADR pointers` section is a curatorial decision
  the user makes separately.
- **No multi-ADR creation in one invocation.** Invoke once per ADR.
- **No skill-testing rigor (writing-skills RED-GREEN-REFACTOR).** A manual smoke test
  during implementation is sufficient for a project-local mechanical skill.

## Decisions made (during brainstorming)

1. **Behavior:** Mechanics-only. If the decision isn't ready, the user invokes
   `superpowers:brainstorming` first.
2. **Scope:** Project-local (`.claude/skills/create-adr/`), ships with the repo.
3. **Files:** Single `SKILL.md`. No support files; the template at `docs/adr/_template.md`
   is the format reference and is read live.
4. **Description style:** Per writing-skills guidance — third-person, "Use when…",
   triggering conditions only, no workflow summary.

## Artifact

### `.claude/skills/create-adr/SKILL.md`

```markdown
---
name: create-adr
description: Use when the user wants to record an architectural decision in novaMOC's ADR log — typically after a decision has been made (in chat, after a brainstorming session, or already settled). Triggers: "create an ADR for X", "write up the decision about X", "log this as ADR-NNN", or any request to add a new file under docs/adr/. If the decision hasn't been thought through yet, invoke superpowers:brainstorming first and come back here once there's a chosen option and rationale to record.
---

# Create ADR

## Overview

Mechanically create a new ADR in `docs/adr/` from a decision the user has already made.
The format spec lives in `docs/adr/_template.md` (the top HTML comment block); this skill
defers to that template and never duplicates its rules.

## When to Use

Use when the user has a settled decision to record:
- They've described a problem and stated a chosen approach.
- They've finished a brainstorming session and the decision is locked.
- They explicitly say "create an ADR for X" / "write this up as an ADR".

Use this skill — including the supersession path below — when a new ADR replaces one
or more existing ADRs.

Do NOT use when:
- The decision is still being explored — invoke `superpowers:brainstorming` first.
- The user is asking about ADR format/policy — point them at ADR-000 and `docs/adr/_template.md`.
- The change is a *pure* status update on an existing ADR with no new ADR involved
  (e.g., marking an Accepted ADR as Deprecated, or flipping a Proposed ADR to
  Accepted) — manual edit per the template's lifecycle guidance.

## Prerequisites

The user must have, at minimum:
1. A short title for the decision.
2. A problem / context statement.
3. The alternatives that were considered.
4. The chosen alternative and the rationale.

If any are missing, ask before writing. Push back on thin rationale — it's the most
important part of the ADR.

## Steps

1. **Read the template.** Open `docs/adr/_template.md` and re-read its top HTML comment.
   That comment block is the canonical spec. If this skill ever conflicts with the
   template, the template wins.

2. **Determine supersession.** Ask the user whether the new ADR replaces any existing
   ADR(s). Note the list of superseded numbers (zero, one, or more). This affects the
   new ADR's `status` (always `accepted` when superseding), its Context (must cite the
   superseded ADRs by number), and adds a status-update step on the superseded ADRs
   later.

3. **Pick the next number.** List `docs/adr/[0-9][0-9][0-9]-*.md`, find the highest
   3-digit prefix, increment by 1. Zero-pad to 3 digits.

4. **Pick a slug.** Lowercase, dash-separated, representative of the decision (not the
   title verbatim). Confirm with the user.

5. **Pick a category.** Free-form tag. Common novaMOC values: `meta`, `storage`, `sync`,
   `schema`, `transport`, `multi-tenancy`. Pick the primary area; if a decision spans
   two, pick the most central. Ask if unclear.

6. **Gather frontmatter values:**
   - `status` — `accepted` when superseding any existing ADRs (the new ADR is in force
     the moment it replaces them). Otherwise default to `proposed`; use `accepted` only
     if the user says the decision is already in force.
   - `date` — today (UTC).
   - `category` — from step 5.
   - `decision-makers` — try `git config user.name`; ask if multiple people.
   - `consulted`, `informed` — `[]` unless the user names someone.

7. **Gather body content:**
   - **Context and Problem Statement** (required) — 2-3 sentences. If superseding, the
     Context must cite the superseded ADR(s) by number and briefly explain what changed
     since they were written (the substantive reason this is a new decision rather than
     an amendment).
   - **Considered Options** (required) — 2+ alternatives at the same abstraction
     level (don't compare a technology to a product). List the chosen option first.
   - **Decision Outcome** (required) — `Chosen option: **X**, because Y.` form,
     followed by the rationale paragraph. Push for a clear rationale — it's what makes
     the decision revisitable.
   - **Decision Drivers**, **Consequences**, **Confirmation**, **Pros and Cons of the
     Options**, **More Information** (all optional) — include any the user wants or
     that genuinely apply. Skip the rest.

8. **Write the new ADR file** to `docs/adr/NNN-<slug>.md`. Start from the template body,
   then:
   - Strip the leading `<!-- ... -->` HTML comment block.
   - Strip every section's inline `<!-- REQUIRED. -->` / `<!-- OPTIONAL. -->` comment.
   - Remove optional section headings the user chose to omit.
   - Replace every `{placeholder}` with real content.

9. **If superseding, update each superseded ADR's status.** For each superseded ADR:
   - Detect format by reading the first line. If it begins with `---`, the file uses
     YAML frontmatter — update the `status` value to `"superseded by ADR-NNN"`
     (quoted; the value contains spaces). If the first non-blank line begins with
     `#` (no frontmatter), it's the older four-section shape used by ADRs 001–015 —
     update the `## Status` section's value to `Superseded by ADR-NNN`.
   - Touch only the status field. Do not modify any other content of the superseded
     ADR.

10. **Show the result.** Present every changed file to the user — the new ADR plus any
    status edits on superseded ADRs. Confirm before committing.

11. **Commit.** Single commit covering all changes.
    - Creating only: `docs(adr-NNN): <title>`.
    - Superseding: `docs(adr-NNN): <title> (supersedes ADR-MMM)` for one; for multiple,
      `(supersedes ADR-MMM, ADR-LLL)`.

## Edge cases

- **Multi-supersession.** One new ADR may replace several existing ADRs. Cite each in
  the Context; update each superseded ADR's status individually in step 9; list them
  all in the commit subject.
- **Superseding a grandfathered ADR (001–015).** Step 9's format detection handles
  this — the older shape uses a `## Status` Markdown section instead of YAML
  frontmatter. Update only that section's value.
- **Pure status updates.** Marking an Accepted ADR Deprecated, or flipping a Proposed
  ADR to Accepted, is a manual edit per the template — out of scope for this skill.
- **Multiple new ADRs at once.** Invoke this skill once per ADR.

## Common mistakes

- Forgetting to strip the template's top HTML comment block.
- Inventing format rules instead of re-reading the template — the template is the source
  of truth, and it can change.
- Comparing options at different abstraction levels.
- Skipping or thinning the rationale because the chosen option seems obvious.
- Auto-numbering without scanning for the highest existing N (leads to collisions if
  another ADR landed since you last looked).
- **Forgetting the second half of supersession** — writing the new ADR but failing to
  update the old ADR's status. The supersession becomes invisible to anyone reading
  the old file.
- **Mismatching the status format on supersession** — using a frontmatter edit on a
  grandfathered ADR (which has no frontmatter) or editing a `## Status` section on a
  new-format ADR (which has none). Detect the format first.
- **Touching content beyond the status field on a superseded ADR.** The template says
  ADRs are not edited after acceptance except to change status; supersession is the
  status change, not a content rewrite.
```

## Verification

Two manual smoke tests during implementation:

- **Plain creation.** Simulate invoking the skill with a representative hypothetical
  decision (e.g., "we use ruff for linting"). Walk through the steps by hand and
  confirm a valid ADR file would be produced — correct path, frontmatter parses, all
  placeholders replaced, optional sections cleanly omitted, top HTML comment stripped.
- **Supersession.** Simulate a hypothetical new ADR superseding both a new-format ADR
  (e.g., ADR-000) and a grandfathered ADR (e.g., ADR-007). Confirm: the new ADR's
  Context cites both by number; the new ADR's `status` is `accepted`; ADR-000's
  frontmatter `status` becomes `"superseded by ADR-NNN"`; ADR-007's `## Status` body
  becomes `Superseded by ADR-NNN`; the commit subject lists both supersessions.

## Out of scope

- Generic ADR creation skill (publishable to other projects).
- Skill discovery configuration / settings.json changes — the skill is project-local at
  `.claude/skills/`, which the harness picks up automatically.
- Updating CLAUDE.md to mention the skill — Claude already lists available skills via
  the system prompt; no documentation needed.
- Tests beyond a manual smoke test.

## Open questions

None.
