# T065 - Reader and Operations Workspace Boundary

## Status

Done — 2026-07-21

## Objective

Create distinct Reader and Operations route, layout, navigation, and frontend
boundaries inside the existing FastAPI deployment.

## Why it matters

Reader and Operations serve different intentions and require different hierarchy,
density, and interaction patterns. A clean boundary prevents the new reader from
becoming another panel inside the existing operations dashboard.

## Scope

- Add Reader and Operations route namespaces.
- Add separate Reader and Operations base templates/front-end entrypoints.
- Add an accessible workspace switcher.
- Establish target routes: Reader Home at `/`, Reader under `/read`, Operations
  under `/ops`.
- Add compatibility redirects for current queue, job, video, and channel URLs.
- Define shared component/token boundaries without duplicating security helpers.
- Define workspace-aware navigation active states and page titles.
- Preserve API routes and backend service ownership.

## Out of scope

- Reader progress, annotations, or AI features.
- Separate services, deployments, databases, or repositories.
- Rewriting the frontend in React/Vue or another new framework.
- Multi-user authorization from T049.

## Constraints

- Existing bookmarks and API clients remain functional through compatibility.
- Reader and Operations must work at 320px and keyboard-only navigation.
- Shared controls meet WCAG-AA and 44px mobile-target requirements.

## Done criteria

- Reader and Operations render from separate base layouts.
- Workspace switching is understandable, accessible, and preserves destination
  context where practical.
- Existing public web routes have tested compatibility behavior.
- API routes and worker behavior are unchanged.
- Desktop/mobile route and navigation browser tests pass.

## Validation

- Reader and Operations render from `reader_base.html` and
  `operations_base.html`, with a shared low-level shell and tokens.
- Canonical routes are `/`, `/read`, `/read/{video_id}`, `/ops`,
  `/ops/queue`, and `/ops/jobs/{job_id}`; legacy web URLs return tested 307
  redirects while API paths remain unchanged.
- Default regression suite: `1302 passed, 11 skipped`.
- Read-only live feature matrix: `29/29 passed` against the running service.
- Chromium QA passed at 1440px and 320px with no page-level horizontal
  overflow; both mobile menus expose 44px targets and update `aria-expanded`.
