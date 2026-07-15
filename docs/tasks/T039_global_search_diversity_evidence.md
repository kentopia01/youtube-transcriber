# T039: Global Search Diversity and Evidence Packing

## Status
Done

## Goal
Make global search results useful as evidence, not just ranked chunks.

## In scope
- Deduplicate repeated chunk IDs and near-identical text snippets.
- Diversify results with a per-video cap.
- Preserve enough flexibility to relax the cap when the corpus match is narrow.
- Build compact evidence snippets from matching sentences where possible.
- Add YouTube timestamp URLs when video IDs and timestamps are available.

## Out of scope
- LLM-based contextual compression.
- Cross-encoder reranking.
- Automatic answer generation.

## Guardrails
- Do not hide genuinely best results solely because they come from the same video.
- Keep evidence extraction deterministic and cheap.

## Validation
- Unit tests cover dedupe, per-video diversity, source type classification, timestamp URL creation, and evidence trimming.
