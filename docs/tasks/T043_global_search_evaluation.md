# T043: Global Search Evaluation Benchmark

## Status
Planned

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
