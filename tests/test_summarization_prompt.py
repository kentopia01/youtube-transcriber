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
    assert "source_metadata" in prompt
    assert "not to list topics" in prompt
    assert "low_content=true" in prompt
    assert "Every key_takeaway must include claim, evidence, and implication" in prompt
    assert "Include caveat only when material" in prompt
    assert "Section jobs and deduplication" in prompt
    assert "Detailed Brief is an appendix for extra detail" in prompt
    assert "Operator Notes must be action-only" in prompt
    assert "Do not include a Watch Map section" in prompt
    assert "Verdict calibration" in prompt
    assert "Use Watch fully when the transcript contains high-signal material" in prompt
    assert "agent systems, OpenClaw, AI ops" in prompt
    assert "Do not default to Skim just because the brief itself is complete" in prompt


def test_consolidation_prompt_preserves_same_contract():
    prompt = CONSOLIDATION_PROMPT

    assert "scan-first intelligence brief" in prompt
    assert "Return only valid JSON" in prompt
    assert "key_takeaways" in prompt
    assert "Skip / Skim / Watch fully" in prompt
    assert "Section jobs and deduplication" in prompt
    assert "Verdict calibration" in prompt


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
        "## Source/Metadata",
    ):
        assert heading in prompt
        assert heading in MARKDOWN_BRIEF_CONTRACT
    assert "Use Watch fully when the source is directly relevant" in prompt
    assert "Do not default to Skim just because the brief is complete" in prompt
    assert "Key Takeaways are the top claims only" in prompt
    assert "Detailed Brief is an appendix for extra details" in prompt
    assert "Operator Notes are action-only" in prompt
    assert "Do not include Watch Map" in prompt


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
                "caveat": None,
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
    assert "Caveat: No caveat stated" not in markdown
    assert "## Watch Map" not in markdown


def test_non_material_caveats_are_not_rendered_as_filler():
    response = {
        "at_a_glance": {
            "verdict": "Watch fully",
            "core_thesis": "The workflow needs evidence-backed handoffs.",
            "why_it_matters": "It changes how Ken should run agent QA.",
            "best_use": "Use the checklist.",
        },
        "executive_summary": ["The speaker gives a practical agent QA pattern."],
        "key_takeaways": [
            {
                "claim": "Review evidence should travel with every handoff.",
                "evidence": "The transcript names test logs and screenshots.",
                "caveat": "No caveat stated in the transcript.",
                "implication": "Ken should require evidence in task handoffs.",
                "timestamp": None,
            },
            {
                "claim": "Risky changes need stronger gates.",
                "evidence": "The transcript separates low-risk and high-risk work.",
                "caveat": "The transcript does not quantify the failure rate.",
                "implication": "Ken should keep approval thresholds risk-based.",
                "timestamp": None,
            },
        ],
        "detailed_brief": [
            {
                "heading": "Evidence handoff appendix",
                "claims": ["Additional details about screenshots."],
                "evidence": ["The speaker references visual proof."],
                "caveats": [],
                "implications": ["Useful for QAClaw handoff design."],
            }
        ],
        "notable_concepts_terms": [{"term": "Evidence bundle", "meaning": "Proof attached to a handoff."}],
        "operator_notes": ["Add evidence bundles to agent handoffs."],
        "watch_map": [{"timestamp": None, "note": "Legacy field should be ignored."}],
        "source_metadata": {
            "title": "Agent QA",
            "transcript_word_count": 1200,
            "timestamp_note": "No timestamps were provided.",
        },
        "low_content": False,
    }

    markdown = normalize_summary_response(json.dumps(response), title="Agent QA", transcript_word_count=1200)

    assert "Caveat: No caveat stated" not in markdown
    assert "Caveat: The transcript does not quantify the failure rate." in markdown
    assert "Legacy field should be ignored" not in markdown


def test_redundant_detailed_brief_lines_are_dropped():
    response = {
        "at_a_glance": {
            "verdict": "Watch fully",
            "core_thesis": "Agent handoffs need evidence.",
            "why_it_matters": "It affects Ken's agent systems.",
            "best_use": "Use it as a QA checklist.",
        },
        "executive_summary": ["The speaker explains why agent handoffs need evidence."],
        "key_takeaways": [
            {
                "claim": "Handoffs are the real control plane.",
                "evidence": "The transcript names decision traces and eval logs.",
                "caveat": None,
                "implication": "Ken should capture handoff state before adding more agents.",
            }
        ],
        "detailed_brief": [
            {
                "heading": "Repeated handoff point",
                "claims": ["Handoffs are the real control plane."],
                "evidence": ["The transcript names decision traces and eval logs."],
                "caveats": ["Trace quality still depends on schema design."],
                "implications": ["Ken should capture handoff state before adding more agents."],
            }
        ],
        "notable_concepts_terms": [{"term": "Decision trace", "meaning": "A record of why an agent acted."}],
        "operator_notes": ["Relevant to Ken's agent systems and AI ops workflow."],
        "source_metadata": {"title": "Trace video", "transcript_word_count": 1600},
        "low_content": False,
    }

    markdown = normalize_summary_response(json.dumps(response), title="Trace video", transcript_word_count=1600)

    assert "- Claims: Handoffs are the real control plane." not in markdown
    assert "- Evidence: The transcript names decision traces and eval logs." not in markdown
    assert "- Implications: Ken should capture handoff state before adding more agents." not in markdown
    assert "Caveats: Trace quality still depends on schema design." in markdown
