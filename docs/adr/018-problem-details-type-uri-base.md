---
status: accepted
date: 2026-05-05
category: transport
decision-makers: [Sam Caldwell]
consulted: []
informed: []
---

# ADR-018: HTTPS Type-URI Base for Problem-Details Responses

## Context and Problem Statement

ADR-016 left the `type` URI in problem-details responses as the opaque URN
`urn:novamoc:problems:<code>` and named issue #13 as the place where the
host swap would be tracked. The placeholder is now retired: the API serves
per-code documentation directly. This ADR is the amendment that records
how the URI shape was settled.

## Considered Options

* **HTTPS URLs served by the API (`<base>/problems/<code>.html`)** — chosen.
* **HTTPS URLs served by a separate static site (e.g. `docs.novamoc.app`).**
* **Keep the URN placeholder.**

## Decision Outcome

Chosen option: **HTTPS URLs served by the API.** Markdown sources live
under `docs/problems/` and are rendered to HTML at build time; the wheel
ships the rendered pages as package data and Litestar's static-files
router exposes them at `/problems/<code>.html`. The `.html` suffix is
required by the static-files router and carried through to the `type`
URI (`<base>/problems/<code>.html`); clients that branch on the leaf
strip the extension to recover the code. The base host is read from
`NOVAMOC_PROBLEM_DOCS_BASE_URL` (default `http://localhost:8000`) so a
future standalone docs site can take over without a wire-shape change.
The host is opaque per RFC 9457 §3.1.

A separate docs site is the eventual end state but premature now —
hosting the docs alongside the API closes issue #13 with the smallest
change and keeps documentation versioned with the code that emits it.

## More Information

* Amends ADR-016. The "non-reachable URN" paragraph in ADR-016 is
  superseded by this ADR.
* Closes issue #13.
* The ``.html`` suffix in the URL is a Litestar static-files router
  convention (no extensionless rewrites). A custom handler could keep
  the URL extensionless but adds code to maintain; serving the file
  verbatim is simpler and the contract is still stable.
