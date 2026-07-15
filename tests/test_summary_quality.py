from __future__ import annotations

from app.services.summary_quality import (
    format_summary_quality_messages,
    validate_summary_contract,
)


def _summary(*, key_takes: str | None = None, ken_relevance: str | None = None, verdict: str = "Skim") -> str:
    return f"""
## At-a-Glance
- Verdict: {verdict}
- Core thesis: The speaker argues AI operators should use agents for leverage, but only with clear evals and workflow guardrails.
- Why it matters: Ken can reuse the operating pattern in agent systems.
- Best use: Skim for the workflow pattern.

## Executive Summary
The speaker argues that agent leverage comes from narrowing automation to a concrete workflow, instrumenting evals, and keeping human review where quality can silently regress.

The useful angle for Ken is not a new tool recommendation; it is an operating pattern for AI ops, content/business workflows, and GTM systems.

## Key Takeaways
{key_takes or "- Claim: Agents can remove repetitive research work when scoped to a narrow workflow. | Evidence: The video names research handoffs and review loops. | Caveat: It does not prove generic chatbots help. | Implication: Ken should define workflow boundaries before automation.\n- Claim: Evals matter because unchecked automation creates silent quality regressions. | Evidence: The speaker points to quality checks and human review. | Caveat: Eval design is still hard. | Implication: Ken should treat evals as part of the system, not afterthoughts.\n- Claim: GTM teams can turn content into repeatable sales insights. | Evidence: The transcript ties content research to sales workflows. | Caveat: The examples assume clean source data. | Implication: Ken can reuse the pattern for content/business opportunities.\n- Claim: The core idea is an operating pattern rather than tooling news. | Evidence: The speaker emphasizes process, scopes, and review. | Caveat: Tool choice still matters in implementation. | Implication: Ken should port the pattern into his personal workflow."}

## Detailed Brief
### Workflow scope
- Claims: Agents work better when scoped to a narrow workflow.
- Evidence: The video names evals, agent handoffs, and GTM workflows as concrete implementation areas.
- Caveats: Broad automation can hide quality failures.
- Implications: Ken should pick bounded workflows first.

### Quality loop
- Claims: Review and evals are part of the product surface.
- Evidence: The speaker links evals with human review.
- Caveats: The transcript does not prove one eval design fits every workflow.
- Implications: Ken should store quality evidence with outputs.

### GTM leverage
- Claims: The same workflow can feed sales and content loops.
- Evidence: GTM workflows are named as a concrete use case.
- Caveats: It assumes useful input material.
- Implications: Ken can turn transcript intelligence into sales/content prompts.

## Notable Concepts & Terms
- Agent handoff: A transfer of context or task ownership between tools or agents.
- Eval: A check that catches quality regression.
- GTM workflow: A repeatable sales/content process.
- Human review: A guardrail for automation quality.

## Operator Notes / Why Ken Should Care
{ken_relevance or "- Relevant to Ken's agent systems, AI ops, content/business opportunities, investing, GTM, and personal workflow."}

## Source/Metadata
- Title: Test video
- Transcript words: 1800
- Timestamp note: Timestamps or chapters were unavailable in the transcript.
""".strip()


def test_validate_summary_contract_passes_well_formed_scan_first_summary():
    result = validate_summary_contract(_summary(), word_count=1200)

    assert result.passed
    assert result.key_take_count == 4
    assert result.minimum_key_takes == 4
    assert result.watch_verdict == "Skim"
    assert result.warnings == ()
    assert format_summary_quality_messages(result)[0].startswith("PASS:")


def test_validate_summary_contract_requires_more_depth_for_long_transcripts():
    result = validate_summary_contract(_summary(), word_count=1800, duration_seconds=720)

    assert not result.passed
    assert result.requires_deep_brief
    assert result.minimum_key_takes == 5
    assert any("expected at least 5" in error for error in result.errors)


def test_validate_summary_contract_errors_on_missing_required_sections_and_verdict():
    result = validate_summary_contract(
        """
## At-a-Glance
This is a generic paragraph.

## Key Takeaways
- One point.
""".strip(),
        word_count=1800,
    )

    assert result.is_malformed
    assert any("missing required heading" in error for error in result.errors)
    assert any("Operator Notes" in error for error in result.errors)
    assert any("Skip / Skim / Watch fully" in error for error in result.errors)


def test_validate_summary_contract_blocks_substantive_summary_with_too_few_key_takes():
    result = validate_summary_contract(
        _summary(key_takes="- One specific claim with an implication."),
        word_count=2200,
    )

    assert not result.passed
    assert result.is_malformed
    assert result.key_take_count == 1
    assert any("expected at least 5" in error for error in result.errors)


def test_validate_summary_contract_allows_low_content_with_fewer_key_takes():
    low_content = _summary(
        key_takes="- The upload is mostly music/repetition, so there are no reliable substantive claims to extract.",
        ken_relevance="- Low relevance for Ken because this appears to be a low-content placeholder rather than agent systems or GTM material.",
        verdict="Skip",
    ).replace(
        "The speaker argues AI operators should use agents for leverage, but only with clear evals and workflow guardrails.",
        "Low-content transcript: the upload is mostly music and repeated placeholder text, so little can be learned.",
    )

    result = validate_summary_contract(low_content, word_count=120)

    assert result.passed
    assert result.is_low_content
    assert result.minimum_key_takes == 2
    assert result.watch_verdict == "Skip"
    assert any("accepted because the summary explicitly flags low content" in warning for warning in result.warnings)


def test_validate_summary_contract_blocks_short_non_low_content_summary_with_too_few_key_takes():
    result = validate_summary_contract(
        _summary(key_takes="- One specific claim with an implication."),
        word_count=500,
    )

    assert not result.passed
    assert result.minimum_key_takes == 4
    assert any("expected at least 4" in error for error in result.errors)


def test_validate_summary_contract_blocks_false_positive_low_content_wording():
    result = validate_summary_contract(
        _summary(
            key_takes="- Claim: The speaker discusses licensing strategy for AI-generated music products. | Evidence: The transcript names rights and product strategy. | Caveat: This is not a low-content transcript. | Implication: Ken should evaluate product risk before GTM.",
            ken_relevance="- Relevant to Ken's agent systems and AI ops workflow, and this is not a low-content transcript.",
        ),
        word_count=1200,
    )

    assert not result.passed
    assert not result.is_low_content
    assert any("expected at least 4" in error for error in result.errors)


def test_validate_summary_contract_warns_when_ken_relevance_is_generic():
    result = validate_summary_contract(
        _summary(ken_relevance="- This is relevant because it may matter later."),
        word_count=1200,
    )

    assert result.passed
    assert any("Ken focus area" in warning for warning in result.warnings)


def test_validate_summary_contract_does_not_require_watch_map():
    summary = _summary().replace(
        "- Timestamp note: Timestamps or chapters were unavailable in the transcript.",
        "- Timestamp note: Navigation was intentionally omitted from the report.",
    )

    result = validate_summary_contract(
        summary.replace(
            "## Detailed Brief",
            "- Claim: The summary should remain useful without timestamp navigation. | Evidence: The report carries verdict, takeaways, and operator notes. | Implication: Ken can read the brief without fake Watch Map entries.\n\n## Detailed Brief",
        ),
        word_count=1800,
        duration_seconds=720,
    )

    assert result.passed
    assert not any("Watch Map" in warning for warning in result.warnings)
