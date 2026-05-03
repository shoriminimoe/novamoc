# ADR-000 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ADR-000 with a MADR-shaped rewrite, add `docs/adr/_template.md` as a copyable scaffold + format spec, and update the CLAUDE.md ADR pointer to match.

**Architecture:** Docs-only change. Three files touched, all under `docs/adr/` plus a one-line update in `CLAUDE.md`. No code, no tests, no build artifacts. Verification is by visual diff against the approved spec at `docs/superpowers/specs/2026-05-03-adr-format-redesign-design.md`.

**Tech Stack:** Markdown + YAML frontmatter. Renders on GitHub PR view.

**Branch context:** Working on `docs/adr-format-refinement` in worktree `.worktrees/adr-format/`. The branch already has seven iteration commits (the prior, looser ADR-000 attempt plus the spec). The spec [calls for a single new commit](../specs/2026-05-03-adr-format-redesign-design.md#d-pr-12-history) on top — squash to one commit happens at GitHub merge time.

---

### Task 1: Rewrite ADR-000

**Files:**
- Modify (full rewrite): `docs/adr/000-use-markdown-architectural-decision-records.md`

- [ ] **Step 1: Replace the entire file with the approved content**

Use the Write tool to overwrite `docs/adr/000-use-markdown-architectural-decision-records.md` with this exact content (including the YAML frontmatter delimiters):

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

- [ ] **Step 2: Verify the file matches**

Run: `head -40 docs/adr/000-use-markdown-architectural-decision-records.md`

Expected: the first 40 lines start with `---`, then `status: accepted`, `date: 2026-05-03`, `category: meta`, etc., then the title `# ADR-000: Use Markdown Architectural Decision Records`. No leftover content from the prior version.

- [ ] **Step 3: Confirm word count is in range**

Run: `wc -l docs/adr/000-use-markdown-architectural-decision-records.md`

Expected: 30–35 lines (the file as drafted is 31 lines).

---

### Task 2: Create `docs/adr/_template.md`

**Files:**
- Create: `docs/adr/_template.md`

- [ ] **Step 1: Create the file with the approved content**

Use the Write tool to create `docs/adr/_template.md` with this exact content:

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

- [ ] **Step 2: Verify the file matches**

Run: `head -5 docs/adr/_template.md && echo '...' && tail -5 docs/adr/_template.md`

Expected:
- First line is `<!--`
- Second line is `novaMOC ADR template (MADR full template, customized for this repo).`
- Last non-blank line is `{Anything else worth noting.}`

- [ ] **Step 3: Confirm structure**

Run: `grep -nE '^(##|<!--|---)' docs/adr/_template.md | head -25`

Expected: an opening `<!--` on line 1, a frontmatter `---` block opener and closer, then `# ADR-NNN: ...` near the top of the body, then `## Context and Problem Statement`, `## Decision Drivers`, `## Considered Options`, `## Decision Outcome`, `### Consequences`, `### Confirmation`, `## Pros and Cons of the Options`, `## More Information` in that order.

---

### Task 3: Update the CLAUDE.md ADR pointer line

**Files:**
- Modify: `CLAUDE.md` (the bullet under `## ADR pointers (read these when touching the relevant subsystem)`)

- [ ] **Step 1: Read the file to find the exact pointer line**

Use the Read tool on `CLAUDE.md` and locate this line (currently the first bullet under `## ADR pointers`):

```
- ADR-000 — the ADR practice and format (brief context, one-line decision + rationale, 2–3 key tradeoffs). ADRs record a decision and its reasoning; design discussion is allowed where it supports that, but exhaustive design lives in the developer docs.
```

- [ ] **Step 2: Replace it**

Use the Edit tool with these strings:

old_string:
```
- ADR-000 — the ADR practice and format (brief context, one-line decision + rationale, 2–3 key tradeoffs). ADRs record a decision and its reasoning; design discussion is allowed where it supports that, but exhaustive design lives in the developer docs.
```

new_string:
```
- ADR-000 — the ADR practice. To start a new ADR, copy `docs/adr/_template.md`; that template carries the section structure, required-vs-optional rules, status lifecycle, and writing guidance. ADRs 001–015 use the older four-section shape and are grandfathered.
```

- [ ] **Step 3: Verify**

Run: `grep -n "ADR-000" CLAUDE.md`

Expected: exactly one line, the new bullet, in the ADR pointers section. If the prior line variant still appears or there are duplicates, stop and re-check.

---

### Task 4: Final review and single commit

- [ ] **Step 1: Confirm the working tree state**

Run: `git status --short`

Expected:
```
 M CLAUDE.md
 M docs/adr/000-use-markdown-architectural-decision-records.md
?? docs/adr/_template.md
```

If any other files appear modified, investigate before continuing.

- [ ] **Step 2: Review the diff**

Run: `git diff CLAUDE.md docs/adr/000-use-markdown-architectural-decision-records.md && echo '---' && cat docs/adr/_template.md | head -50`

Visually confirm:
- ADR-000's whole body is replaced; YAML frontmatter present at the top.
- CLAUDE.md changes only the one ADR-000 pointer line.
- `_template.md` content begins with the `<!--` comment block.

- [ ] **Step 3: Stage and commit (single commit, per spec section D)**

Run:

```bash
git add CLAUDE.md docs/adr/000-use-markdown-architectural-decision-records.md docs/adr/_template.md
git commit -m "$(cat <<'EOF'
docs(adr-000): redesign per spec; adopt MADR full template

Replaces ADR-000 with a MADR-shaped rewrite (YAML frontmatter, Context
and Problem Statement, Considered Options, Decision Outcome, Consequences,
More Information). Adds docs/adr/_template.md as the copyable scaffold
and canonical format spec — naming, lifecycle, supersession, philosophy,
and style guidance live in its top comment block. Updates the CLAUDE.md
ADR pointer to direct authors at the template. ADRs 001-015 unchanged.

Spec: docs/superpowers/specs/2026-05-03-adr-format-redesign-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push and confirm PR is updated**

Run: `git push && gh pr view 12 --json commits --jq '.commits[-1].messageHeadline'`

Expected: the push succeeds, and the last commit headline is `docs(adr-000): redesign per spec; adopt MADR full template`.

- [ ] **Step 5: Update the PR description to match the new design**

The current PR body still describes the prior, looser approach. Replace it via:

```bash
gh pr edit 12 --title "docs(adr-000): redesign — adopt MADR full template" --body "$(cat <<'EOF'
## Summary

- Rewrites **ADR-000** in MADR full template form (YAML frontmatter, Context and Problem Statement, Considered Options, Decision Outcome, Consequences, More Information). Records the decision to use MADR alongside the alternatives that were considered (Nygard's template, Y-Statements, no formal decision records).
- Adds **`docs/adr/_template.md`** as the copyable scaffold and canonical format spec. Its top comment block carries the naming convention (`NNN-short-slug.md`, 3-digit sequential), required-vs-optional section rules, status lifecycle (proposed / accepted / rejected / deprecated / superseded), supersession syntax, philosophy ("decision records, not comprehensive design documents"), and writing style.
- Updates the **CLAUDE.md** ADR pointer to direct authors at the template.
- ADRs 001–015 are grandfathered — unchanged.

The branch's earlier iteration commits land in history; the GitHub merge UI will squash them down to one commit on `main`.

## Spec

`docs/superpowers/specs/2026-05-03-adr-format-redesign-design.md` (in this PR).

## Test plan

- [ ] ADR-000 reads cleanly as a worked example of the new template.
- [ ] Copying `docs/adr/_template.md` to `docs/adr/016-foo.md` and filling it in feels natural.
- [ ] No code touched — pytest / ruff / ty / svelte-check unaffected.
EOF
)"
```

Expected: `gh pr edit` returns the PR URL with no error.

---

## Notes for the implementer

- **No tests.** This change is markdown-only; the project's test surface (pytest/ruff/ty/svelte-check) doesn't cover it.
- **No partial implementations.** ADR-000 is a full file rewrite — do not try to merge with existing content. The Write tool overwrites; that is correct here.
- **Branch state:** the worktree is `.worktrees/adr-format/` from the repo root. Run all commands from there. If you find yourself in `/home/sam/Projects/novamoc` (the main checkout), `cd /home/sam/Projects/novamoc/.worktrees/adr-format` first.
- **Don't squash locally.** The spec calls for the squash to happen at GitHub merge time, not via `git rebase -i` on the branch.
- **Pre-existing files:** `docs/adr/_template.md` does not yet exist. If it does, stop and check.
