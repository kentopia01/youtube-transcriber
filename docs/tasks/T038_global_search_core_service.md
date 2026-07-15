# T038: Global Search Core Service

## Status
Done

## Goal
Add a service that searches the whole ingested corpus using existing vector and keyword infrastructure.

## In scope
- Add `app/services/global_search.py`.
- Search all videos by default, not just chat-enabled videos.
- Support optional channel and source-type filters.
- Retrieve from vector, keyword, and summary-focused lanes.
- Fuse candidates with reciprocal rank fusion.
- Return structured candidates with score components and source metadata.

## Out of scope
- Changing existing `semantic_search()`.
- Adding external vector databases.
- Adding reranker or query-expansion dependencies.

## Guardrails
- Keep candidate pools bounded for basic hardware.
- Use parameterized SQL.
- Preserve source metadata needed for citations.

## Validation
- Unit tests cover RRF fusion and SQL helper behavior where practical.
- Focused endpoint tests prove service wiring works through the API.
