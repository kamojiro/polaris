<!--
Sync Impact Report
- Version change: [TEMPLATE] → 1.0.0 (initial ratification)
- Modified principles: n/a (first ratified version; template placeholders replaced)
- Added sections: Core Principles I–V, Scope Constraints, Development Workflow, Governance
- Removed sections: none
- Templates requiring updates: none checked yet — no dependent .specify/templates/*.md
  reference concrete principle names, so no follow-up edits are required at this time.
- Follow-up TODOs: RATIFICATION_DATE (original adoption predates this file; the source
  draft, docs/constitution.draft.md, carries no date of its own)
-->

# Polaris Constitution

## Core Principles

### I. Python + Pydantic AI
The implementation language is Python, with typing centered on Pydantic. Agent behavior is
implemented with Pydantic AI v2. Domain data, API request/response shapes, and settings MUST be
modeled as Pydantic (or SQLModel) types rather than untyped dicts, so that type checking
(`pyright`) can catch structural errors before runtime.

### II. YAGNI for a Single-User Tool
This is a personal-use platform, not a multi-tenant product. Over-generalization and the
introduction of DI frameworks or other enterprise-scale abstractions MUST be avoided. Features are
built for the one actual use case in front of them; speculative extensibility is not a goal.
Simplicity is preferred even where it means less "correct" architecture in the abstract.

### III. Model Selection via Settings Only
Which LLM is used is controlled exclusively through settings values (`Settings`/`*Settings`
classes, `.env`), never hardcoded in application code. The development phase defaults to the free
OpenRouter-hosted Qwen3-30B-A3B; the production phase uses Qwen3.6-35B-A3B. Narrower tasks (e.g.
memory recall) MAY use a separate, lighter model, again selected via a dedicated settings field.
Switching models MUST require only a settings/env change, never a code change.

### IV. Hub/Satellite Data Pattern
Knowledge data is modeled with a Hub/Satellite pattern: generic `Item`/`Chunk`/`Embedding` tables
form the hub, and each domain (e.g. papers, IR documents) gets its own satellite table (e.g.
`PaperRecord`) holding domain-specific fields. New domains extend this pattern rather than
inventing a parallel storage scheme.

### V. AG-UI Chat Protocol
The chat UI runs on the AG-UI protocol: `pydantic_ai`'s `AGUIAdapter` is wired directly into a
FastAPI endpoint, and the frontend connects with `@ag-ui/client`'s `HttpAgent`. CopilotKit and
Next.js are explicitly not used — the integration stays direct and minimal.

## Scope Constraints

v1 targets `localhost`, a single user, and no authentication layer. Multi-user support, remote
deployment, and auth are out of scope until a concrete need arises; do not build toward them
preemptively (see Principle II).

## Development Workflow

New features are built walking-skeleton style: a minimal slice through every layer involved
(backend service, persistence, agent/tool, frontend) is made to work end-to-end before any single
layer is deepened. `specs/README.md` tracks which spec is ready to implement, blocked, or
deliberately skipped; a spec is detailed (`spec.draft.md`) before implementation begins, and ADRs
under `docs/adr/` record decisions that would be hard to reverse later.

## Governance

This constitution supersedes ad hoc practice for the principles it states. Amendments are made by
editing this file directly (not through code review of application PRs) and follow semantic
versioning: MAJOR for backward-incompatible principle removals/redefinitions, MINOR for a new
principle or materially expanded guidance, PATCH for wording/clarification fixes. Each amendment
records its rationale in a Sync Impact Report comment at the top of this file. Compliance is
reviewed informally as specs are implemented — there is no separate automated gate — since this is
a single-user project without a review process to enforce against.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): original adoption date not recorded
before this file existed | **Last Amended**: 2026-08-30
