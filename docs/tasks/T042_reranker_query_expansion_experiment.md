# T042: Reranker and Query Expansion Experiment

## Status
Planned

## Goal
Evaluate whether reranking and query expansion improve Ken's real global-search queries enough to justify extra cost.

## In scope
- Try query fusion/HyDE against the global search service.
- Try bounded reranking over the top 30 to 50 candidates.
- Prefer API rerankers or very small local rerankers on basic hardware.
- Make all advanced inference optional and off by default.

## Out of scope
- Mandatory local heavy inference.
- Replacing the v1 retrieval service.
- GraphRAG or RAPTOR production rollout.

## Guardrails
- Measure quality and latency before keeping any dependency.
- Never rerank the full corpus.

## Validation
- Compare baseline global search against reranked/query-expanded variants on a fixed query set.
