# T069 - Reader Annotations and Notebook

## Status

Done — implemented and live-validated on 2026-07-21

## Objective

Add durable highlights, notes, bookmarks, and a notebook that can return the
reader to the exact transcript passage.

## Why it matters

Reading becomes useful knowledge work when important passages can be captured,
annotated, reviewed, and revisited.

## Scope

- Add annotation model/migration and CRUD APIs.
- Support highlight, note, and bookmark types.
- Anchor annotations with video ID, timestamp range, selected-text snapshot, and
  resilient block/offset metadata.
- Add selection actions in Reader.
- Add document Notebook with jump-back navigation.
- Add library-level Highlights view.
- Add copy/export of selected annotations in a safe text/Markdown format.
- Define reconciliation behavior after transcript regeneration.

## Out of scope

- Collaborative/shared annotations.
- Native stylus or handwriting support.
- Automatic AI processing of every highlight.
- Third-party note-system synchronization.

## Constraints

- Do not rely only on segment UUIDs; transcription retries replace segment rows.
- Annotation rendering remains escaping-first.
- Selection actions remain usable by keyboard and touch.

## Done criteria

- Highlights, notes, and bookmarks persist and render at the correct passage.
- Notebook and library views jump back to the saved location.
- Transcript regeneration preserves or explicitly flags annotation attachment.
- Export is safe and deterministic.
- Migration/API/rendering/security/browser tests pass.

## Validation

- Migration `020` adds durable annotation storage and is applied live.
- Annotation creation validates the selected-text snapshot against transcript
  offsets. Reconciliation preserves exact anchors and safely degrades
  whitespace-normalized matches to block-level attachment.
- Reader selection actions, passage rendering, notebook jump/delete, library
  Highlights, and safe Markdown export are implemented.
- API, model, reconciliation, escaping, rendering, and browser contracts pass
  within the `1350 passed, 11 skipped` repository gate and `30/30` live browser
  matrix.
