# T070 - Document Intelligence and Search/Ask Consolidation

## Status

Done — implemented and live-validated on 2026-07-21

## Objective

Add explicit document-scoped intelligence to Reader and consolidate overlapping
Chat, Search, and Global Search entry points into one coherent research surface.

## Why it matters

The current frontend presents multiple poorly differentiated research paths. A
reader should be able to search within a transcript, ask about the current video,
or search/ask across the library without guessing which page to use.

## Scope

- Add explicit `video_id` retrieval scope to the shared chat/search contract.
- Add Ask this transcript from the Reader notebook.
- Add selection-scoped explain/summarize/context actions.
- Add semantic chapter generation with stored provenance and deterministic
  fallback.
- Consolidate Reader Search/Ask UI with clear current-document, channel, and
  whole-library scopes.
- Preserve evidence snippets, timestamps, citations, and source-type labels.
- Keep Operations-specific job/report diagnostics outside Reader search.

## Out of scope

- Replacing Postgres/pgvector.
- Unbounded agentic research.
- Automatic AI calls on every document open or selection.
- Removing compatibility routes before usage is migrated.

## Constraints

- LLM and embedding failures must not block reading.
- Scope is explicit in API inputs and visible in UI.
- Budget checks, provider fallback, and cost attribution remain intact.
- Answers remain grounded in stored transcript/summary evidence.

## Done criteria

- Current-video Ask cannot retrieve evidence from other videos.
- Whole-library and channel scopes remain available and clearly labeled.
- Selection actions use only the selected passage plus explicitly retrieved
  context.
- Generated chapters preserve timestamps and fall back safely.
- Legacy Search/Global/Chat paths have tested migration behavior.
- Retrieval, security, rendering, browser, and provider-failure tests pass.

## Validation

- Search and Ask accept an exact `video_id` scope through every retrieval and
  fallback path; tests prove current-video queries cannot leak cross-video
  evidence.
- `/search` is the consolidated Research surface with library, channel, current
  transcript, evidence-source, Search, and Ask modes. `/global-search` remains a
  tested compatibility redirect.
- Selection Explain, Summarize, and Context actions use the selected passage as
  explicit evidence plus explicitly retrieved context.
- Migration `021` stores semantic chapter sets with source fingerprints, model,
  generator version, provenance, and fallback reason. Generation is opt-in and
  provider/parse failures store deterministic timestamped chapters.
- A live exact-video search returned 10/10 results from only the requested
  transcript; chapter access returned nine deterministic chapters without an
  LLM call.
- Retrieval, provider-failure, rendering, security, and live browser coverage
  pass in the final `1350 passed, 11 skipped`, `33/33` HTTP, and `30/30` browser
  gates.
