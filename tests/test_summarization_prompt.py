from app.services.summarization import CONSOLIDATION_PROMPT, SUMMARY_SYSTEM_PROMPT


def test_summary_prompt_uses_scan_first_contract():
    prompt = SUMMARY_SYSTEM_PROMPT

    assert "## 30-second take" in prompt
    assert "## Key takes" in prompt
    assert "## Useful details" in prompt
    assert "## Caveats / counterpoints" in prompt
    assert "## Ken relevance" in prompt
    assert "## Watch verdict" in prompt
    assert "not to list topics" in prompt
    assert "low-content transcript" in prompt


def test_consolidation_prompt_preserves_same_contract():
    prompt = CONSOLIDATION_PROMPT

    assert "scan-first intelligence brief" in prompt
    assert "## 30-second take" in prompt
    assert "## Key takes" in prompt
    assert "Skip / Skim / Watch fully" in prompt
