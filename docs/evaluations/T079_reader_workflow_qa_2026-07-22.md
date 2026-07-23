# T079 Reader workflow QA — 2026-07-22

## Method

The live Reader was inspected at 1440x900 desktop and 390x844 mobile widths using the
real library (609 readable transcripts across 29 channels). The review covered Reader
Home, Library, an actual transcript, Highlights, document search, appearance, resume,
and annotation controls. Automated Chromium checks then exercised both workspaces.

## Findings and disposition

| Severity | Workflow | Evidence | Disposition |
|---|---|---|---|
| High | Read a transcript on mobile | The fixed `Aa · Search · Progress` pill occupied roughly half the viewport width and covered multiple transcript lines. | Shipped a compact 48px, accessibly named `Aa` control in the left transcript gutter. Final vision check shows the reading column unobstructed. |
| Medium | Understand the Reader Home warning | The notice said transcript jobs needed attention while the only live warnings were two report deliveries. | Reworded it to the accurate domain-neutral “Operations has items to review.” The linked count and Operations ownership remain clear. |
| None | Browse/resume | Home shelves, Library filters/cards, reading progress, and channel browsing were legible and fit both viewports. | No change; avoid aesthetic churn. |
| None | Navigate/read | Continuous transcript typography, outline, timestamp links, search, and appearance controls were usable and retained no-JavaScript reading access. | No change. |
| None | Annotate/revisit | Highlights empty state, notebook entry point, selection controls, and jump-back structure were coherent. | No change; no speculative feature added. |

## Verification

- Static accessibility regression contracts pass.
- Live Chromium feature-area gate: `30/30` passed.
- No horizontal overflow, unnamed visible controls, or sub-44px mobile controls were
  reported on Reader Home, Library, transcript, Research, Chat, Highlights, or
  Operations pages.
- The frontend skill's Stitch preflight found no configured Stitch tools or API key, so
  the assessment used direct live-browser screenshots and vision rather than generated
  redesign variants.
