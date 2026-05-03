# `create-adr` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a project-local Claude skill at `.claude/skills/create-adr/SKILL.md` that mechanically produces a new ADR (with optional supersession of existing ADRs) following the format defined in `docs/adr/_template.md`.

**Architecture:** Docs/config-only change. One new file: `.claude/skills/create-adr/SKILL.md`. No code, no tests, no build. Verification is two manual walkthrough smoke tests (plain creation + multi-supersession). Spec is at `docs/superpowers/specs/2026-05-03-create-adr-skill-design.md`.

**Tech Stack:** Markdown + YAML frontmatter. Claude Code project-local skill discovery (per official docs: `.claude/skills/<skill-name>/SKILL.md` is discovered for the project where it lives).

**Branch context:** Working on `feat/create-adr-skill` in worktree `.worktrees/create-adr-skill/`. The branch has one prior commit (the spec). PR is not yet open — the final task opens it.

---

### Task 1: Create `.claude/skills/create-adr/SKILL.md`

**Files:**
- Create: `.claude/skills/create-adr/SKILL.md`

The directory `.claude/skills/` does not yet exist; the Write tool will create it.

- [ ] **Step 1: Confirm working directory**

Run: `pwd`

Expected output: `/home/sam/Projects/novamoc/.worktrees/create-adr-skill`

If you see anything else (e.g., `/home/sam/Projects/novamoc` without `.worktrees/...`), STOP — you are in the wrong tree. `cd /home/sam/Projects/novamoc/.worktrees/create-adr-skill` and re-run.

- [ ] **Step 2: Confirm prerequisites**

Run: `ls .claude/ && ls docs/adr/_template.md`

Expected: `.claude/` lists `settings.json` (no `skills/` directory yet — that's fine), and `docs/adr/_template.md` exists. If `_template.md` does NOT exist, STOP — this branch is not based on a main that includes PR #12; do not proceed.

- [ ] **Step 3: Create the file with this EXACT content**

Use the Write tool to create `.claude/skills/create-adr/SKILL.md` with the content below. The Write tool will create the parent directory automatically. Note: the very first character of the file is `-`, the first line is `---` (YAML frontmatter delimiter). No leading blank line.

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

- [ ] **Step 4: Verify the file landed**

Run all of:

```bash
pwd
ls -la .claude/skills/create-adr/SKILL.md
head -5 .claude/skills/create-adr/SKILL.md
tail -5 .claude/skills/create-adr/SKILL.md
grep -cE '^## ' .claude/skills/create-adr/SKILL.md
wc -w .claude/skills/create-adr/SKILL.md
```

Expected:
- `pwd` is the worktree (ends with `.worktrees/create-adr-skill`).
- `ls -la` shows the file exists.
- `head -5` first line is `---`, second line begins with `name: create-adr`.
- `tail -5` last non-blank line ends with `not a content rewrite.` (within the closing fence — actually the last line of the SKILL.md content, since the file has no trailing fence).
- `grep -cE '^## '` reports 6 (the six h2 sections: Overview, When to Use, Prerequisites, Steps, Edge cases, Common mistakes — note the trailing space in the regex excludes h3s).
- `wc -w` reports 700–900 words (the SKILL.md content is ~820 words).

If any check fails, STOP and fix before continuing.

---

### Task 2: Smoke-test plain creation

This is a walkthrough verification — no files are produced. Read `.claude/skills/create-adr/SKILL.md` and walk through the 11 steps as if you were Claude executing the skill for a hypothetical decision. Report what files the skill would produce.

**Hypothetical decision:**
- Title: "Use ruff for Python linting and formatting"
- Context: novaMOC is a Python project; we need a single tool that handles both linting and formatting fast. Existing tools in this space include ruff, flake8 + black, pylint.
- Considered options: ruff; flake8 + black; pylint.
- Chosen: ruff.
- Rationale: ruff is the fastest of the three (Rust implementation), unifies linting and formatting in one tool with one config, and is actively maintained by Astral with a clear roadmap. flake8 + black requires two tools and two configs; pylint is slower and less ergonomic.
- Category: `meta` (build/dev tooling).
- Status: `accepted` (already in use, per the existing pyproject.toml).
- No supersession.

- [ ] **Step 1: Walk through steps 1–7 of the skill**

For each numbered step in `## Steps`, write 1–2 sentences describing what the skill would do for the hypothetical decision above. Specifically:
- Step 2 (supersession): user says "no supersession."
- Step 3 (next number): based on `ls docs/adr/[0-9][0-9][0-9]-*.md`, the highest existing is `015-…`, so next is `016`.
- Step 4 (slug): `ruff-for-linting-and-formatting`.
- Step 5 (category): `meta`.
- Step 6 (frontmatter): status `accepted`, date today, category `meta`, decision-makers from `git config user.name`.
- Step 7 (body): all required sections filled; user includes Consequences (optional) and skips Decision Drivers, Confirmation, Pros and Cons, More Information.

- [ ] **Step 2: Show what step 8 would write**

Reproduce the file content the skill would write to `docs/adr/016-ruff-for-linting-and-formatting.md`. Specifically the YAML frontmatter, the `# ADR-016: Use ruff for Python linting and formatting` heading, then `## Context and Problem Statement`, `## Considered Options`, `## Decision Outcome`, and `### Consequences` sections — with the placeholders filled. Confirm the leading HTML comment block is gone and no inline `<!-- REQUIRED. -->` / `<!-- OPTIONAL. -->` comments remain.

- [ ] **Step 3: Confirm step 11 commit message**

The commit subject should be exactly: `docs(adr-016): use ruff for Python linting and formatting`.

- [ ] **Step 4: Report**

Report back with the produced file content (from Step 2) and the commit message (from Step 3). Confirm the skill steps were sufficient — flag any place the skill was ambiguous or led you to make a judgment call without guidance.

---

### Task 3: Smoke-test multi-supersession

Same walkthrough format as Task 2, but for a hypothetical new ADR that supersedes both a new-format ADR and a grandfathered one. No files are produced.

**Hypothetical decision:**
- Title: "Combined ADR practice and overall architecture"
- Context: This new ADR consolidates ADR-000 (practice / format) and ADR-001 (overall architecture) into a single combined record. ADR-000 was a meta-ADR; ADR-001 captured the three-component architecture. Six months on, the meta-decision and the architecture decision overlap so much in references that combining them aids navigation.
- Considered options: combined ADR; keep them separate; deprecate ADR-001 entirely.
- Chosen: combined ADR.
- Rationale: a single landing-page ADR that introduces the practice and the architecture together is what newcomers want to read first.
- Category: `meta`.
- Status: `accepted` (forced by the supersession path).
- Supersedes: ADR-000 (new format) and ADR-001 (grandfathered four-section format).

NB: this is hypothetical only — the implementer must NOT actually create or modify ADRs during this smoke test. The point is to verify the skill's instructions are clear enough to produce correct output.

- [ ] **Step 1: Walk through steps 1–8**

For each numbered step, describe what the skill does. Highlight:
- Step 2 (supersession): user names ADR-000 and ADR-001.
- Step 3 (next number): same as Task 2 — `016`.
- Step 6 (status): `accepted` (forced by supersession).
- Step 7 (Context): cites both ADR-000 and ADR-001 by number, with a one-sentence reason for the consolidation.

- [ ] **Step 2: Show what step 9 would write for ADR-000**

ADR-000 begins with `---` (YAML frontmatter). The skill should change exactly one line in its frontmatter:

Before:
```yaml
status: accepted
```

After:
```yaml
status: "superseded by ADR-016"
```

Confirm: nothing else in ADR-000 is touched (Context, Considered Options, Decision Outcome, Consequences, More Information all unchanged).

- [ ] **Step 3: Show what step 9 would write for ADR-001**

ADR-001 has no YAML frontmatter — its first non-blank line is `# ADR-001: ...` and it has a `## Status` section with body `Accepted`. The skill should change only that body:

Before:
```
## Status

Accepted
```

After:
```
## Status

Superseded by ADR-016
```

Confirm: nothing else in ADR-001 is touched.

- [ ] **Step 4: Confirm step 11 commit message**

Should be exactly: `docs(adr-016): combined ADR practice and overall architecture (supersedes ADR-000, ADR-001)`.

- [ ] **Step 5: Report**

Report the format-detection logic worked correctly (frontmatter for ADR-000 vs `## Status` section for ADR-001), the new ADR's Context cites both, status is `accepted`, commit subject lists both supersessions. Flag any ambiguity in step 9's format detection (e.g., what if a future ADR has frontmatter AND a `## Status` section? Currently the skill takes frontmatter; flag that as a gap if it surfaced during walkthrough).

---

### Task 4: Commit, push, open PR

- [ ] **Step 1: Confirm worktree state**

Run from the worktree:

```bash
cd /home/sam/Projects/novamoc/.worktrees/create-adr-skill && git status --short
```

Expected:

```
?? .claude/skills/create-adr/SKILL.md
```

Exactly one untracked file. If anything else appears, STOP and investigate.

- [ ] **Step 2: Stage and commit**

```bash
cd /home/sam/Projects/novamoc/.worktrees/create-adr-skill && git add .claude/skills/create-adr/SKILL.md && git commit -m "$(cat <<'EOF'
feat(skill): add create-adr — mechanically write ADRs from settled decisions

Project-local Claude skill at .claude/skills/create-adr/SKILL.md. Reads
docs/adr/_template.md at invocation time so it stays in sync with format
changes. Mechanics-only — defers to superpowers:brainstorming for
unsettled decisions. Supersession is supported (cites old ADRs in Context
and updates each old ADR's status field, with format detection so
grandfathered 001-015 use the ## Status section while new-format ADRs
use frontmatter).

Spec: docs/superpowers/specs/2026-05-03-create-adr-skill-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify: `git log -1 --oneline` should show `feat(skill): add create-adr — mechanically write ADRs from settled decisions`.

- [ ] **Step 3: Push**

```bash
cd /home/sam/Projects/novamoc/.worktrees/create-adr-skill && git push
```

Expected: a successful push to `origin/feat/create-adr-skill` with no errors. The branch already tracks `origin/feat/create-adr-skill` from when the spec commit was pushed.

- [ ] **Step 4: Open the PR (draft)**

```bash
gh pr create --draft --base main --title "feat(skill): create-adr — mechanically write ADRs from settled decisions" --body "$(cat <<'EOF'
## Summary

- Adds **`.claude/skills/create-adr/SKILL.md`**, a project-local Claude skill that mechanically creates ADRs in novaMOC's MADR format. Reads `docs/adr/_template.md` at invocation time so the skill stays in sync with the template; the skill itself never duplicates the template's rules.
- Mechanics-only: assumes the decision is already settled (chosen option + rationale in hand). For unsettled decisions, the skill delegates to `superpowers:brainstorming` first.
- **Supports supersession** end-to-end: when a new ADR replaces existing ADRs, the skill cites them in Context, sets the new ADR's status to `accepted`, and updates each superseded ADR's status field in the same commit. Format detection handles both new-format ADRs (YAML frontmatter `status:`) and the grandfathered 001–015 (Markdown `## Status` section).
- Pure status updates that don't involve writing a new ADR (e.g., marking an Accepted ADR Deprecated) remain out of scope — manual edit per the template.

## Spec

`docs/superpowers/specs/2026-05-03-create-adr-skill-design.md` (in this PR).

## Test plan

- [ ] Read SKILL.md end-to-end; the steps and edge cases match the spec.
- [ ] Confirm Claude discovers the skill (it should appear in available skills on a fresh session, no `enabledPlugins` change needed).
- [ ] Real-world try: invoke the skill for a small upcoming decision and verify it produces a valid ADR file (template's frontmatter parses, sections in correct order, no leftover placeholders or guidance comments).
- [ ] Real-world try: invoke the skill for a hypothetical supersession and verify the superseded ADR's status field is updated correctly without touching anything else.
- [ ] No code touched — pytest / ruff / ty / svelte-check unaffected.
EOF
)"
```

Expected: `gh pr create` returns the PR URL. The PR is draft.

- [ ] **Step 5: Final verification**

Run: `gh pr view --json title,isDraft,headRefName | head`

Confirm:
- `headRefName` is `feat/create-adr-skill`.
- `isDraft` is `true`.
- `title` is `feat(skill): create-adr — mechanically write ADRs from settled decisions`.

---

## Notes for the implementer

- **No tests.** This change is markdown/config-only; the project's test surface (pytest/ruff/ty/svelte-check) doesn't cover it.
- **No partial implementations.** The skill is a single file with a single content. Use the Write tool to create it; do not try to merge with anything that doesn't exist.
- **Branch state:** the worktree is `.worktrees/create-adr-skill/` from the repo root. Run all commands from there. If you find yourself in `/home/sam/Projects/novamoc` (the main checkout), `cd /home/sam/Projects/novamoc/.worktrees/create-adr-skill` first.
- **Smoke tests are walkthroughs.** Tasks 2 and 3 do not produce files. They are mental exercises that surface ambiguity in the skill before it ships.
- **Don't actually create ADR-016 during the smoke tests.** The hypothetical decisions are illustrative only.
