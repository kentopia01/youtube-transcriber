# T071 - Frontend Production and Accessibility Release Gate

## Status

Done — release gate passed on 2026-07-21

## Objective

Complete the shared frontend production, accessibility, responsive, and browser
quality gate for Reader and Operations.

## Why it matters

The existing frontend is coherent but depends on runtime CDN tooling and misses
contrast, focus, accessible-name, live-region, progress-label, touch-target, and
mobile-table requirements. Both new workspaces need enforceable quality rather
than another markup-presence test suite.

## Scope

- Replace Tailwind browser compilation with static production assets.
- Pin or locally bundle required frontend dependencies.
- Move substantial inline behavior into versioned static modules.
- Correct shared color-token contrast and visible focus states.
- Add skip links, accessible names, live regions, progress labels, dialog naming,
  and 44px mobile targets.
- Replace inappropriate mobile operations tables with responsive cards or clear
  overflow affordances.
- Resolve the live-QA finding that the dashboard Recent Jobs table stays within
  its scroll container at 390px but compresses columns enough to impair scanning;
  prefer a mobile job-card treatment over a merely clipped/scrollable table.
- Add desktop/mobile browser flows for both workspaces.
- Add automated accessibility and visual-regression coverage.
- Run final compatibility, performance, rendering-safety, and non-mutating QA.

## Out of scope

- A new frontend framework.
- Separate Reader/Operations deployment.
- Broad backend refactors unrelated to frontend contracts.
- Live queue mutation in default QA.

## Constraints

- Accessibility is also enforced in T064-T070; this task closes cross-workspace
  gaps rather than postponing all accessibility work.
- Default QA remains read-only/non-mutating.
- External-resource failure must not make core navigation or reading unusable.

## Done criteria

- No runtime Tailwind browser compiler remains in production pages.
- Reader and Operations meet WCAG-AA token and interaction requirements.
- Reflow passes at 320 CSS pixels and 400% zoom-equivalent layouts.
- Keyboard-only and screen-reader names/states are covered.
- Desktop/mobile browser suites cover navigation, reading progress, annotations,
  queue polling, recovery affordances, and compatibility redirects.
- Static, focused, and default full-suite gates pass with documented opt-in live
  mutation boundaries.

## Validation

- Core fonts, icons, utility CSS, HTMX-compatible behavior, and Markdown
  rendering are local production assets; runtime CDN/compiler dependencies are
  removed.
- Page behavior is in versioned static modules. Operations and legacy Submit
  share one submission module instead of duplicate implementations, and an
  automated contract prevents executable inline scripts from returning.
- Shared text/status tokens meet WCAG AA contrast; focus, accessible names and
  states, live regions, progress semantics, mobile job-card reflow, and 44px
  mobile targets have automated coverage.
- Browser QA checks same-origin failures, JavaScript exceptions, horizontal
  overflow, control names, mobile targets, navigation, Reader interactions,
  queue/job pages, Research, and compatibility redirects.
- Release results: `1350 passed, 11 skipped`, `33/33` live HTTP checks, and
  `30/30` desktop/mobile browser checks. Default QA did not enqueue jobs, send
  chat prompts, mutate annotations, generate chapters, or deliver Telegram
  messages.
