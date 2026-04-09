# T007 - Pipeline stabilization Phase 3: recovery guardrails, stale-job behavior, and retry containment

## Status
Done

## Objective
Harden recovery behavior so the pipeline stops churning through repeated failures, stale jobs are handled safely, and repeated identical failures are contained instead of creating noisy attempt chains.

## Why it matters
After Phases 1, 1.5, and 2, the next stability risk is recovery policy itself. The pipeline still needs clearer rules for stale jobs, repeated failures, and when automatic recovery should stop and require operator review.

## Scope
- Improve stale-job handling so slow-but-active work is not misclassified too aggressively.
- Add per-stage retry/recovery guardrails.
- Detect repeated identical failure signatures and prevent endless churn.
- Introduce a quarantine / manual-review path for videos that keep failing the same way.
- Make recovery decisions rely on explicit state from earlier phases.

## Out of scope
- Throughput or parallel worker changes
- Broad UI redesign
- Long-term observability and analytics beyond what is needed for safe recovery behavior

## Constraints
- Keep changes compatible with Phases 1, 1.5, and 2.
- Prefer clear containment rules over optimistic automatic retries.
- Do not mix unrelated cleanup into this phase.

## Done criteria
- Stale-job handling distinguishes active progress from truly stale work.
- Automatic retries are bounded and stage-aware.
- Repeated identical failures can be quarantined instead of endlessly retried.
- Recovery logic produces predictable operator-facing outcomes.
- Tests cover the new recovery/stale-job behavior.

## Validation
- BuildClaw implements against this file.
- QAClaw validates against this file.
- Focused regression/tests now cover recovery guardrails, manual-review blocking, repeat failure containment, and stale-job classification.
