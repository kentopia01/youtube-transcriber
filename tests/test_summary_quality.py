from __future__ import annotations

from app.services.summary_quality import (
    format_summary_quality_messages,
    validate_summary_contract,
)


def _summary(*, key_takes: str | None = None, ken_relevance: str | None = None, verdict: str = "Skim") -> str:
    return f"""
## 30-second take
The speaker argues AI operators should use agents for leverage, but only with clear evals and workflow guardrails.

## Key takes
{key_takes or "- Agents can remove repetitive research work when scoped to a narrow workflow.\n- Evals matter because unchecked automation creates silent quality regressions.\n- GTM teams can use the workflow to turn content into repeatable sales insights.\n- The implication is that Ken should treat this as an ops pattern, not just tooling news."}

## Useful details
- The video names evals, agent handoffs, and GTM workflows as concrete implementation areas.

## Caveats / counterpoints
- The speaker does not prove the approach works for every team.

## Ken relevance
{ken_relevance or "- Relevant to Ken's agent systems, AI ops, content/business opportunities, investing, GTM, and personal workflow."}

## Watch verdict
{verdict} — useful enough to sample, but the summary captures the core take.
""".strip()


def test_validate_summary_contract_passes_well_formed_scan_first_summary():
    result = validate_summary_contract(_summary(), word_count=1800)

    assert result.passed
    assert result.key_take_count == 4
    assert result.minimum_key_takes == 4
    assert result.watch_verdict == "Skim"
    assert result.warnings == ()
    assert format_summary_quality_messages(result)[0].startswith("PASS:")


def test_validate_summary_contract_errors_on_missing_required_sections_and_verdict():
    result = validate_summary_contract(
        """
## 30-second take
This is a generic paragraph.

## Key takes
- One point.
""".strip(),
        word_count=1800,
    )

    assert result.is_malformed
    assert any("missing required heading" in error for error in result.errors)
    assert any("Ken relevance" in error for error in result.errors)
    assert any("Watch verdict" in error for error in result.errors)


def test_validate_summary_contract_blocks_substantive_summary_with_too_few_key_takes():
    result = validate_summary_contract(
        _summary(key_takes="- One specific claim with an implication."),
        word_count=2200,
    )

    assert not result.passed
    assert result.is_malformed
    assert result.key_take_count == 1
    assert any("expected at least 4" in error for error in result.errors)


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
            key_takes="- The speaker discusses licensing strategy for AI-generated music products.",
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
        word_count=1600,
    )

    assert result.passed
    assert any("Ken focus area" in warning for warning in result.warnings)
