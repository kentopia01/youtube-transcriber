# T042: Reranker and Query Expansion Experiment

## Status
Deferred pending evidence

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

## Decision gate (2026-07-20)
T043's seed benchmark reached a 91.7% hit rate with one ambiguous miss and found no
quality gain from larger candidate pools. Do not add reranking or HyDE/query-expansion
cost yet. Reopen this experiment after the benchmark contains at least 30 anonymized
real operator queries, or when a repeatable run falls below 90% hit rate or shows at
least three recurring miss patterns.
