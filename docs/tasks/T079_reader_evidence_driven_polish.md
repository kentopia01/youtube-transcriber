# T079 - Evidence-driven Reader workflow polish

## Status

Done

## Objective

Observe the live Reader with the real library and implement only changes that
materially reduce demonstrated browse, resume, navigate, or annotate friction.

## In scope

- Desktop/mobile visual and keyboard review of Reader Home, Library, document,
  highlights, search, resume, appearance, and annotation workflows.
- Record findings with evidence, severity, and disposition.
- Implement narrowly scoped fixes for reproduced high-value friction.
- Repeat accessibility, reflow, and browser regression gates.

## Out of scope

- Aesthetic churn, speculative social features, or mandatory LLM processing.

## Done criteria

- The evaluation names the observed workflow, evidence, and outcome for each finding.
- Any shipped UI change has a regression test and preserves no-JavaScript reading access.
- Final Reader checks pass at desktop and mobile widths.

## Validation

- Visually reviewed Reader Home, Library, transcript, and Highlights at desktop and
  390x844 mobile widths using the live 609-transcript library.
- Replaced the wide fixed mobile reading-tools label with an accessible 48px `Aa`
  control positioned in the transcript gutter; the final viewport shows no reading-
  column obstruction.
- Corrected the Reader Home notice so report-delivery warnings are not mislabeled as
  transcript-job failures.
- Both changes have static regression contracts; the live Chromium gate passes
  `30/30` across desktop/mobile navigation, reflow, labels, targets, and interactions.
