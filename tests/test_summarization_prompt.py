import json

from app.services.summarization import (
    CONSOLIDATION_PROMPT,
    MARKDOWN_BRIEF_CONTRACT,
    SUMMARY_MARKDOWN_FALLBACK_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    normalize_summary_response,
)


def test_summary_prompt_uses_scan_first_contract():
    prompt = SUMMARY_SYSTEM_PROMPT

    assert "Return only valid JSON" in prompt
    assert "at_a_glance" in prompt
    assert "executive_summary" in prompt
    assert "key_takeaways" in prompt
    assert "detailed_brief" in prompt
    assert "notable_concepts_terms" in prompt
    assert "operator_notes" in prompt
    assert "watch_map" in prompt
    assert "source_metadata" in prompt
    assert "not to list topics" in prompt
    assert "low_content=true" in prompt
    assert "claim, evidence/example, caveat, and implication" in prompt


def test_consolidation_prompt_preserves_same_contract():
    prompt = CONSOLIDATION_PROMPT

    assert "scan-first intelligence brief" in prompt
    assert "Return only valid JSON" in prompt
    assert "key_takeaways" in prompt
    assert "Skip / Skim / Watch fully" in prompt


def test_markdown_fallback_prompt_uses_quality_gate_headings():
    prompt = SUMMARY_MARKDOWN_FALLBACK_PROMPT

    assert "prior structured JSON attempt did not pass" in prompt
    for heading in (
        "## At-a-Glance",
        "## Executive Summary",
        "## Key Takeaways",
        "## Detailed Brief",
        "## Notable Concepts & Terms",
        "## Operator Notes / Why Ken Should Care",
        "## Watch Map",
        "## Source/Metadata",
    ):
        assert heading in prompt
        assert heading in MARKDOWN_BRIEF_CONTRACT


def test_structured_json_response_is_normalized_to_report_markdown():
    response = {
        "at_a_glance": {
            "verdict": "Skim",
            "core_thesis": "Agents need reliable handoffs.",
            "why_it_matters": "It changes AI ops workflow design.",
            "best_use": "Use it as a checklist.",
        },
        "executive_summary": [
            "The speaker argues that agent workflows only scale when handoffs are observable.",
            "The evidence is a production failure story and an eval pattern.",
        ],
        "key_takeaways": [
            {
                "claim": "Handoffs are the real control plane.",
                "evidence": "The transcript names decision traces and eval logs.",
                "caveat": "It does not prove every team needs the same stack.",
                "implication": "Ken should capture handoff state before adding more agents.",
                "timestamp": "03:12",
            }
            for _ in range(5)
        ],
        "detailed_brief": [
            {
                "heading": "Decision traces",
                "claims": ["Traces make agent behavior reviewable."],
                "evidence": ["The speaker compares traces with plain documents."],
                "caveats": ["Trace quality still depends on the schema."],
                "implications": ["Ken should store the reason, evidence, and next action."],
            }
            for _ in range(3)
        ],
        "notable_concepts_terms": [{"term": "Decision trace", "meaning": "A compact record of why an agent acted."}],
        "operator_notes": ["Relevant to Ken's agent systems and AI ops workflow."],
        "watch_map": [{"timestamp": "03:12", "note": "Decision trace argument."}],
        "source_metadata": {
            "title": "Trace video",
            "transcript_word_count": 1600,
            "timestamp_note": "Transcript included timestamps.",
        },
        "low_content": False,
    }

    markdown = normalize_summary_response(json.dumps(response), title="Trace video", transcript_word_count=1600)

    assert "## At-a-Glance" in markdown
    assert "## Executive Summary" in markdown
    assert "## Key Takeaways" in markdown
    assert "Claim: Handoffs are the real control plane." in markdown
    assert "Evidence: The transcript names decision traces and eval logs." in markdown
    assert "Implication: Ken should capture handoff state before adding more agents." in markdown
