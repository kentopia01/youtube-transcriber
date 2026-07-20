# T043: Global Search Evaluation Benchmark

## Status
Done (seed baseline)

## Goal
Create a small repeatable benchmark for global corpus search quality and latency.

## In scope
- Build a set of representative real queries: names, technical terms, broad themes, vague questions, and summary-style questions.
- Record expected useful videos/chunks where known.
- Measure latency for baseline and optional advanced retrieval variants.
- Tune candidate limits, per-video caps, and source-type weighting.

## Out of scope
- Full academic IR benchmark construction.
- Large-scale annotation workflow.

## Guardrails
- Use this benchmark before adding heavier retrieval dependencies.
- Keep evaluation cheap enough to run locally.

## Validation
- Benchmark output gives enough evidence to decide whether reranking/query expansion should ship.

## Outcome (2026-07-20)
- Added `scripts/evaluate_global_search.py` and a 12-query, five-category seed set.
- The harness measures video-level hit rate, recall, MRR, result diversity, mean latency, and p95 latency without writing to the application database.
- The interleaved three-repeat run scored the default baseline at 91.7% hit rate, 0.792 MRR, and 64.3 ms mean / 81.5 ms p95 after warm-up.
- Removing the summary lane reduced hit rate to 83.3%; summaries remain necessary for vague and summary-style questions.
- Lean, diverse, and deep variants did not improve labeled quality. The diverse variant increased mean distinct videos from 8.2 to 11.7 without a meaningful latency penalty, but the seed set is too small to change production defaults confidently.
- T042 is deferred: one ambiguous miss in a seed set does not justify a reranker or query-expansion dependency. Reopen after at least 30 anonymized real operator queries or a repeatable sub-90% hit rate.
- The committed queries are corpus-grounded operator-style seeds, not captured production telemetry. Continue adding anonymized real queries manually.

## Validation evidence
- `.venv314/bin/pytest -q tests/test_global_search_eval_script.py tests/test_global_search_service.py tests/test_api_endpoints.py -k 'global_search or benchmark or ranked_video or score_query or markdown_report or committed_query or repetitions'` — 18 passed.
- `.venv314/bin/python scripts/evaluate_global_search.py --repeat 3` — 12 queries, five variants, 180 timed read-only requests plus 12 warm-ups.
- Full results: `docs/evaluations/T043_global_search_benchmark_2026-07-20.md`.
